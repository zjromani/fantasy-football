#!/usr/bin/env bash
set -euo pipefail

repository="${1:-zjromani/fantasy-football}"
fantasy_week="${2:?usage: scripts/bootstrap.sh REPOSITORY FANTASY_WEEK}"

node_major="$(node --version | tr -d v | cut -d. -f1)"
if (( node_major < 22 )); then
  echo "Node.js 22 or newer is required for Wrangler." >&2
  exit 1
fi

required=(
  YAHOO_CLIENT_ID
  YAHOO_CLIENT_SECRET
  YAHOO_REFRESH_TOKEN
  FANTASYPROS_API_KEY
  LEAGUE_KEY
  TEAM_KEY
  WORKER_GITHUB_TOKEN
  APPROVAL_BASE_URL
)

for name in "${required[@]}"; do
  if [[ -z "${!name:-}" ]]; then
    echo "missing required environment variable: $name" >&2
    exit 1
  fi
done

signing_secret="${APPROVAL_SIGNING_SECRET:-$(openssl rand -hex 32)}"
ingest_token="${APPROVAL_INGEST_TOKEN:-$(openssl rand -hex 32)}"
jitter_secret="${SCHEDULE_JITTER_SECRET:-$(openssl rand -hex 32)}"
ntfy_topic="${NTFY_TOPIC:-fantasy-auto-gm-$(openssl rand -hex 12)}"

(cd worker && npm ci)
if grep -q "REPLACE_WITH_D1_DATABASE_ID" worker/wrangler.toml; then
  echo "create the D1 database and set its ID in worker/wrangler.toml" >&2
  exit 1
fi

run_gh() {
  env -u GITHUB_TOKEN gh "$@"
}

set_github_secret() {
  printf '%s' "$2" | run_gh secret set "$1" --repo "$repository"
}

set_worker_secret() {
  printf '%s' "$2" | (cd worker && npx wrangler secret put "$1")
}

set_github_secret YAHOO_CLIENT_ID "$YAHOO_CLIENT_ID"
set_github_secret YAHOO_CLIENT_SECRET "$YAHOO_CLIENT_SECRET"
set_github_secret YAHOO_REFRESH_TOKEN "$YAHOO_REFRESH_TOKEN"
set_github_secret FANTASYPROS_API_KEY "$FANTASYPROS_API_KEY"
set_github_secret NTFY_TOPIC "$ntfy_topic"
set_github_secret APPROVAL_BASE_URL "$APPROVAL_BASE_URL"
set_github_secret APPROVAL_SIGNING_SECRET "$signing_secret"
set_github_secret APPROVAL_INGEST_TOKEN "$ingest_token"
set_github_secret SCHEDULE_JITTER_SECRET "$jitter_secret"

run_gh variable set FANTASY_WEEK --body "$fantasy_week" --repo "$repository"
run_gh variable set LEAGUE_KEY --body "$LEAGUE_KEY" --repo "$repository"
run_gh variable set TEAM_KEY --body "$TEAM_KEY" --repo "$repository"
run_gh variable set WRITES_ENABLED --body "false" --repo "$repository"
run_gh variable set LINEUP_WRITES_ENABLED --body "false" --repo "$repository"
run_gh variable set FAB_WRITES_ENABLED --body "false" --repo "$repository"
run_gh variable set TRADE_WRITES_ENABLED --body "false" --repo "$repository"

set_worker_secret SIGNING_SECRET "$signing_secret"
set_worker_secret INGEST_TOKEN "$ingest_token"
set_worker_secret GITHUB_TOKEN "$WORKER_GITHUB_TOKEN"
set_worker_secret GITHUB_REPOSITORY "$repository"
set_worker_secret NTFY_TOPIC "$ntfy_topic"
set_worker_secret PUBLIC_BASE_URL "$APPROVAL_BASE_URL"

(cd worker && npx wrangler d1 migrations apply fantasy-auto-gm-approvals --remote)
(cd worker && npx wrangler deploy)

echo "Bootstrap complete. Subscribe to ntfy topic: $ntfy_topic"
echo "WRITES_ENABLED remains false."
