import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import test from "node:test";

import worker from "../src/index.js";

class MemoryD1 {
  records = new Map();

  prepare(sql) {
    const database = this;
    return {
      args: [],
      bind(...args) {
        this.args = args;
        return this;
      },
      async run() {
        if (sql.includes("INSERT INTO approvals")) {
          const [id, payloadHash, expiresAt, decisionJson, createdAt] = this.args;
          if (!database.records.has(id)) {
            database.records.set(id, {
              payload_hash: payloadHash,
              expires_at: expiresAt,
              decision_json: decisionJson,
              status: "pending",
              reminded: 0,
              created_at: createdAt,
            });
          }
          return { meta: { changes: 1 } };
        }
        if (sql.includes("consumed_at")) {
          const [status, id] = this.args;
          const record = database.records.get(id);
          if (!record || record.status !== "pending") {
            return { meta: { changes: 0 } };
          }
          record.status = status;
          return { meta: { changes: 1 } };
        }
        return { meta: { changes: 1 } };
      },
      async first() {
        const record = database.records.get(this.args[0]);
        return record?.status === "pending" ? record : null;
      },
      async all() {
        return { results: [] };
      },
    };
  }
}

test("approval is signed, dispatched once, then rejected", async () => {
  const env = {
    DB: new MemoryD1(),
    INGEST_TOKEN: "ingest",
    SIGNING_SECRET: "signing",
    GITHUB_REPOSITORY: "owner/repo",
    GITHUB_TOKEN: "github",
  };
  const expires = Math.floor(Date.now() / 1000) + 300;
  const record = {
    id: "approval",
    hash: "payload-hash",
    expires,
    decision: { id: 1, kind: "fab", payload: { bid: 7 } },
  };
  const prepared = await worker.fetch(
    new Request("https://worker.example/prepare", {
      method: "POST",
      headers: {
        Authorization: "Bearer ingest",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(record),
    }),
    env,
  );
  assert.equal(prepared.status, 200);

  const signature = createHmac("sha256", "signing")
    .update(`approval.payload-hash.${expires}`)
    .digest("hex");
  const approvalUrl =
    `https://worker.example/approve?id=approval&hash=payload-hash` +
    `&expires=${expires}&signature=${signature}`;
  const originalFetch = globalThis.fetch;
  let dispatch;
  globalThis.fetch = async (url, options) => {
    dispatch = { url, options };
    return new Response(null, { status: 204 });
  };
  try {
    const preview = await worker.fetch(new Request(approvalUrl), env);
    assert.equal(preview.status, 200);
    assert.match(await preview.text(), /method="post"/);
    assert.equal(dispatch, undefined);
    const approved = await worker.fetch(
      new Request(approvalUrl, { method: "POST" }),
      env,
    );
    const replay = await worker.fetch(
      new Request(approvalUrl, { method: "POST" }),
      env,
    );
    assert.equal(approved.status, 200);
    assert.equal(replay.status, 409);
    assert.match(dispatch.url, /execute-approval\.yml\/dispatches$/);
    const body = JSON.parse(dispatch.options.body);
    assert.equal(body.inputs.hash, "payload-hash");
  } finally {
    globalThis.fetch = originalFetch;
  }
});
