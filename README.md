# Fantasy Football Auto-GM

Headless, deterministic Yahoo fantasy-football manager for league `196780`.
GitHub Actions observes league state, scores options with FantasyPros data, records
every decision in SQLite, automatically applies safe lineup/IR changes, and sends
FAB/trade proposals to ntfy for one-tap approval.

Yahoo write access is capability-probed. A rejected write leaves the system in
advisory mode and preserves the exact action for manual entry.

## Local setup

Requires Python 3.13. Worker deployment additionally requires Node.js 22,
Cloudflare Wrangler, `gh`, and authenticated GitHub/Cloudflare CLIs.

```bash
make venv
cp .env.example .env
```

Set `LEAGUE_KEY` and `TEAM_KEY` in the environment or put their values in
`config/league.yml`. Keep all write controls off during bootstrap:

```dotenv
WRITES_ENABLED=false
DRY_RUN=true
```

Generate a Yahoo authorization URL with a random state:

```bash
.venv/bin/python -m app.cli oauth-url --state-file ~/.fantasy-bot/oauth-state
.venv/bin/python -m app.cli oauth-exchange \
  --code '<returned-code>' \
  --state '<returned-state>' \
  --state-file ~/.fantasy-bot/oauth-state
```

Copy the resulting refresh token from the protected token file into the
`YAHOO_REFRESH_TOKEN` secret. Never commit `.env`, token files, raw Yahoo
snapshots, or SQLite databases.

## Commands

```bash
python -m app.cli migrate
python -m app.cli sync --week 1
python -m app.cli recommend --state normalized-state.json
python -m app.cli run-live --week 1
python -m app.cli execute --decision-id 1
python -m app.cli probe-write --week 1 --positions current-roster.json
python -m app.cli digest
python -m app.cli export-audit
```

`run-live` is the scheduled entry point. It retrieves Yahoo state and
FantasyPros weekly/ROS data, normalizes player identities, creates lineup, FAB,
incoming-trade, and outbound-trade decisions, then applies policy.

## Safety model

- Lineup and legal IR moves are the only categories eligible for automatic writes.
- FAB claims and every trade require a signed, expiring ntfy approval.
- Approval URLs are payload-bound, expire within 24 hours or at the Yahoo deadline,
  and are atomically consumed once by Cloudflare D1.
- Stale data blocks transactions. Only explicitly marked safe lineup corrections
  may proceed from stale data.
- Top-30 ROS players and `protected_player_keys` cannot be dropped.
- FAB is limited to two claims weekly, 15% normally, and 40% for a starter vacancy.
- `WRITES_ENABLED=false` is the repository-wide kill switch. Observation,
  recommendations, and redacted audits continue.
- Raw provider responses are temporary and never uploaded as artifacts.

## GitHub and Cloudflare bootstrap

Create these GitHub Actions secrets:

- `YAHOO_CLIENT_ID`
- `YAHOO_CLIENT_SECRET`
- `YAHOO_REFRESH_TOKEN`
- `FANTASYPROS_API_KEY`
- `NTFY_TOPIC`
- `APPROVAL_BASE_URL`
- `APPROVAL_SIGNING_SECRET`
- `APPROVAL_INGEST_TOKEN`
- `SCHEDULE_JITTER_SECRET`

Create these repository variables:

- `FANTASY_WEEK`
- `LEAGUE_KEY`
- `TEAM_KEY`
- `WRITES_ENABLED` (start with `false`)
- `LINEUP_WRITES_ENABLED` (enable first after two reviewed cycles)
- `FAB_WRITES_ENABLED` (enable only after separate review)
- `TRADE_WRITES_ENABLED` (enable only when playoff/risk data is healthy)

For the Worker:

1. Run `npx wrangler d1 create fantasy-auto-gm-approvals`, then put the returned
   database ID in `worker/wrangler.toml`.
2. Run `npx wrangler d1 migrations apply fantasy-auto-gm-approvals --remote`.
3. Set Worker secrets `SIGNING_SECRET`, `INGEST_TOKEN`, `GITHUB_TOKEN`,
   `GITHUB_REPOSITORY`, `NTFY_TOPIC`, and `PUBLIC_BASE_URL`.
4. Give `GITHUB_TOKEN` only Actions workflow-dispatch access to this repository.
5. Deploy from `worker/` with `npm ci && npm run deploy`.
6. Put the deployed URL in `APPROVAL_BASE_URL`.

The signing and ingest values must match their GitHub counterparts.

After creating the D1 database and exporting the account-specific values,
the bootstrap script generates the remaining secrets, configures GitHub and the
Worker, deploys the Worker, and leaves writes disabled:

```bash
export YAHOO_CLIENT_ID=...
export YAHOO_CLIENT_SECRET=...
export YAHOO_REFRESH_TOKEN=...
export FANTASYPROS_API_KEY=...
export LEAGUE_KEY=...
export TEAM_KEY=...
export WORKER_GITHUB_TOKEN=...
export APPROVAL_BASE_URL=...
scripts/bootstrap.sh zjromani/fantasy-football 1
```

## Rollout

Run `make verify` and two complete dry-run cycles. Review every generated
lineup, FAB, and trade proposal. Probe an identical roster before player locks,
then record the result. Enable each category separately after its review, then
enable the global `WRITES_ENABLED=true` kill switch.

See `RUNBOOK.md` for incidents, provider outages, approvals, and manual fallback.
