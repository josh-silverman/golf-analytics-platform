#!/usr/bin/env bash
# Warm the live demo before showing it to someone.
#
# Render's free instance spins down after ~15 min idle (~40s cold start on
# the next request), and even once the container is up, a board is only
# cached once someone has actually requested it (6h TTL) — the first request
# for an uncached event also pays a DataGolf fetch, which the README notes
# can take "a minute or two" under rate limiting. This script pays both costs
# once, before the audience is watching, instead of live during a demo:
#
#   1. Hits /healthz to wake the container (skip if keep-warm.yml already
#      kept it up — this is a no-op then).
#   2. Reads /status to report which model is serving and whether DataGolf
#      answers right now.
#   3. Resolves the current tournament and requests its board, which is what
#      actually builds/refreshes that event's cache.
#
# Usage: scripts/warm_demo.sh [base_url]
#   base_url defaults to the production API (matches frontend/vercel.json's
#   rewrite target). Pass http://localhost:8000 to warm a local dev stack.

set -euo pipefail

BASE_URL="${1:-https://pga-analytics-api.onrender.com}"
API="${BASE_URL}/api/v1"

echo "== Warming ${BASE_URL} =="
echo

echo "-- /healthz --"
t0=$(date +%s)
curl -fsS --max-time 90 "${API}/healthz"
echo
t1=$(date +%s)
echo "(${t1} - ${t0} = $((t1 - t0))s)"
echo

echo "-- /status --"
curl -fsS --max-time 30 "${API}/status" | python3 -m json.tool
echo

echo "-- Resolving current tournament --"
current_json=$(curl -fsS --max-time 30 "${API}/tournaments/current")
tournament_id=$(echo "${current_json}" | python3 -c "import sys, json; d = json.load(sys.stdin).get('data'); print(d['id'] if d else '')")

if [ -z "${tournament_id}" ]; then
  echo "No current tournament — nothing to warm. (Off-season, or between events.)"
  exit 0
fi
echo "Current tournament id: ${tournament_id}"
echo

echo "-- Building board for tournament ${tournament_id} (this is the slow one) --"
t0=$(date +%s)
outcome_count=$(curl -fsS --max-time 150 "${API}/predictions/${tournament_id}" \
  | python3 -c "import sys, json; print(len(json.load(sys.stdin).get('outcomes', [])))")
t1=$(date +%s)
echo "Board built: ${outcome_count} players, $((t1 - t0))s"
echo

echo "-- /status again (confirms last_board_build_at moved) --"
curl -fsS --max-time 30 "${API}/status" | python3 -m json.tool

echo
echo "Warm. Safe to demo."
