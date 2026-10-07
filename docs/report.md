# Load and Performance Report: `/api/v1/chat`

Draft for review. Wording and layout are not final. How the tests were run is in [methodology.md](methodology.md), the setup in [environment.md](environment.md), and the run data in [`runs/`](../runs/).

## 1. Objective and scope

- **Objective:** find how to optimise each component on the `/api/v1/chat` path so that the latency the AI4I orchestration layer adds stays within **10 ms (target) and 15 ms (ceiling)**.
- **SLA definition:** the SLA is overhead, the latency the layer adds to an inference request (auth, plugins, gateway hops, capturing information for visibility).
- **Assumption:** the model stub adds no latency, so the measured end-to-end latency is treated as AI4I overhead. This is deliberately conservative. Locust client time and the network hop to Nginx are also counted, so the true overhead is at most the measured value. The stub's own response time is not yet measured.
- **Pass/fail metric:** median and average latency. P95 and P99 are reported as observed tail behaviour, not as the SLA. To be confirmed.
- **Scope:** `/api/v1/chat` only, stubbed model only. Only tests that show a progression, or a change that moved the number, are reported.

## 2. Summary

- **Headline:** at 1,240 RPS sustained for 2 hours (8.9M requests), AI4I adds at most **11 ms at the median and 15 ms on average**. Tail: P95 40 ms, P99 86 ms. Failures were 0.00% (4 of 8.93M).
- The median of 11 ms is about at the 10 ms target. The average of 15 ms is at the ceiling, with no margin.
- The tail (P95 40 ms) is above the 10 to 15 ms band. This is the open item.
- Throughput rose from about 290 RPS (full gateway stack, one replica of each service) to about 1,240 RPS.
- Biggest gains: Auth scale-out (+75% on the full gateway stack, 4.2), Inference 1 to 2 pods (+50%), Platform Core 1 to 2 pods (+17%), and the move to non-burstable infrastructure (+99%, combined with a load-generator change and more users).
- Smaller gains: keep-alive tuning (+4.5%) and a second APISIX replica (+2%).
- From 30 Jul the load generator, not the cluster, was the limit, so distributed Locust was used from 5 Aug.
- Async work for visibility (tracing, usage events through Kafka) is outside the synchronous latency budget and did not affect request throughput. Its Kafka lag problem was fixed with more consumer pods, more memory and an even partition spread (lag 21 to 35 s).

## 3. Method and environment

See [methodology.md](methodology.md) for the tool stack, request behaviour and caveats, and [environment.md](environment.md) for the cluster and load-generator setup. Locust is closed-loop, so tail latency may be understated and P99 is indicative only.

## 4. Component analysis

Each section follows the same structure: overview, change tested, environment, a table of the numbers, outcome and notes. In every table, Δ is the change in RPS against the first row of that table. The run source is recorded in [`runs/runs.csv`](../runs/runs.csv). **4.1, 4.2 and 4.6 came from isolated-hop scripts, not from `chat_load.py`** (see [methodology](methodology.md#where-the-numbers-came-from)).

### 4.1 APISIX gateway: plugin cost (21 Jul)

**Overview.** The APISIX gateway runs a plugin chain on every request. This section measures what the plugins cost in latency and throughput.

**Change tested.** Plugins were added step by step: none, auth plugin only, full stack.

**Environment.** 25 users, 1 replica of each service, 3-minute runs, burstable (t3a) infrastructure and load generator.

| Step | Run | RPS | Avg ms | P95 ms | Δ |
|---|---|---|---|---|---|
| No plugins | 21 Jul | 645 | 32 | 28 | baseline |
| Auth plugin only | 21 Jul | 333 | 72 | 86 | −48% |
| Full plugin stack | 21 Jul | 292 | 82 | 120 | −12% (vs previous row) |

**Outcome.** The auth plugin is the main gateway cost. It more than doubled average latency (32 to 72 ms) and halved throughput. The other plugins together cost a further 12% of throughput. How Auth was scaled to recover this is in 4.2.

**Notes.**
- The "no plugins" run (645 RPS, 32 ms average) is not a floor. It is the gateway path without plugins, measured under load, where latency is mostly queueing. It is not baseline latency.
- The P95 (28 ms) is below the average (32 ms) because about 1 to 2% of requests took around 1 second or more (P99 1,000 ms, max 2,144 ms), which pulls the average up without moving P95. The cause of those slow requests is not established.
- A control run with a larger load-generator instance (t3a.xlarge) gave 672 RPS (+4%), so the first load generator was not the main limit at that scale.

### 4.2 Auth service: isolation and scale-out (21 Jul, 28 Jul)

**Overview.** Splitting the path into hops showed the Auth service, not APISIX, as the first bottleneck. This section covers the Auth pod on its own and how scaling it reduced latency under load.

**Change tested.** The Auth pod was measured directly, then Auth was scaled from 1 to 3 pods on 28 Jul.

**Environment.** 25 users on 21 Jul and 20 users on 28 Jul, 3-minute runs, burstable infrastructure.

| Step | Run | RPS | Avg ms | P95 ms | Δ |
|---|---|---|---|---|---|
| Auth pod called directly, 1 replica | 21 Jul | 323 | 71 | 150 | reference |
| Full gateway stack, 1 Auth replica | 21 Jul | 292 | 82 | 120 | baseline |
| Full gateway stack, 3 Auth replicas | 28 Jul | 511 | 36 | 60 | +75% |

**Outcome.** One Auth pod on its own handled 323 RPS, which is the limit seen at the gateway. Scaling Auth to 3 pods lifted the full stack from 292 to 511 RPS and cut average latency from 82 to 36 ms.

**Notes.** On 28 Jul Auth (1 to 3), Inference (1 to 3) and Platform Core (to 2) were changed together, along with Auth CPU 1000m to 600m, 20 users instead of 25 and a bigger load generator. The +75% is therefore a combined gain, and Platform Core's earlier count is unknown. The effect of each pod on its own is in 4.4 and 4.5.

### 4.3 Observability and tracing (20 Jul)

**Overview.** Checks whether metrics, logging and tracing add latency or cost throughput.

**Change tested.** Observability on, then tracing on, against a reference with both off.

**Environment.** 25 users, 1 replica of each service, burstable infrastructure.

| Step | Run | RPS | Avg ms | P95 ms | Δ |
|---|---|---|---|---|---|
| Reference, no observability or tracing | 20 Jul | 212 | 107 | 210 | baseline |
| Observability | 20 Jul | 221 | 101 | 190 | +4% |
| Tracing | 20 Jul | 202 | 115 | 230 | −5% |

**Outcome.** The effect is within run-to-run noise (about 4 to 5%). Neither adds meaningful latency. This is consistent with the visibility work being asynchronous and outside the synchronous latency budget.

### 4.4 Inference service (28 Jul)

**Overview.** Measures how scaling Inference pods reduced latency under load.

**Change tested.** Inference replicas 1, 2 and 3, with Auth at 3 and Platform Core at 1.

**Environment.** 20 users, burstable infrastructure.

| Step | Run | RPS | Avg ms | P95 ms | Δ |
|---|---|---|---|---|---|
| 1 Inference replica | 28 Jul | 239 | 80 | 160 | baseline |
| 2 Inference replicas | 28 Jul | 359 | 51 | 91 | +50% |
| 3 Inference replicas | 28 Jul | 362 | 52 | 100 | +1% |

**Outcome.** The second pod cut average latency from 80 to 51 ms and gave most of the gain. A third adds almost nothing at this point because the next bottleneck is elsewhere.

### 4.5 Platform Core (28 Jul)

**Overview.** Measures how scaling Platform Core reduced latency under load.

**Change tested.** Platform Core from 1 to 2 replicas, with Auth at 3 and Inference at 3.

**Environment.** 20 users, burstable infrastructure.

| Step | Run | RPS | Avg ms | P95 ms | Δ |
|---|---|---|---|---|---|
| 1 Platform Core replica | 28 Jul | 362 | 52 | 100 | baseline |
| 2 Platform Core replicas | 28 Jul | 422 | 44 | 76 | +17% |

**Outcome.** Platform Core was the next limit after Inference. A second replica cut average latency from 52 to 44 ms and gave +17% throughput.

### 4.6 Nginx and connection tuning (28 Jul, part 2)

**Overview.** Checks what Nginx connection handling and the APISIX hop cost in latency under load.

**Change tested.** Requests through APISIX without keep-alive, then with keep-alive 100. A run that skipped APISIX measured how much the gateway hop itself costs.

**Environment.** 20 users, burstable infrastructure.

| Step | Run | RPS | Avg ms | P95 ms | Δ |
|---|---|---|---|---|---|
| Through APISIX, no keep-alive | 28 Jul | 619 | 26 | 53 | baseline |
| Skipping APISIX (reference) | 28 Jul | 692 | 21 | 33 | +12% |
| Keep-alive 100 | 28 Jul | 647 | 25 | 46 | +4.5% |

**Outcome.** Keep-alive adds 4.5% throughput and trims P95 from 53 to 46 ms. The whole APISIX hop costs about 12% of throughput.

### 4.7 Non-burstable infrastructure and load-generator upgrade (30 Jul)

**Overview.** Tests up to 28 Jul ran on burstable (t3a) instances and were preliminary. From 29 Jul the cluster moved to non-burstable nodes. On 30 Jul the load generator also moved from a burstable instance to a non-burstable one, to generate more load.

**Change tested.**
- Cluster: 2 x m6a.2xlarge CPU nodes, 2 x m6a.large system nodes.
- Load generator: burstable T-series to m6a.xlarge.
- Replicas (both runs): Auth 5, Inference 5, Platform Core 3, APISIX 2.

**Environment.** Single load generator, `/api/v1/chat`, stubbed model, `-r 5 -t 3m`.

| Step | Run | RPS | Avg ms | P95 ms | Δ |
|---|---|---|---|---|---|
| Burstable load generator, 20 users | 1 | 583 | 27 | 35 | baseline |
| m6a.xlarge load generator, 30 users | 2 | 1,162 | 21 | 28 | +99% |

**Outcome.**
- Throughput doubled, from 583 to 1,162 RPS. Average latency fell from 27 to 21 ms and P95 from 35 to 28 ms.
- Non-burstable infrastructure gives stable numbers that can be compared from here on.
- Zero failures.

**Notes.** Users changed from 20 to 30 together with the load generator, so the +99% is a combined effect.

### 4.8 Distributed load generation: 2-hour run (5 Aug)

**Overview.** By 30 Jul a single m6a.xlarge load generator was the limit, so it moved to distributed Locust (one master and two workers). The result shown is the full 2-hour run.

**Change tested.**
- Load generator: single machine to distributed Locust (master + 2 workers).
- Duration: 3 minutes to 2 hours.
- Replica setup of the 5 Aug run: Auth 5, Inference 5 (1 Uvicorn worker), Platform Core 3, APISIX 2, Nginx 1, with the Kafka consumer enabled on 4 partitions. This matches the final setup.

**Environment.** Same infrastructure as 4.7. `-u 20 -r 2 --run-time 2h`.

| Step | Run | RPS | Avg ms | P95 ms | Δ |
|---|---|---|---|---|---|
| Single load generator, 30 users, 3 min (4.7) | n/a | 1,162 | 21 | 28 | baseline |
| Distributed, 20 users, 2 hours | Run 1 | 1,240 | 15 | 40 | +7% |

8,931,136 requests in total. P50 was 11 ms and P99 was 86 ms.

**Outcome.**
- The cluster held 1,240 RPS for two hours. The RPS is a floor for capacity, not a limit.
- Average latency is 15 ms, down from 21 ms with the single load generator. The median is 11 ms, about at the 10 ms target.
- The average of 15 ms is at the 15 ms ceiling, with no margin.

**Notes.**
- P95 is higher in the 2-hour run (40 ms vs 28 ms). Users (20 vs 30) and duration also differ, so the rows are not like-for-like.
- The worse tail is likely an effect of the long soak (for example garbage collection pauses, noisy neighbours, Kafka or Fluent Bit activity). This is a hypothesis and has not been tested.
- The P95 of 40 ms is above the 10 to 15 ms band and is the open item.

### 4.9 Kafka consumer lag and partition analysis (18 Aug to 2 Sep)

This is a throughput and freshness topic, not a latency one. The Kafka path is asynchronous and outside the synchronous latency budget.

**Problem.**
- The Kafka consumers (PPU) were throttling.
- Real-time spend could not be seen in the Portal, because processing fell behind the request rate.

**Changes analysed.**
- Kafka consumer (PPU) pods 4 to 8, Kafka broker memory 2–4Gi to 2–8Gi, and Fluent Bit consumer memory 128–256Mi to 256Mi–1Gi.
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

## 5. Capacity and headroom

- Sustained: 1,240 RPS for 2 hours on 2 x m6a.2xlarge CPU nodes and 2 x m6a.large system nodes.
- Headroom: this is a floor, not a limit. The load generator was still the constraint, and no CPU warning appeared in the 2-hour run.
- Latency: the median is 11 ms against the 10 ms target, and the average is 15 ms against the 15 ms ceiling. The P95 of 40 ms is above the band.

## 6. Pod-level change summary

| Component | Change | Effect |
|---|---|---|
| Auth | 1 to 3 pods (28 Jul), later 5 | Largest gain on the gateway path (+75% with the full plugin stack) |
| Inference | 1 to 2 pods | +50% (3 pods gave +1% more) |
| Platform Core | 1 to 2 pods | +17% |
| APISIX | 1 to 2 pods | +2% |
| Nginx | keep-alive 100 | +4.5% |
| Infra and load generator | burstable to m6a | +99% (combined with 20 to 30 users) |
| Load generator | single machine to distributed | removed the load generator limit |
| Kafka (PPU) | 4 to 8 pods, more memory, 8 partitions | lag fell to 21–35 s |

## 7. Recommendations

- Run Auth at 5 pods, Inference at 5 pods, Platform Core at 2 to 3 pods and APISIX at 2 pods as the baseline.
- Keep Nginx keep-alive on.
- Use non-burstable nodes for any capacity or SLA test.
- Run Kafka consumers at 8 pods with 8 partitions, and watch consumer lag as well as request latency.
- Use distributed Locust for any test above about 1,100 RPS.
- Investigate the tail latency (P95 40 ms) in the long run, since it is above the 10 to 15 ms band.

## 8. Conclusion

On the final setup the `/api/v1/chat` path sustained 1,240 RPS for two hours. AI4I adds at most 11 ms at the median and 15 ms on average, with the load generator still the limit, so capacity is at least this figure. The median is about at the 10 ms target and the average is at the 15 ms ceiling. The tail (P95 40 ms, P99 86 ms) is above the band and is the open item.

## Open items

- Stub response time: measure it directly and add it as a footnote to section 1.
- Pass/fail metric: confirm whether the client treats median, average or both as pass/fail.
- Which Kafka change fixed the partition imbalance.
- Which Auth node type is correct for 29 to 30 Jul.
- Whether the 5 Aug 2-hour run used the final setup (Auth 5, Inference 5, Platform Core 3, APISIX 2, Nginx 1).
