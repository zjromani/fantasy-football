# Auto-GM Runbook

## Weekly operation

1. Update the `FANTASY_WEEK` repository variable.
2. Confirm FantasyPros cache freshness and provider request budget in the audit.
3. Review the weekly digest and unresolved approval notifications.
4. Leave `WRITES_ENABLED=false` whenever behavior or league settings are uncertain.

Scheduled runs use deterministic weekly jitter and suppress successful no-op
notifications. Failures send an urgent ntfy alert with the GitHub run URL.
FAB and trade writes first report `submitted`; later scheduled polls send the
terminal Yahoo success or failure receipt.

## Initial write rollout

1. Run CI and Worker tests.
2. Run `Fantasy Auto-GM` manually twice with `WRITES_ENABLED=false`.
3. Download both redacted audit artifacts and compare every decision.
4. Export current Yahoo roster positions to a local JSON object.
5. Before player locks, run:

   ```bash
   python -m app.cli probe-write --week "$FANTASY_WEEK" \
     --positions current-roster.json
   ```

6. If Yahoo accepts the identical-roster PUT, review the recorded capability.
7. Set `LINEUP_WRITES_ENABLED=true`, leave FAB/trade category gates false, then
   set the global `WRITES_ENABLED=true`.
8. Enable `FAB_WRITES_ENABLED` and `TRADE_WRITES_ENABLED` separately only after
   two reviewed category-specific cycles. They remain approval-gated.
9. After the first successful scheduled GitHub run, remove any loaded
   `com.fantasy.ai-*` launchd jobs from the Mac.

If Yahoo returns 401, 403, or 405, keep the kill switch off and execute the
recorded payload manually in Yahoo. Do not use browser automation as a bypass.

## Yahoo app approval gate

`Fantasy Auto-GM` and `Execute Fantasy Approval` skip all jobs until repository
variable `YAHOO_APP_APPROVED=true`. Leave it unset while Yahoo reviews the
developer app so scheduled and dispatched Yahoo runs do not fire. CI continues
normally. After Yahoo approves the app, set the variable and resume the write
rollout below.

## Kill switch

Set repository variable `WRITES_ENABLED=false`. This takes effect on the next
workflow run and forces dry-run behavior while retaining reads, decisions,
notifications, and redacted audit artifacts.

For immediate containment, cancel the active workflow run after setting the
variable. Rotate a credential only if it may be compromised.

## Yahoo OAuth recovery

1. Set `WRITES_ENABLED=false`.
2. Check whether the refresh request failed or Yahoo rejected the API operation.
3. For an invalid refresh token, repeat `oauth-url` and `oauth-exchange`.
4. Update only the `YAHOO_REFRESH_TOKEN` GitHub secret.
5. Verify a league/team read.
6. Repeat the identical-roster probe before restoring writes.

Token files are written with mode `0600`. Access and refresh tokens must never
appear in GitHub artifacts or logs.

## FantasyPros outage or budget exhaustion

Cached data remains available with its original timestamp. The policy blocks
FAB and trade writes when data is stale. Do not increase freshness thresholds
to force a transaction through.

Lineup recommendations may continue. A stale-data lineup write is permitted only
when its immutable decision payload is marked `safe_correction`, such as moving
an ineligible player out of an active slot.

## Approval incidents

- Approval links expire after 24 hours or at the Yahoo deadline.
- A second use returns HTTP 409.
- A signature or payload-hash mismatch returns HTTP 403/409.
- The Worker atomically transitions the D1 record from pending before dispatch,
  preventing concurrent replay.
- If GitHub dispatch fails after consumption, create a new recommendation; never
  reconstruct or reuse the old URL.

The Worker holds only pending decision payloads. Yahoo credentials remain in
GitHub Actions secrets.

## Manual Yahoo fallback

Use the decision summary and intended payload from the local SQLite audit.
Confirm league, team, week, player keys, bid, and add/drop pairing before
submitting in Yahoo. Record the final Yahoo transaction status in the weekly
review notes. Never weaken policy checks because API writes are unavailable.

## Data and artifacts

GitHub uploads only `export-audit` JSON, which omits raw decision payloads,
tokens, authorization headers, and provider responses. Retention is 14 days.
Raw state is written to the runner's temporary directory and is not uploaded.
