# Methodology

How the `/api/v1/chat` load tests were run and how to read the numbers.

## What is measured

- **SLA = overhead the AI4I layer adds to an inference request**: auth, plugins, gateway hops, and capturing information for visibility. The SLA is 10 ms, at more than 1,000 RPS.
- **The model is a stub.** It is assumed to add no latency, so measured end-to-end latency is treated as AI4I overhead. This is a deliberate, conservative upper bound: Locust client time and the network hop to Nginx are counted too, so the true overhead is at most the measured value. The stub's own response time is still to be measured.
- **Pass/fail metrics: median and average latency.** P95 and P99 are reported as tail behaviour only.
- **Asynchronous visibility work is out of the budget.** Tracing and PPU usage events (Kafka) do not sit on the synchronous request path.

## Scope

- `/api/v1/chat` only, stubbed model only. No ASR, NMT, TTS, OCR or other services, and no earlier real-model tests.
- Only runs that show a progression, or a change that moved the number, are reported. Failed runs were test defects and are ignored.
- Plugin optimisation runs (30 Jul evening, 4 Aug) and the 4 Aug Kafka consumer runs are left out: they did not give a fair result.

## Load generator

- [Locust](https://locust.io), driven by [`locust/chat_load.py`](../locust/chat_load.py). Each Locust user acts as one real client and fires requests back to back (think time 0, except the 18 and 19 Aug Kafka runs, which used 0.005 to 0.1 s).
- **Request behaviour is fixed. Changing any of it invalidates the numbers:**
  - `stream=False`
  - one fixed, heavy "turn 20" payload ([`locust/payloads/chat_turn20.json`](../locust/payloads/chat_turn20.json)): the full conversation history plus tool definitions
  - round-robin over 3 API keys (Admin, Tenant Admin 1, Tenant Admin 2), sent as Bearer tokens
- A response counts as a success only if it is HTTP 200 and has `choices[0].message`.
- From 5 Aug, distributed Locust (one master, two workers) was used, because a single load-generator machine had become the limit. Each worker starts its key round-robin on a different key (`WORKER_INDEX`).
- Run it with [`scripts/run_single.sh`](../scripts/run_single.sh) or [`scripts/run_distributed.sh`](../scripts/run_distributed.sh). What must be in place first, and how to read the output, is in [environment.md](environment.md#test-prerequisites).

## Run design

- Runs were 3 minutes for most component tests, 5 to 30 minutes later, and 2 hours for the final sustained run.
- Metrics per run: RPS, average, P50, P95 and P99 latency, failures, and the replica, CPU and memory settings of each component.
- Each component was tested by changing its settings and comparing against the run before it. Where several settings changed together, the report says so and treats the gain as a combined effect.
- In every report table, Δ is the change in RPS against the first row of that table, unless the row says otherwise.

## Where the numbers came from

- Numbers come from the Google Sheet "Load and peformance analysis - release2.5". [`runs/runs.csv`](../runs/runs.csv) records the reported runs, and [`runs/kafka-partitions.csv`](../runs/kafka-partitions.csv) the Kafka partition spread.
- **Sections 4.1, 4.2 and 4.5 of the report did not come from `chat_load.py`.** They came from separate isolated-hop scripts that are not in this repository:
  - a plugin-latency script, which hit dedicated test endpoints on the gateway (no plugins, auth plugin only, full plugin stack) to measure the cost of each gateway stage. It supplied all of 4.1, the 28 Jul 3-Auth row of 4.2, and all of 4.5 (through APISIX, skipping APISIX, and keep-alive 100);
  - an auth-validate script, which called the Auth service directly, bypassing Nginx and APISIX, to measure the Auth pod on its own (the first row of 4.2).

  `runs/runs.csv` holds only the runs shown in the report. Its `source` column says which script produced each row (`chat_load`, `isolated_plugin_latency` or `isolated_auth_validate`). Do not read the isolated rows as `/api/v1/chat` runs.
- Where the sheet is silent on a cause, the report marks it as not established rather than inferring one.

## Caveats

- Locust is closed-loop, so tail latency may be understated (coordinated omission). P99 is indicative only.
- Up to 28 Jul the cluster and the load generator ran on burstable (t3a) instances, and those results were preliminary. Compare runs only within the same infrastructure.
- Runs are not always like-for-like (different users, duration or several simultaneous changes). Each section's notes say where.
- A "no plugins" run measured under load is mostly queueing time. It is not a baseline or minimum latency.
