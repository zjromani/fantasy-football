const encoder = new TextEncoder();

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "POST" && url.pathname === "/prepare") {
      return prepare(request, env);
    }
    if (request.method === "GET" && url.pathname === "/approve") {
      return confirmation(url, "Approve");
    }
    if (request.method === "POST" && url.pathname === "/approve") {
      return approve(url, env);
    }
    if (request.method === "GET" && url.pathname === "/ignore") {
      return confirmation(url, "Ignore");
    }
    if (request.method === "POST" && url.pathname === "/ignore") {
      return ignore(url, env);
    }
    return new Response("Not found", { status: 404 });
  },
  async scheduled(_event, env) {
    await sendReminders(env);
  },
};

function confirmation(url, label) {
  const action = escapeHtml(`${url.pathname}${url.search}`);
  return new Response(
    `<!doctype html><meta name="viewport" content="width=device-width">` +
      `<title>Fantasy ${label}</title>` +
      `<form method="post" action="${action}">` +
      `<button type="submit">${label} fantasy action</button></form>`,
    { headers: { "Content-Type": "text/html; charset=utf-8" } },
  );
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

async function prepare(request, env) {
  const authorization = request.headers.get("authorization");
  if (authorization !== `Bearer ${env.INGEST_TOKEN}`) {
    return new Response("Unauthorized", { status: 401 });
  }
  const record = await request.json();
  if (!record.id || !record.hash || !record.expires || !record.decision) {
    return new Response("Invalid approval", { status: 400 });
  }
  record.createdAt = Math.floor(Date.now() / 1000);
  record.reminded = false;
  await env.DB.prepare(
    `INSERT INTO approvals(
      id, payload_hash, expires_at, decision_json, status, reminded, created_at
    ) VALUES (?, ?, ?, ?, 'pending', 0, ?)
    ON CONFLICT(id) DO NOTHING`,
  )
    .bind(
      record.id,
      record.hash,
      record.expires,
      JSON.stringify(record.decision),
      record.createdAt,
    )
    .run();
  return Response.json({ status: "prepared" });
}

async function approve(url, env) {
  const verified = await verifyAndConsume(url, env, "approved");
  if (verified instanceof Response) return verified;
  const { id, hash, stored } = verified;

  const payload = encodeBase64(JSON.stringify(stored.decision));
  const dispatchSignature = await sign(
    env.SIGNING_SECRET,
    `${id}.${hash}.${stored.expires}.${payload}`,
  );
  const response = await fetch(
    `https://api.github.com/repos/${env.GITHUB_REPOSITORY}/actions/workflows/execute-approval.yml/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        Accept: "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "fantasy-auto-gm-approval-worker",
      },
      body: JSON.stringify({
        ref: "main",
        inputs: {
          payload,
          hash,
          approval_id: id,
          expires: String(stored.expires),
          signature: dispatchSignature,
        },
      }),
    },
  );
  if (!response.ok) {
    return new Response("GitHub dispatch failed", { status: 502 });
  }
  return new Response("Approved. Execution has been dispatched.", {
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
}

async function ignore(url, env) {
  const verified = await verifyAndConsume(url, env, "ignored");
  if (verified instanceof Response) return verified;
  return new Response("Ignored. No action was dispatched.");
}

async function verifyAndConsume(url, env, consumedStatus) {
  const id = url.searchParams.get("id") || "";
  const hash = url.searchParams.get("hash") || "";
  const expires = Number(url.searchParams.get("expires") || 0);
  const signature = url.searchParams.get("signature") || "";
  if (Math.floor(Date.now() / 1000) >= expires) {
    return new Response("Approval expired", { status: 410 });
  }
  const expected = await sign(env.SIGNING_SECRET, `${id}.${hash}.${expires}`);
  if (!timingSafeEqual(signature, expected)) {
    return new Response("Invalid signature", { status: 403 });
  }
  const row = await env.DB.prepare(
    `SELECT payload_hash, expires_at, decision_json
     FROM approvals WHERE id = ? AND status = 'pending'`,
  )
    .bind(id)
    .first();
  if (!row) {
    return new Response("Approval missing or already used", { status: 409 });
  }
  if (row.payload_hash !== hash || row.expires_at !== expires) {
    return new Response("Approval record mismatch", { status: 409 });
  }
  const consumed = await env.DB.prepare(
    `UPDATE approvals SET status = ?, consumed_at = unixepoch()
     WHERE id = ? AND status = 'pending' AND expires_at > unixepoch()`,
  )
    .bind(consumedStatus, id)
    .run();
  if (consumed.meta.changes !== 1) {
    return new Response("Approval missing or already used", { status: 409 });
  }
  return {
    id,
    hash,
    stored: {
      expires: row.expires_at,
      decision: JSON.parse(row.decision_json),
    },
  };
}

async function sign(secret, message) {
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = await crypto.subtle.sign(
    "HMAC",
    key,
    encoder.encode(message),
  );
  return [...new Uint8Array(signature)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

function timingSafeEqual(left, right) {
  if (left.length !== right.length) return false;
  let mismatch = 0;
  for (let index = 0; index < left.length; index += 1) {
    mismatch |= left.charCodeAt(index) ^ right.charCodeAt(index);
  }
  return mismatch === 0;
}

function encodeBase64(value) {
  const bytes = encoder.encode(value);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

async function sendReminders(env) {
  if (!env.NTFY_TOPIC || !env.PUBLIC_BASE_URL) return;
  const { results } = await env.DB.prepare(
    `SELECT id, payload_hash, expires_at, decision_json, created_at
     FROM approvals
     WHERE status = 'pending'
       AND reminded = 0
       AND expires_at > unixepoch()
       AND unixepoch() >= MIN(created_at + 43200, expires_at - 3600)`,
  ).all();
  for (const row of results) {
    const record = {
      id: row.id,
      hash: row.payload_hash,
      expires: row.expires_at,
      decision: JSON.parse(row.decision_json),
    };
    const signature = await sign(
      env.SIGNING_SECRET,
      `${record.id}.${record.hash}.${record.expires}`,
    );
    const query = new URLSearchParams({
      id: record.id,
      hash: record.hash,
      expires: String(record.expires),
      signature,
    });
    const base = env.PUBLIC_BASE_URL.replace(/\/$/, "");
    const response = await fetch("https://ntfy.sh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        topic: env.NTFY_TOPIC,
        title: "Fantasy approval reminder",
        message: record.decision.summary,
        actions: [
          {
            action: "http",
            label: "Approve",
            url: `${base}/approve?${query}`,
            method: "POST",
            clear: true,
          },
          {
            action: "http",
            label: "Ignore",
            url: `${base}/ignore?${query}`,
            method: "POST",
            clear: true,
          },
        ],
      }),
    });
    if (response.ok) {
      await env.DB.prepare(
        `UPDATE approvals SET reminded = 1
         WHERE id = ? AND status = 'pending' AND reminded = 0`,
      )
        .bind(record.id)
        .run();
    }
  }
}
