#!/usr/bin/env bash
# Distributed run (master + workers on separate bastion hosts).
#
#   Master:  scripts/run_distributed.sh master [users] [spawn_rate] [run_time] [expect_workers]
#   Worker:  MASTER_HOST=<master address> WORKER_INDEX=<0,1,...> scripts/run_distributed.sh worker
#
# WORKER_INDEX must differ per worker so their key round-robin starts on different keys.
# Needs locust/.env filled in on every machine.
set -euo pipefail

ROLE="${1:?usage: run_distributed.sh master|worker ...}"
cd "$(dirname "$0")/../locust"

case "$ROLE" in
  master)
    USERS="${2:-20}"; RATE="${3:-2}"; RUN_TIME="${4:-5m}"; WORKERS="${5:-2}"
    exec locust -f chat_load.py --master --expect-workers="$WORKERS" --headless \
      -u "$USERS" -r "$RATE" --run-time "$RUN_TIME" \
      --csv "../runs/out_$(date +%Y%m%d_%H%M%S)"
    ;;
  worker)
    : "${MASTER_HOST:?set MASTER_HOST to the master address}"
    exec locust -f chat_load.py --worker --master-host="$MASTER_HOST" \
      --master-port="${MASTER_PORT:-5557}"
    ;;
  *)
    echo "role must be master or worker" >&2; exit 1 ;;
esac
