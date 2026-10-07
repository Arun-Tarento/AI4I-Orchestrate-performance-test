#!/usr/bin/env bash
# Single-machine run. Usage: scripts/run_single.sh [users] [spawn_rate] [run_time]
# Defaults: 20 users, 1 user/s, 2m. Needs locust/.env filled in.
set -euo pipefail

USERS="${1:-20}"
RATE="${2:-1}"
RUN_TIME="${3:-2m}"

cd "$(dirname "$0")/../locust"
exec locust -f chat_load.py -u "$USERS" -r "$RATE" --headless --run-time "$RUN_TIME" \
  --csv "../runs/out_$(date +%Y%m%d_%H%M%S)"
