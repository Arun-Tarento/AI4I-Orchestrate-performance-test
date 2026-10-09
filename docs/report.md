# AI4I Inclusion: Load and Performance Report (/api/v1/chat)

Rough draft for review. Wording and layout are not final. How the tests were run is in [methodology.md](methodology.md), the setup in [environment.md](environment.md), and the run data in [`runs/`](../runs/).

## 1. Objective and scope

**Objective.** Find how to optimise each component on the `/api/v1/chat` path so that the AI4I orchestration layer adds no more than 10 ms of latency to a request, at more than 1,000 RPS.

**SLA.**
- The SLA (10 ms) measures the overhead AI4I adds to an inference request: auth, plugins, gateway hops and capturing information for visibility.
- The pass/fail metrics are the median and the average. P95 and P99 are reported as tail behaviour only.

**Scope.**
- `/api/v1/chat` only, with a stubbed model. Other services and earlier real-model tests are out of scope.
- Only tests that show a progression, or a change that moved the number, are reported.
- Note: it is assumed that the model stub adds no latency, so the measured latency is treated as AI4I overhead. This is conservative, because the measurement also includes Locust client time and the network hop to Nginx. The stub responds in about [N] ms.

The results are summarised in section 2 and detailed in section 4.

## 2. Summary

**Outcome.** Under a sustained load of 1,240 RPS, 24% above the 1,000 RPS requirement, AI4I held an 11 ms median and a 15 ms average across 8.9M requests in 2 hours. Failures were 0.00% (4 of 8.93M).

- **Against the 10 ms SLA:** the median (11 ms) is within 1 ms of it. The average (15 ms) is 5 ms above it.
- **Throughput:** from about 290 RPS in the first runs (burstable infrastructure, one replica per service) to 1,240 RPS on the final setup (non-burstable infrastructure, scaled replicas, distributed load). The gain comes from both the scaling and the better infrastructure.
- **Largest gains:**
  - Non-burstable infrastructure and a larger load generator: +99%.
  - Auth scale-out (done together with Inference and Platform Core): +75% on the full gateway stack.
  - Inference, 1 to 2 pods: +50%.
  - Platform Core, 1 to 2 pods: +17%.
- **Smaller gains:**
  - Keep-alive tuning: +4.5%.
  - Second APISIX replica: +2%.
- **Async work:** tracing and usage events through Kafka are not part of the synchronous latency and did not affect request throughput. The Kafka lag problem was fixed with more consumer pods, more memory and an even partition spread (lag 21 to 35 s).

## 3. Tool stack and methodology

### Tool stack

- **Load testing:** Locust, an open-source load-testing tool distributed as a Python package (`pip install locust`). Scenarios are plain Python code (`llm_benchmarking.py`), and Locust supports distributed runs with a master and workers.
- **System under test:** the `/api/v1/chat` path: Nginx, APISIX (plugins), Auth, Inference, Platform Core, Kafka consumer (PPU), Fluent Bit and Redis.
- **Load generator and cluster, by phase:**
  - Up to 28 Jul: burstable bastion, burstable (t3a) nodes.
  - 29 Jul: burstable bastion, 2 × m6a.2xlarge CPU nodes and 2 × m6a.large system nodes.
  - From 30 Jul: m6a.xlarge bastion, same cluster.
- Where needed, multiple load-generating machines were used (Locust in distributed mode, with a master and workers).

### Methodology

- Each Locust user acts as one real client.
- Runs lasted 3 minutes in most tests, up to 30 minutes in the Kafka tests, and 2 hours for the final sustained run.
- Metrics per run: RPS and average, P50, P95 and P99 latency, with the replica, CPU and memory settings of each component.
- Each component was tested by changing its settings and comparing against the run before it. Where several settings changed together, the gain is reported as a combined effect.

## 4. Steps Taken to Improve Performance

Each section follows the same structure: overview, change tested, environment, a table of the numbers, outcome and notes. In every table, Δ is the change in RPS against the first row of that table. Each section is framed around what reduced latency under load.

### 4.1 APISIX gateway: plugin cost (21 Jul)

**Overview.** The APISIX gateway runs a plugin chain on every request. This section measures what the plugins cost in latency and throughput.

**Change tested.** Plugins were added step by step: none, auth plugin only, full stack.

**Test setup.** 25 users, 3 min. 1 replica of each service, burstable (t3a) infrastructure and bastion.

| Step | Run | RPS | Avg ms | P95 ms | Δ |
|---|---|---|---|---|---|
| No plugins | 21 Jul | 645 | 32 | 28 | baseline |
| Auth plugin only | 21 Jul | 333 | 72 | 86 | −48% |
| Full plugin stack | 21 Jul | 292 | 82 | 120 | −12% (vs previous row) |

**Outcome.** The auth plugin is the main gateway cost. It more than doubled average latency (32 to 72 ms) and halved throughput. The other plugins together cost a further 12% of throughput. How Auth was scaled to recover this is in 4.2.

**Notes.**
- The "no plugins" run (645 RPS, 32 ms average) is not a floor. It is the gateway path without plugins, measured under load, where latency is mostly queueing. It is not baseline latency.
- The P95 (28 ms) is below the average (32 ms) because about 1 to 2% of requests took around 1 second or more (P99 1,000 ms, max 2,144 ms), which pulls the average up. The cause is not established.
- A control run with a t3a.xlarge bastion gave 672 RPS (+4%), so the first load generator was not the main limit at that scale.

### 4.2 Auth service: isolation and scale-out (21 Jul, 28 Jul)

**Overview.** Every request calls the Auth service to validate the caller before it goes any further. This section follows Auth in time order. On 21 Jul the path was split into hops and Auth was found to be the largest contributor to latency. On 28 Jul Auth was scaled out, and that is where the 75% improvement in throughput comes from.

**Change tested.**
- 21 Jul: the Auth pod was called directly and compared with the full gateway stack, both with 1 Auth pod (CPU limit 1000m, 1.0 core).
- 28 Jul: Auth was scaled out from 1 to 3 pods, and the CPU limit of each pod went from 1000m to 600m (1.8 cores allowed in total).

**Test setup.** 25 users on 21 Jul, 20 users on 28 Jul, 3 min. Burstable infrastructure.

| Step | Run | RPS | Avg ms | P95 ms | Δ |
|---|---|---|---|---|---|
| Auth pod called directly, 1 replica | 21 Jul | 323 | 71 | 150 | reference |
| Full gateway stack, 1 Auth pod (1.0 core) | 21 Jul | 292 | 82 | 120 | baseline |
| Full gateway stack, 3 Auth pods (1.8 cores) | 28 Jul | 511 | 36 | 60 | +75% |

**Outcome.**
- 21 Jul: Auth alone gave 323 RPS at 71 ms average, close to the full stack at 292 RPS and 82 ms. Almost all of the latency of a `/chat` request was the Auth call, and one Auth pod capped the whole path.
- 28 Jul: scaling Auth to 3 pods lifted the full stack from 292 to 511 RPS (+75%) and cut average latency from 82 to 36 ms.

**Notes.**
- A pod is one running copy of the service, and each copy can validate only a limited number of requests at a time. With one pod, requests queue and latency rises. With three, the same load is shared across three copies and the queueing mostly disappears.
- Each pod became smaller (1000m to 600m), but Auth as a whole has more CPU (1.0 to 1.8 cores) and three copies. A lower per-pod limit alone would make each pod slower, so the gain cannot come from the smaller size.
- On 28 Jul Inference (1 to 3 pods) and Platform Core (to 2) were scaled in the same run, along with 20 users instead of 25 and a bigger bastion. The +75% is therefore a combined gain, and Platform Core's earlier count is unknown. The effect of each pod on its own is in 4.3 and 4.4.

### 4.3 Inference service (28 Jul)

**Overview.** Measures how scaling Inference pods reduced latency under load.

**Change tested.** Inference replicas 1, 2 and 3, with Auth at 3 and Platform Core at 1.

**Test setup.** 20 users, 3 min. Burstable infrastructure.

| Step | Run | RPS | Avg ms | P95 ms | Δ |
|---|---|---|---|---|---|
| 1 Inference replica | 28 Jul | 239 | 80 | 160 | baseline |
| 2 Inference replicas | 28 Jul | 359 | 51 | 91 | +50% |
| 3 Inference replicas | 28 Jul | 362 | 52 | 100 | +1% |

**Outcome.** The second pod cut average latency from 80 to 51 ms and gave most of the gain. A third adds almost nothing at this point because the next bottleneck is elsewhere.

### 4.4 Platform Core (28 Jul)

**Overview.** Measures how scaling Platform Core reduced latency under load.

**Change tested.** Platform Core from 1 to 2 replicas, with Auth at 3 and Inference at 3.

**Test setup.** 20 users, 3 min. Burstable infrastructure.

| Step | Run | RPS | Avg ms | P95 ms | Δ |
|---|---|---|---|---|---|
| 1 Platform Core replica | 28 Jul | 362 | 52 | 100 | baseline |
| 2 Platform Core replicas | 28 Jul | 422 | 44 | 76 | +17% |

**Outcome.** Platform Core was the next limit after Inference. A second replica cut average latency from 52 to 44 ms and gave +17% throughput.

### 4.5 Nginx and connection tuning (28 Jul, part 2)

**Overview.** Checks what Nginx connection handling and the APISIX hop cost in latency under load.

**Change tested.** Requests through APISIX without keep-alive, then with keep-alive 100. A run that skipped APISIX measured how much the gateway hop itself costs.

**Test setup.** 20 users, 3 min. Burstable infrastructure.

| Step | Run | RPS | Avg ms | P95 ms | Δ |
|---|---|---|---|---|---|
| Through APISIX, no keep-alive | 28 Jul | 619 | 26 | 53 | baseline |
| Skipping APISIX (reference) | 28 Jul | 692 | 21 | 33 | +12% |
| Keep-alive 100 | 28 Jul | 647 | 25 | 46 | +4.5% |

**Outcome.** Keep-alive adds 4.5% throughput and trims P95 from 53 to 46 ms. The whole APISIX hop costs about 12% of throughput.

### 4.6 Non-burstable infrastructure and bastion upgrade (30 Jul)

**Overview.** Tests up to 28 Jul ran on burstable (t3a) instances and were preliminary. From 29 Jul the cluster moved to non-burstable nodes. On 30 Jul the load generator also moved from a burstable instance to a non-burstable one, to generate more load.

**Change tested.**
- Cluster: 2 × m6a.2xlarge CPU nodes, 2 × m6a.large system nodes.
- Bastion: burstable T-series to m6a.xlarge.
- Replicas (both runs): Auth 5, Inference 5, Platform Core 3, APISIX 2.

**Test setup.** 20 and 30 users, 3 min. Single bastion, `/api/v1/chat`, stubbed model, `-r 5 -t 3m`.

Most significant peak point (single bastion):

| Step | Run | RPS | Avg ms | P95 ms | Δ |
|---|---|---|---|---|---|
| Burstable bastion, 20 users | 1 | 583 | 27 | 35 | baseline |
| m6a.xlarge bastion, 30 users | 2 | 1,162 | 21 | 28 | +99% |

**Outcome.**
- Throughput doubled, from 583 to 1,162 RPS. Average latency fell from 27 to 21 ms and P95 from 35 to 28 ms.
- Non-burstable infrastructure gives stable numbers that can be compared from here on.
- Zero failures.

**Notes.** Users changed from 20 to 30 together with the bastion, so the +99% is a combined effect.

### 4.7 Distributed load generation: 2-hour run (5 Aug)

**Overview.** From 5 Aug the load was generated with distributed Locust (one master and two workers). The result shown is the full 2-hour run.

**Change tested.**
- Load generator: single bastion to distributed Locust (master + 2 workers).
- Duration: 3 minutes to 2 hours.
- Replica setup of the 5 Aug run: Auth 5, Inference 5 (1 Uvicorn worker), Platform Core 3, APISIX 2, Nginx 1, with the Kafka consumer enabled on 4 partitions. This matches the final setup.

**Test setup.** 20 users, 2 hours. Same infrastructure as 4.6. `-u 20 -r 2 --run-time 2h`.

| Step | Run | RPS | Avg ms | P95 ms | Δ |
|---|---|---|---|---|---|
| Single bastion, 30 users, 3 min (4.6) | – | 1,162 | 21 | 28 | baseline |
| Distributed, 20 users, 2 hours | Run 1 | 1,240 | 15 | 40 | +7% |

8,931,136 requests in total. P50 was 11 ms and P99 was 86 ms.

**Outcome.**
- The cluster held 1,240 RPS for two hours, and no CPU warning appeared during the run.
- Average latency is 15 ms, down from 21 ms with the single bastion. The median is 11 ms, about at the 10 ms target.

**Notes.**
- P95 is higher in the 2-hour run (40 ms vs 28 ms). Users (20 vs 30) and duration also differ, so the rows are not like-for-like.
- The worse tail is likely an effect of the long soak (for example garbage collection pauses, noisy neighbours, Kafka or Fluent Bit activity). This is a hypothesis and has not been tested.

### 4.8 Kafka consumer lag and partition analysis (18 Aug to 2 Sep)

This is a throughput and freshness topic, not a latency one. The Kafka path is asynchronous and outside the synchronous latency budget.

**Problem.**
- The Kafka consumers (PPU) were throttling.
- Real-time spend could not be seen in the Portal, because processing fell behind the request rate.

**Changes analysed.**
- Memory and pods of a few entities were increased: Kafka consumer (PPU) pods 4 to 8, Kafka broker memory 2–4Gi to 2–8Gi, and Fluent Bit consumer memory 128–256Mi to 256Mi–1Gi.
- The Kafka consumer partitions were set to 8.
- The distribution of messages across partitions was analysed, because it was uneven.

**Result.**

| Step | Setup | Kafka lag after test |
|---|---|---|
| 18 Aug, Run 3 | 8 pods, 8 partitions | 3 min |
| 18 Aug, Run 4 | 4 pods, 8 partitions | 1 min 35 s |
| 19 Aug, 30 min run | 8 pods, 8 partitions, 20 users | 21–35 s |

- On 19 Aug, 30-minute runs at about 1,055 RPS and 13 ms average cleared the Kafka backlog in 21 to 35 seconds.
- On 2 Sep, all 8 partitions processed almost the same number of messages. In the 30-minute run the busiest partition had 617,571 and the quietest 614,974, a difference of about 0.4%.
- Request throughput was not affected by any of these changes.
- Which of these changes fixed the uneven partition distribution is not established in the test data.
