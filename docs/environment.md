# Environment

The system under test, the load generator, and how to run the tests. Hostnames, IPs and node names are deliberately left out.

## System under test

The `/api/v1/chat` request path:

```
Locust  ->  Nginx  ->  APISIX (plugins)  ->  Auth pod  ->  Inference pod (stubbed model)
```

Running alongside: Platform Core, Kafka consumer (PPU), Fluent Bit and Redis.

The Inference pod returns a stubbed response with no model call, so the test isolates the cost of the infrastructure from the endpoint to the pod.

## Final setup

| Component | Replicas | Notes |
|---|---|---|
| Auth | 5 | |
| Inference | 5 | 1 Uvicorn worker each |
| Platform Core | 3 | |
| APISIX | 2 | |
| Nginx | 1 | keep-alive 100 tested in 4.6; keep it on |
| Kafka consumer (PPU) | 8 | 8 partitions (the 5 Aug run had the consumer enabled on 4 partitions) |

Whether the 5 Aug two-hour run used exactly this setup is listed in the [open items](report.md#open-items).

## Infrastructure

| Period | Cluster | Load generator |
|---|---|---|
| Up to 28 Jul | burstable (t3a) nodes | burstable instance |
| From 29 Jul | 2 x m6a.2xlarge CPU nodes, 2 x m6a.large system nodes | 30 Jul: single m6a.xlarge bastion host |
| From 5 Aug | same as above | distributed Locust: one master, two workers |

Use non-burstable nodes for any capacity or SLA test. Burstable results are not comparable with later ones.

## Test prerequisites

To repeat the tests you need all of the following in place. Items marked **to be provided** are not described in this repository yet.

| Need | Detail |
|---|---|
| A deployed AI4I stack | The `/api/v1/chat` path (Nginx, APISIX with its plugins, Auth, Inference, plus Platform Core and the Kafka consumers) shaped like the final setup above, on non-burstable nodes. |
| A stubbed model | The Inference side must return a valid non-streaming chat completion (JSON with `choices[0].message`) with no real model call, so any latency measured is overhead. How the stub is deployed: **to be provided**. Its own response time: not yet measured. |
| A registered service for the stub | Its ID goes in `SERVICE_ID`. The request must carry a service ID, not a model name, or `/api/v1/chat` answers 404. How the service is registered: **to be provided**. |
| Three API keys | Admin, Tenant Admin 1 and Tenant Admin 2, in `API_KEY_ADMIN`, `API_KEY_TENANT_ADMIN_1` and `API_KEY_TENANT_ADMIN_2`. All three must have access to the service above. Locust uses them round-robin, so each carries about a third of the traffic. How the keys are issued: **to be provided**. |
| Component sizing | Per-pod CPU and memory limits, the APISIX plugin configuration and the Nginx keep-alive setting. Replica counts are in the final setup above. The rest: **to be provided**. |
| A load generator | A non-burstable machine that can reach the entry point (m6a.xlarge was used). Above about 1,100 RPS use distributed Locust. Python 3 and the packages in `locust/requirements.txt`. |

`chat_load.py` stops at start-up if `CHAT_HOST`, `SERVICE_ID` or a key is missing. If every request fails with 404, check `SERVICE_ID`. If it fails with 401 or 403, check that the key has access to the service.

## Running the tests

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r locust/requirements.txt
cp locust/.env.example locust/.env     # then fill in the host, service ID and the 3 API keys
```

`.env` is gitignored. Never commit real keys.

| Variable | Meaning |
|---|---|
| `CHAT_HOST` | Base URL of the performance environment's entry point |
| `SERVICE_ID` | ID of the service registered for the stubbed model, sent as `model` in every request |
| `API_KEY_ADMIN`, `API_KEY_TENANT_ADMIN_1`, `API_KEY_TENANT_ADMIN_2` | Long-lived API keys, used round-robin |
| `WORKER_INDEX` | Shell variable, set per distributed worker (0, 1, ...) so each starts on a different key |

Single machine (defaults: 20 users, 1 user/s, 2 minutes):

```bash
scripts/run_single.sh [users] [spawn_rate] [run_time]
```

Distributed (master and workers on separate bastion hosts, `.env` filled in on each):

```bash
# master
scripts/run_distributed.sh master [users] [spawn_rate] [run_time] [expect_workers]
# each worker
MASTER_HOST=<master address> WORKER_INDEX=<0,1,...> scripts/run_distributed.sh worker
```

Settings common to every run (locustfile, `think-time = 0`) are in [`locust/locust.conf`](../locust/locust.conf). Users, spawn rate and run time are passed as flags. Locust CSV output goes to `runs/out_*` (gitignored).

### Reported run parameters

| Runs | Users (`-u`) | Spawn rate (`-r`) | Duration |
|---|---|---|---|
| 21 Jul, plugin and auth tests (4.1, 4.2) | 25 | 5 | 3 min |
| 28 Jul, Auth, Inference, Platform Core and Nginx tests (4.2, 4.4 to 4.6) | 20 | 5 | 3 min |
| 30 Jul, infrastructure and load-generator upgrade (4.7) | 20, then 30 | 5 | 3 min |
| 5 Aug, distributed (4.8) | 20 | 2 | 2 h |
| 18 Aug, single load generator (4.9) | 30 | 5 | 3 min |
| 19 Aug, distributed (4.9) | 20 | 2 | 30 min, `--think-time 0.005` |
| 2 Sep, distributed, partition spread (4.9) | 10 | 2 | 30 min |

The 20 Jul tracing runs (4.3) used 25 users for 3 minutes (spawn rate 5). Think time was 0 in every reported run except the 19 Aug runs (0.005 s; `--think-time` is in seconds). The reported runs are in [`runs/runs.csv`](../runs/runs.csv).

## Reading your results

- The report's figures are the **aggregated** row across the three keys. In Locust's `*_stats.csv` they map as follows:

  | Report | Locust column |
  |---|---|
  | RPS | `Requests/s` |
  | Avg ms | `Average Response Time` |
  | P50, P95, P99 ms | `50%`, `95%`, `99%` |
  | Failures | `Failure Count` |

- The per-key rows (`/api/v1/chat [Admin]` and so on) should be close to each other. A large gap between keys points to a problem with that key or tenant, not with the stack.
- Compare a run only with a run on the same kind of infrastructure, user count and duration. The reference results are in [report.md](report.md).
- Judge against the SLA as defined in [methodology.md](methodology.md#what-is-measured): median and average against 10 ms (target) and 15 ms (ceiling), with P95 and P99 as observed tail behaviour.
