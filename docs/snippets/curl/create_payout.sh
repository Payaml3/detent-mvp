#!/usr/bin/env bash
# Create the quickstart payout. Run from a folder that holds payout.json: bash create_payout.sh
set -euo pipefail
# docs:start
curl -sS --fail-with-body "$DEKERNAI_BASE_URL/v1/payment_intents" \
  -H "Authorization: Bearer $DEKERNAI_API_KEY" \
  -H "Idempotency-Key: $(openssl rand -hex 16)" \
  -H "Content-Type: application/json" \
  -d @payout.json
# docs:end
