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
- Note: it is assumed that the model stub adds no latency, so the measured latency is treated as AI4I overhead. This is conservative, because the measurement also includes Locust client time and the network hop to Nginx.

The results are summarised in section 2 and detailed in section 4.

## 2. Summary

**Outcome.** Under a sustained load of 1,240 RPS, 24% above the 1,000 RPS requirement, AI4I held an 11 ms median and a 15 ms average across 8.9M requests in 2 hours. Failures were 0.00% (4 of 8.93M).

- **Against the 10 ms SLA:** the median (11 ms) is within 1 ms of it. The average (15 ms) is 5 ms above it.
- **Throughput:** from about 240 RPS in the first `/chat` runs (burstable infrastructure, one replica per service) to 1,240 RPS on the final setup (non-burstable infrastructure, scaled replicas, distributed load). The gain comes from both the scaling and the better infrastructure.
- **Largest gains:**
  - Non-burstable infrastructure and a larger load generator: +99%.
  - Inference, 1 to 2 pods: +50%.
  - Platform Core, 1 to 2 pods: +17%. Together with Inference, `/chat` throughput rose from 240 to 422 RPS (+76%).
  - Auth scale-out gave no gain by itself (a single Inference pod was the limit), but it removes the 323 RPS limit of one Auth pod.
- **APISIX cost:** the gateway adds about 15 ms of average latency (5 ms hop, 8 ms auth plugin, 2 ms other plugins) once Auth is scaled. Before scaling, the plugins cost about 50 ms.
- **Smaller gains:**
  - Keep-alive tuning: +4.5%.
  - Second APISIX replica: +2%.
- **Async work:** tracing and usage events through Kafka are not part of the synchronous latency and did not affect request throughput. With 8 consumer pods on 8 partitions the messages were spread evenly across the partitions and the consumers kept pace with the load.

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

Each section follows the same structure: overview, change tested, test setup, a one-row table with the result, outcome and notes. The row shows the throughput and latency before and after the change. Improvement in RPS is the change in requests per second. Improvement in latency is the fall in average latency (a negative value means latency rose). Each section is framed around what reduced latency under load. The `/api/v1/chat` runs of 21 Jul and 28 Jul follow on from one another (4.2 to 4.4), so their gains add up.

### 4.1 APISIX gateway: contribution to latency (28 Jul)

**Overview.** The APISIX gateway sits between Nginx and the services and runs a plugin chain on every request. This section measures how much latency APISIX adds altogether, from the gateway hop and from its plugins.

**Change tested.** Nginx straight to the inference service (skipping APISIX), compared with the full path through APISIX with the full plugin stack. The runs in between split the cost into the hop, the auth plugin and the other plugins.

**Test setup.** 20 users, 3 min. Auth 3, Inference 3, Platform Core 2, APISIX 1, burstable (t3a) infrastructure.

| Action | Run | RPS | Avg ms | Improvement in RPS | Improvement in latency |
|---|---|---|---|---|---|
| Skipping APISIX to full APISIX plugin stack | 28 Jul | 692 → 511 | 21 → 36 | −26% | −71% (+15 ms) |

**Outcome.** APISIX adds about 15 ms of average latency and costs 26% of throughput. Of the 15 ms, 5 ms is the gateway hop (26 ms with no plugins), 8 ms is the auth plugin (34 ms) and 2 ms is the other plugins (36 ms).

**Notes.**
- These runs use the plugin-latency test endpoints, which go through Nginx and APISIX to a stubbed inference handler, not through `/api/v1/chat`.
- Before Auth was scaled (21 Jul, 25 users, 1 pod of each service), the same plugins cost about 50 ms of average latency: 32 ms with no plugins, 72 ms with the auth plugin only and 82 ms with the full stack. The auth plugin was 40 ms of that. The cost fell to about 10 ms (26 to 36 ms) once Auth, Inference and Platform Core were scaled. Users and bastion also differ between the two days, so this is a combined effect.

### 4.2 Auth service: scale-out (21 Jul, 28 Jul)

**Overview.** Every request calls the Auth service to validate the caller before it goes any further. On 21 Jul, calling Auth directly averaged 71 ms at 25 users, against 97 ms for the whole `/chat` path (without plugins), so Auth is the largest part of a request. One Auth pod handled 323 RPS on its own. This section shows what scaling Auth from 1 to 3 pods did on `/chat`.

**Change tested.** Auth from 1 to 3 pods. The CPU limit of each pod went from 1000m to 600m, so the total CPU allowed for Auth rose from 1.0 to 1.8 cores. Inference and Platform Core stayed at 1 pod in the 28 Jul run.

**Test setup.** 25 users on 21 Jul, 20 users on 28 Jul, 3 min. Burstable infrastructure. Bastion t3a.medium on 21 Jul and t3a.xlarge on 28 Jul.

| Action | Run | RPS | Avg ms | Improvement in RPS | Improvement in latency |
|---|---|---|---|---|---|
| Auth 1 → 3 pods | 21 Jul → 28 Jul | 240 → 239 | 97 → 80 | 0% | +18%\* |

**Outcome.** Throughput did not change, because a single Inference pod limits `/chat` to about 239 RPS (see 4.3). Scaling Auth removes the next limit: one Auth pod handled 323 RPS on its own, so the higher throughput in 4.3 and 4.4 (359 and 422 RPS) needs more than one Auth pod.

**Notes.**
- A pod is one running copy of the service, and each copy can validate only a limited number of requests at a time. With one pod, requests queue and latency rises. With three, the same load is shared across three copies and the queueing mostly disappears.
- Each pod became smaller (1000m to 600m), but Auth as a whole has more CPU (1.0 to 1.8 cores) and three copies. A lower per-pod limit alone would make each pod slower, so the gain cannot come from the smaller size.
- \*The fall in average latency from 97 to 80 ms is not credited to Auth. At the same throughput, average latency is roughly users divided by RPS (25 / 240 is about 104 ms, 20 / 239 is about 84 ms), and the users fell from 25 to 20.
- A control run on 21 Jul with the larger bastion changed throughput by about 4%. The Platform Core count on 21 Jul is not recorded (it was 1 on 28 Jul).

### 4.3 Inference service (28 Jul)

**Overview.** Measures how scaling Inference pods reduced latency under load.

**Change tested.** Inference from 1 to 2 pods, with Auth at 3 and Platform Core at 1. The 1-pod run is the same 28 Jul run as the end point of 4.2.

**Test setup.** 20 users, 3 min. Burstable infrastructure.

| Action | Run | RPS | Avg ms | Improvement in RPS | Improvement in latency |
|---|---|---|---|---|---|
| Inference 1 → 2 pods | 28 Jul | 239 → 359 | 80 → 51 | +50% | +36% |

**Outcome.** The second pod cut average latency from 80 to 51 ms and gave most of the gain.

**Notes.** A third pod added almost nothing (362 RPS, +1%) because the next limit is elsewhere.

### 4.4 Platform Core (28 Jul)

**Overview.** Measures how scaling Platform Core reduced latency under load.

**Change tested.** Platform Core from 1 to 2 pods, with Auth at 3 and Inference at 3.

**Test setup.** 20 users, 3 min. Burstable infrastructure.

| Action | Run | RPS | Avg ms | Improvement in RPS | Improvement in latency |
|---|---|---|---|---|---|
| Platform Core 1 → 2 pods | 28 Jul | 362 → 422 | 52 → 44 | +17% | +15% |

**Outcome.** Platform Core was the next limit after Inference. A second pod cut average latency from 52 to 44 ms.

**Notes.** Across 4.2 to 4.4 the `/chat` throughput went from 240 to 422 RPS, a gain of 76%. It came from the Inference and Platform Core scale-out, with the Auth scale-out making that headroom possible.

### 4.5 Nginx and connection tuning (28 Jul, part 2)

**Overview.** Checks what Nginx connection handling cost in latency under load.

**Change tested.** Requests through APISIX without keep-alive, then with keep-alive 100.

**Test setup.** 20 users, 3 min. Burstable infrastructure. Auth 3, Inference 3, Platform Core 2, APISIX 1, on the plugin-latency baseline endpoint.

| Action | Run | RPS | Avg ms | Improvement in RPS | Improvement in latency |
|---|---|---|---|---|---|
| Nginx keep-alive 100 | 28 Jul | 619 → 647 | 26 → 25 | +4.5% | +4% |

**Outcome.** Keep-alive adds 4.5% throughput and trims P95 from 53 to 46 ms.

### 4.6 Non-burstable infrastructure and bastion upgrade (30 Jul)

**Overview.** Tests up to 28 Jul ran on burstable (t3a) instances and were preliminary. From 29 Jul the cluster moved to non-burstable nodes. On 30 Jul the load generator also moved from a burstable instance to a non-burstable one, to generate more load.

**Change tested.**
- Cluster: 2 × m6a.2xlarge CPU nodes, 2 × m6a.large system nodes.
- Bastion: burstable T-series to m6a.xlarge.
- Replicas (both runs): Auth 5, Inference 5, Platform Core 3, APISIX 2.

**Test setup.** 20 and 30 users, 3 min. Single bastion, `/api/v1/chat`, stubbed model, `-r 5 -t 3m`.

| Action | Run | RPS | Avg ms | Improvement in RPS | Improvement in latency |
|---|---|---|---|---|---|
| Burstable → m6a.xlarge bastion | 30 Jul | 583 → 1,162 | 27 → 21 | +99% | +22% |

**Outcome.**
- Throughput doubled and average latency fell from 27 to 21 ms. P95 fell from 35 to 28 ms.
- Non-burstable infrastructure gives stable numbers that can be compared from here on.
- Zero failures.

**Notes.** Users changed from 20 to 30 together with the bastion, so the +99% is a combined effect.

### 4.7 Distributed load generation: 2-hour run (5 Aug)

**Overview.** From 5 Aug the load was generated with distributed Locust (one master and two workers). Distributed mode spreads the simulated users across several machines, so more requests can be generated and the load-generating machine is not itself throttled. The result shown is the full 2-hour run.

**Change tested.**
- Load generator: multiple bastions to accommodate distributed Locust (master + 2 workers).
- Duration: 2 hours.
- Replica setup of the 5 Aug run: Auth 5, Inference 5 (1 Uvicorn worker), Platform Core 3, APISIX 2, Nginx 1, with the Kafka consumer enabled on 4 partitions. This matches the final setup.

**Test setup.** 20 users, 2 hours. Same infrastructure as 4.6. `-u 20 -r 2 --run-time 2h`.

| Action | Run | RPS | Avg ms | Improvement in RPS | Improvement in latency |
|---|---|---|---|---|---|
| Single bastion → distributed Locust | 5 Aug | 1,162 → 1,240 | 21 → 15 | +7% | +29% |

8,931,136 requests in total. P50 was 11 ms, P95 40 ms and P99 86 ms.

**Outcome.**
- The cluster held 1,240 RPS for two hours, and no CPU warning appeared during the run.
- Average latency is 15 ms, down from 21 ms with the single bastion. The median is 11 ms, about at the 10 ms target.

**Notes.**
- P95 is higher in the 2-hour run (40 ms vs 28 ms). Users (20 vs 30) and duration also differ, so the runs are not like-for-like.
- The worse tail is likely an effect of the long soak (for example garbage collection pauses, noisy neighbours, Kafka or Fluent Bit activity). This is a hypothesis and has not been tested.

### 4.8 Kafka consumer partition analysis (18 Aug to 2 Sep)

This is a throughput and freshness topic, not a latency one. The Kafka path is asynchronous and outside the synchronous latency budget.

**Problem.**
- The Kafka consumers (PPU) were throttling.
- Real-time spend could not be seen in the Portal, because processing fell behind the request rate.

**Changes analysed.**
- Memory and pods of a few entities were increased: Kafka consumer (PPU) pods 4 to 8, Kafka broker memory 2–4Gi to 2–8Gi, and Fluent Bit consumer memory 128–256Mi to 256Mi–1Gi.
- Kafka CPU was increased.
- The Kafka partitions were increased to 8.
- The distribution of messages across partitions was analysed, because it was uneven.

**Result.**

| Action | Run | Partition load | Outcome |
|---|---|---|---|
| PPU pods 4 → 8, 8 partitions | 2 Sep, 30 min | Evenly spread across all 8 partitions | Usage dashboards were showing real-time data with minimal delay (< 60 s) |

- With 8 pods on 8 partitions, all 8 partitions processed almost the same number of messages.
- The consumers kept pace with the load. On 18 Aug, after a 5-minute run at about 1,100 RPS, the backlog took 3 min 9 s to clear with 4 pods and 26 s with 8 pods. On 19 Aug, after 30-minute runs at about 1,055 RPS and 13 ms average, it cleared in 35 s and 21 s.
- Request throughput was not affected by any of these changes (about 910 to 1,170 RPS on 2 Sep).
- The uneven partition distribution was fixed by the increase in Kafka CPU and partitions.

## 5. Pod-level change summary

| Component | Change | Effect |
|---|---|---|
| Auth | 1 to 3 pods (28 Jul), later 5 | 0% by itself; removes the 323 RPS limit of one pod |
| Inference | 1 to 2 pods | +50% (3 pods gave +1% more) |
| Platform Core | 1 to 2 pods | +17% |
| APISIX | 1 to 2 pods | +2% (the gateway itself adds about 15 ms) |
| Nginx | keep-alive 100 | +4.5% |
| Infra and bastion | burstable to m6a | +99% (combined with 20 to 30 users) |
| Load generator | single bastion to distributed (master + 2 workers) | used for the 2-hour run (1,240 RPS) |
| Kafka (PPU) | 4 to 8 pods, more memory and CPU, 8 partitions | Messages spread evenly across the 8 partitions and consumers kept pace with the load |

## 6. Production infrastructure recommendation

### 6.1 Bare minimum infrastructure configuration

The following configuration represents the bare minimum infrastructure available at the start of the load tests. It is included as the initial baseline before the environment was scaled based on the performance-test results.

| Item | Bare minimum configuration |
|---|---|
| Total node capacity | 20 vCPU / 72 GiB RAM |
| Autoscaling (HPA) | Not configured |
| Ingress | Single load balancer through ingress-nginx |

| Application / request-path service | Initial pods |
|---|---|
| Auth Service | 1 |
| Inference Service | 1 |
| Platform Core Service | 1 |
| APISIX Gateway | 2 |
| Nginx Ingress Controller | 2 |
| Kafka consumers | 1 each |
| Simple UI | 1 |

| Supporting service | Pods | PVC |
|---|---|---|
| Postgres | 1 | 10 GiB |
| Redis | 1 | 5 GiB |
| Kafka | 1 | 10 GiB |
| ZooKeeper | 1 | 5 GiB |
| etcd | 1 | 5 GiB |
| OpenSearch | 1 | 20 GiB |
| OpenSearch Dashboards | 1 | - |
| Prometheus | 1 | 5 GiB |
| Alertmanager | 1 | - |
| Grafana | 1 | 5 GiB |

Total persistent storage: 65 GiB.

Initial resource usage: pod requests reserved approximately 5.1 vCPU and 8.3 GiB RAM in total, while combined idle usage was approximately 0.5 vCPU and 7.4 GiB RAM.

This configuration was sufficient as the starting point for load testing, but most application and data services ran with a single replica, so it had limited redundancy and was not intended as the final production configuration.

### 6.2 Recommended production worker capacity

| Item | Recommended production configuration |
|---|---|
| CPU worker nodes | 4 x m6a.2xlarge |
| Capacity per node | 8 vCPU / 32 GiB RAM |
| Total nominal capacity | 32 vCPU / 128 GiB RAM |
| Current persistent storage requirement | 160 GiB |
| Recommended storage provision | 180-200 GiB+ |

The production cluster is sized with a considerable amount of headroom above the CPU and memory requested by the tuned topology at 1,240 RPS. This headroom lets rolling deployments schedule their temporary surge pods without pods remaining Pending, and leaves room for Kubernetes system workloads, per-node DaemonSets, node maintenance and variation in traffic.

### 6.3 Recommended application and request-path pods

| Service | Recommended pods | Reason |
|---|---|---|
| Auth Service | 5 | Retains the tuned gateway-path capacity identified during load testing. |
| Inference Service | 5 | Supports the finalized request rate without reintroducing inference as a bottleneck. |
| Platform Core | 3 | Retains the tuned processing capacity used in the final setup. |
| APISIX | 2 | Provides gateway capacity and avoids a single gateway pod. |
| Nginx / ingress controller | 2 or more | A single Nginx pod handled the final 1,240 RPS test rate, but 2 or more are recommended for production redundancy and availability. |
| Kafka / PPU Consumers | 8 | Used with 8 Kafka partitions so asynchronous event processing keeps pace with load. |

Production request-path baseline: Auth 5, Inference 5, Platform Core 3, APISIX 2, Nginx 2 or more, and 8 Kafka/PPU consumers with 8 Kafka partitions.

### 6.4 Recommended supporting infrastructure services

| Infrastructure service | Pods | Purpose | PVC |
|---|---|---|---|
| Redis | 1 | Shared cache/data dependency. | 5 GiB |
| Postgres | 1 | Primary database dependency. | 10 GiB |
| Kafka Broker | 1 | Handles asynchronous events. | 100 GiB |
| ZooKeeper | 1 | Supports the current Kafka deployment. | 5 GiB |
| etcd | 1 | Required by APISIX. | 5 GiB |
| OpenSearch | 1 | Stores log and observability data. | 20 GiB |
| OpenSearch Dashboards | 1 | OpenSearch/log analysis UI. | - |
| Prometheus | 1 | Metrics collection and Platform Core scheduling dependency. | 10 GiB |
| Alertmanager | 1 | Monitoring alert processing. | - |
| Grafana | 1 | Metrics and monitoring dashboards. | 5 GiB |
| kube-state-metrics | 1 | Kubernetes state metrics. | - |
| kafka-exporter | 1 | Kafka metrics. | - |
| Fluent Bit Kafka Consumer | 1 | Logging/tracing pipeline toward OpenSearch. | - |
| Fluent Bit | 1 per applicable node | DaemonSet for log collection. | hostPath |
| node-exporter | 1 per node | DaemonSet for host metrics. | - |
| Total persistent PVC | - | Production persistent storage allocation | 160 GiB |

Storage requirement: the production baseline uses 160 GiB of PVC capacity. Kafka storage increased from 10 GiB initially to 100 GiB because the volume filled as test data grew during the load tests and required additional capacity. Prometheus is configured with 10 GiB in production, compared with 5 GiB in the initial configuration. Provisioning 180-200 GiB+ is recommended to retain storage headroom.

## 7. Why this production configuration is recommended

For the finalized 1,240 RPS capacity, this production configuration provides the CPU, memory and service-level capacity required to run the tuned request path reliably.

The final replica counts should be retained because the load tests showed clear throughput improvements when Auth, Inference, Platform Core and APISIX were scaled. The 8-consumer / 8-partition Kafka setup should also be retained so that asynchronous usage and event processing can keep pace with the request load.

A considerable amount of headroom needs to be maintained above the requested CPU and memory, and hence these recommendations are provided.

**Final recommendation.** Use 4 x m6a.2xlarge CPU worker nodes (32 vCPU / 128 GiB RAM) with the tuned production pod counts above, including 2 or more Nginx ingress-controller pods and 8 Kafka consumers with 8 partitions. Provide 160 GiB of persistent PVC capacity, with 180-200 GiB+ recommended for storage headroom. This should be used as the production baseline for the finalized 1,240 RPS capacity.
