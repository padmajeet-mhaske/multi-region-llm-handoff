# Research Reference — Multi-Region LLM Agent Infrastructure

IEEE TKDE DK-GenAI Special Issue  
*Last updated: 2026-06-04*

---

## 1. Problem Statement

Modern LLM agent applications run **long-running, stateful sessions** — multi-turn conversations
where an agent is mid-task (debugging, planning, document review) across hours or days.
When those sessions must migrate across geographic regions (failover, load balancing, user
mobility), the agent's entire conversation history must transfer **instantly, correctly, and cheaply**.

Current infrastructure treats handoff as an afterthought:
- **Full context dump** — expensive (tokens = cost), slow (WAN latency stacks)
- **Drop the context** — lossy (agent contradicts itself, user loses trust)

**No prior work benchmarks the write + read strategy combination for cross-region LLM agent handoff under realistic WAN conditions.**

---

## 2. Research Questions

### RQ1 — Write-Side Efficiency
> *"Which write persistence strategy minimizes flush latency and bytes written to distributed
> storage during a cross-region LLM agent handoff, without compromising data durability?"*

- **Maps to:** Experiment A (W0 vs W1–W4, R0 fixed)
- **Key metrics:** `write_latency_ms`, `flush_latency_ms`, `total_bytes_written`

---

### RQ2 — Read-Side Context Fidelity
> *"Which context hydration strategy best reduces input token consumption and handoff latency
> at the receiving region, while preserving conversation continuity?"*

- **Maps to:** Experiment B (R0 vs R1–R4, W0 fixed)
- **Key metrics:** `handoff_latency_ms`, `context_token_count`, `retrieval_accuracy_score`, `compression_ratio`

---

### RQ3 — Hybrid Compounding Effect
> *"When the optimal write strategy and optimal read strategy are combined, do the efficiency
> gains compound additively, or does interference between the two sides diminish the benefit?"*

- **Maps to:** Experiment C (C0 vs C1 vs C2 vs C3 Hybrid)
- **Key metrics:** `execution_latency_ms`, `estimated_cost_usd`, `state_integrity_score`, Wilcoxon p-value

---

### RQ4 — WAN Sensitivity *(requires Toxiproxy)*
> *"How does simulated cross-region WAN latency affect the relative performance ranking of
> write and read strategies?"*

- **Maps to:** Figure 7 (latency survival plot)
- **Key metrics:** `simulated_wan_latency_ms`, `wan_simulation_active`, `execution_latency_ms`

---

## 3. Experimental Design Rationale

The 3-experiment structure is a standard **ablation study** used in systems research:

| Experiment | What is varied | What is fixed | Purpose |
|-----------|---------------|--------------|---------|
| A | Write algorithm (W0–W4) | Read = R0 | Isolate write-side effect |
| B | Read algorithm (R0–R4) | Write = W0 | Isolate read-side effect |
| C | Best W + Best R combined | — | Test compounding of gains |

**Why W0 and R0 as baselines?**  
They represent the simplest possible implementation — naive full write and naive full context
dump. Every optimized algorithm must beat them on at least one metric to justify its complexity.

---

## 4. Algorithms

### Write Algorithms (W0–W4)

| ID | Name | Strategy | Key Innovation |
|----|------|----------|---------------|
| **W0** | Baseline | Every trace synchronously written to Cassandra | Control group |
| **W1** | Selective Flush | Traces stay in local Redis; flush to Cassandra only on milestone events OR when unflushed buffer exceeds 50 KB | Milestone-driven durability |
| **W2** | WAL + Async Batch | Append to Redis list (WAL); background thread drains in batches of 10 to Cassandra | Async batching, pipeline throughput |
| **W3** | CRDT Merge | Grow-only G-Set with vector clocks (Shapiro et al. 2011); region merge on handoff produces union | Conflict-free replication |
| **W4** | Adaptive Pre-flush | Sigmoid handoff probability predictor based on session age; proactively flushes when P(handoff) > 60% | Predictive durability |

**W1 flush trigger logic:**
```
if trace.is_milestone OR unflushed_bytes > 50_000:
    flush to Cassandra
```

**W4 sigmoid predictor:**
```
age_score = 1 / (1 + exp(-0.1 * (age_seconds - 10)))
if age_score > PREFLUSH_THRESHOLD (0.6):
    preflush()
```

---

### Read Algorithms (R0–R4)

| ID | Name | Strategy | Token Reduction | Integrity Risk |
|----|------|----------|----------------|---------------|
| **R0** | Full Dump | Sends entire conversation history to Claude | 0% (baseline) | None |
| **R1** | Hydration Protocol | Milestones + 2 most recent assistant turns; deduped by trace_id | ~70% | Low |
| **R2** | LLM Summarization | Claude compresses history into ≤200-word summary; receiving region resumes from summary | ~80% | Medium |
| **R3** | Semantic RAG | Embeds query "what is current task state?"; retrieves top-5 traces by cosine similarity (all-MiniLM-L6-v2) | ~60% | Medium |
| **R4** | MemGPT Hierarchical | Last 4 turns in main context; older turns compressed into recursive archival summaries (1 per 3 turns) | ~75% | Low–Medium |

**R1 selection logic:**
```
selected = milestone_traces ∪ last_2_assistant_traces  (deduped by trace_id)
```

**R3 embedding pipeline:**
```
query_vec = embed("What is the current task, latest decision, and next action?")
scores    = corpus_vecs @ query_vec          # cosine similarity (L2-normalized)
top_5     = argsort(scores)[::-1][:5]
```

**R4 memory tiers:**
```
main_context   = traces[-4:]                  # always included
archive_chunks = traces[:-4] grouped by 3     # each chunk → 1 Claude summary
```

---

## 5. Metrics

All metrics map directly to paper figures:

| Metric | Paper Use | Source |
|--------|----------|--------|
| `step_sequence_number` | X-axis: cost scaling plots | Global counter across experiment |
| `simulated_wan_latency_ms` | X-axis: latency survival / CDF | Toxiproxy RTT measurement |
| `input_tokens_used` | Token efficiency comparison | `simulator_input + handoff_input` |
| `output_tokens_used` | Output verbosity tracking | `simulator_output + handoff_output` |
| `execution_latency_ms` | Total step wall-clock time | Full iteration: write + handoff |
| `retrieval_accuracy_score` | Y-axis: context fidelity plots | Milestone content in Claude response |
| `compression_ratio` | Context size reduction | `full_bytes / payload_bytes` |
| `state_integrity_score` | Context continuity | Keyword overlap heuristic |
| `estimated_cost_usd` | API cost per iteration | From `response.usage` |

---

## 6. Real-World Motivation

### Where this matters

| Industry | Scenario | Metric that matters most |
|----------|----------|--------------------------|
| **Customer Support** | Agent mid-case, support rep changes shift/region | `state_integrity_score` |
| **Healthcare** | Clinical decision support, hospital failover | `retrieval_accuracy_score` |
| **Finance** | Trading assistant, DR failover during market hours | `execution_latency_ms` |
| **Legal / Enterprise** | Long-running document review, cost control | `estimated_cost_usd` |
| **Gaming / Consumer** | Companion AI, user moves continent | `handoff_latency_ms` |
| **Autonomous Agents** | Multi-day research/coding agent | `compression_ratio` |

### Real-world incidents validating the problem
- **Anthropic** (April 2024): 51-minute outage — all stateful agent sessions lost
- **OpenAI** (November 2024): 2+ hour degradation
- **Google Gemini** (February 2025): 38-minute rate-limit incident

---

## 7. State of the Art

### 7.1 LLM Agent Memory Architectures

#### MemGPT: Towards LLMs as Operating Systems
- **Authors:** Packer, Wooders, Lin, Fang, Patil, Gonzalez (UC Berkeley)
- **Venue:** arXiv:2310.08560 (Oct 2023, revised Feb 2024)
- **Key idea:** Virtual context management — LLM context window as "main memory," external storage as "disk." Interrupt-driven paging between tiers.
- **Relevance:** Direct foundation for R4 (MemGPT Hierarchical Reader). Cite when describing R4 design.
- **Gap your paper fills:** MemGPT manages memory *within* a single region. Your work adds *cross-region transfer* with durability guarantees.
- **Link:** https://arxiv.org/abs/2310.08560

---

#### Generative Agents: Interactive Simulacra of Human Behavior
- **Authors:** Park et al. (Stanford + Google)
- **Venue:** arXiv:2304.03442 (Apr 2023) | ACM UIST 2023
- **Key idea:** Memory stream (complete experience log) + Reflection (periodic synthesis into higher-level insights) + Planning. 25-agent simulation with emergent social behavior.
- **Relevance:** Your `is_milestone` flag parallels their "reflection triggers." Cite when justifying milestone detection.
- **Link:** https://arxiv.org/abs/2304.03442

---

#### MemWalker: Beyond Context Limit through Interactive Reading
- **Authors:** Chen, Pasunuru, Weston, Celikyilmaz (Meta AI)
- **Venue:** arXiv:2310.05029 (Oct 2023)
- **Key idea:** Builds a hierarchical memory tree by recursively summarizing chunks. Navigation via iterative LLM prompting — agent walks tree to find relevant node for a query.
- **Relevance:** R2 (LLM Summarization) is explicitly MemWalker-style. Direct citation for R2 design section.
- **Link:** https://ar5iv.labs.arxiv.org/html/2310.05029

---

#### Recursively Summarizing Enables Long-Term Dialogue Memory
- **Venue:** arXiv:2308.15022 (Aug 2023)
- **Key idea:** Recursive LLM compression of dialogue preserves long-term conversational continuity far beyond raw context window. Empirical integrity baseline.
- **Relevance:** Supports the compression + integrity trade-off framing in Experiment B.
- **Link:** https://arxiv.org/abs/2308.15022

---

#### ACON: Optimizing Context Compression for Long-horizon LLM Agents
- **Authors:** Kang et al. (Microsoft)
- **Venue:** arXiv:2510.00615 (Oct 2025)
- **Key idea:** Unified compression framework for environment observations and interaction histories. Failure-case analysis drives iterative refinement of compression guidelines.
- **Results:** **26–54% reduction in peak tokens**, >95% task accuracy preserved, up to 46% performance improvement on smaller models.
- **Relevance:** Closest existing work to R1/R2. Compare your `compression_ratio` and `retrieval_accuracy_score` against ACON's numbers in evaluation.
- **Link:** https://arxiv.org/abs/2510.00615

---

#### A-MEM: Agentic Memory for LLM Agents
- **Authors:** Xu, Liang, Mei, Gao, Tan, Zhang
- **Venue:** arXiv:2502.12110 (Feb 2025) | **NeurIPS 2025 poster**
- **Key idea:** Zettelkasten-style interconnected memory notes — each new memory generates a structured note with contextual descriptions, keywords, tags, and links to related memories. Agent dynamically reorganizes its own memory graph.
- **Relevance:** A-MEM shows the field moving toward *agent-controlled* memory organization. Your paper provides the *infrastructure layer* (write/read engines + distributed persistence) that A-MEM-style systems require underneath.
- **Link:** https://arxiv.org/abs/2502.12110

---

### 7.2 Multi-Region Distributed LLM Infrastructure

#### SkyWalker: A Locality-Aware Cross-Region Load Balancer for LLM Inference
- **Venue:** arXiv:2505.24095 | **ACM EuroSys 2025**
- **Key idea:** Cross-region LLM routing that preserves KV-cache locality. Uses consistent hashing on session/user ID + prefix trie for cache-aware routing across regions.
- **Results:** **1.12–2.06× higher throughput**, **1.74–6.30× lower latency** vs. naive cross-region routing.
- **Critical positioning:** SkyWalker solves *which region handles a request* (routing). Your paper solves *what happens when the region changes mid-session* (state transfer). These are complementary layers — SkyWalker's routing assumes a state-transfer mechanism exists; your paper provides it.
- **Link:** https://arxiv.org/abs/2505.24095

---

#### AIBrix: Towards Scalable, Cost-Effective LLM Inference Infrastructure
- **Venue:** arXiv:2504.03648 (Feb 2025) | vLLM project (open source)
- **Key idea:** Cloud-native LLM deployment framework with distributed KV cache, LoRA adapter management, SLO-driven GPU optimizer, Kubernetes + Ray hybrid orchestration.
- **Results:** 50% throughput increase, 70% latency reduction via distributed KV cache.
- **Relevance:** Production deployment platform your experiments would run on. Your write/read engines are application-level optimizations complementing AIBrix's system-level KV cache.
- **Link:** https://arxiv.org/abs/2504.03648

---

#### LMCache: An Efficient KV Cache Layer for Enterprise-Scale LLM Inference
- **Venue:** arXiv:2510.09665 (2025)
- **Key idea:** KV cache management layer for stateful LLM inference (agent workflows, multi-turn chat, RAG). Enables KV cache sharing across inference engines.
- **Gap your paper fills:** LMCache caches GPU-level KV tensors. Your work operates at the *conversation trace* level (text, milestones, CRDT state) — applicable when migrating between different model instances where KV cache cannot be transferred.
- **Link:** https://arxiv.org/pdf/2510.09665

---

#### ACM SIGCOMM 2025: Networking for Stateful LLM Inference
- **Venue:** ACM SIGCOMM 2025 Tutorial
- **Significance:** Entire tutorial at top networking venue dedicated to stateful LLM inference — confirms this is a recognized open research problem.
- **Link:** https://conferences.sigcomm.org/sigcomm/2025/tutorials-hackathons/tutorial-nllm/

---

### 7.3 CRDT and Distributed State for AI

#### CodeCRDT: Observation-Driven Coordination for Multi-Agent LLM Code Generation
- **Venue:** arXiv:2510.18893 (Oct 2025)
- **Key idea:** Applies G-Set CRDTs to multi-agent LLM coordination. Agents share state via observable CRDT updates with deterministic convergence — no explicit message passing.
- **Results:** **100% convergence, zero merge failures** across 600 trials. Identifies 5–10% semantic conflict rate.
- **Relevance:** Direct empirical validation of W3 (CRDT Merge Writer). Cite to show G-Set CRDTs work in LLM systems, not just classical distributed systems.
- **Link:** https://arxiv.org/abs/2510.18893

---

### 7.4 Industry Deployments

| Provider | Feature | Detail |
|----------|---------|--------|
| **Snowflake Cortex** | Cross-region inference GA | Routes to alternate AWS/Azure/GCP region when primary unavailable |
| **BentoML** | Multi-cloud inference guide | Session-level routing with failover across providers |
| **Letta** (MemGPT company) | Stateful agents platform | Production MemGPT-based persistent agent service |
| **Anthropic** | Prompt caching | `cache_control: ephemeral` — reduces repeated call cost 80–90% |

---

## 8. Paper Positioning

```
MEMORY MANAGEMENT LAYER
  MemGPT (2023) ────────── R4 builds directly on this
  Generative Agents (2023) ─ milestone/reflection parallel
  MemWalker (2023) ─────── R2 directly cites this  
  ACON (2025) ──────────── benchmark R1/R2 compression against this
  A-MEM (NeurIPS 2025) ─── your infra is what A-MEM needs underneath
          │
          ▼
  ┌─────────────────────────────────────────────────────┐
  │           YOUR PAPER (this work)                    │
  │  Cross-region handoff: write-side durability +      │
  │  read-side efficiency benchmarked under WAN         │
  └─────────────────────────────────────────────────────┘
          │
          ▲
INFRASTRUCTURE LAYER
  SkyWalker (EuroSys 2025) ─ routing; your work is the state-transfer it assumes
  AIBrix (2025) ──────────── deployment platform
  LMCache (2025) ─────────── GPU KV cache (complementary, not competing)
  CodeCRDT (2025) ────────── validates W3 CRDT design in LLM systems
```

---

## 9. Key Claim for Paper Introduction

> *"Despite significant advances in LLM agent memory management [MemGPT, ACON, A-MEM]
> and multi-region serving infrastructure [SkyWalker, AIBrix], no prior work addresses
> the state-transfer problem that arises when a stateful agent session must migrate across
> geographic regions mid-conversation. This paper bridges that gap with a systematic
> comparison of write persistence and read hydration strategies, providing the first
> empirical benchmark of cross-region LLM agent handoff under realistic WAN conditions."*

---

## 10. Citation List (BibTeX keys)

| Key | Paper | Year |
|-----|-------|------|
| `packer2023memgpt` | MemGPT: Towards LLMs as Operating Systems | 2023 |
| `park2023generative` | Generative Agents: Interactive Simulacra of Human Behavior | 2023 |
| `chen2023memwalker` | Walking Down the Memory Maze (MemWalker) | 2023 |
| `wang2023recursive` | Recursively Summarizing Enables Long-Term Dialogue Memory | 2023 |
| `kang2025acon` | ACON: Optimizing Context Compression for Long-horizon LLM Agents | 2025 |
| `xu2025amem` | A-MEM: Agentic Memory for LLM Agents | 2025 |
| `xiao2025skywalker` | SkyWalker: A Locality-Aware Cross-Region Load Balancer | 2025 |
| `aibrix2025` | AIBrix: Towards Scalable, Cost-Effective LLM Inference Infrastructure | 2025 |
| `lmcache2025` | LMCache: An Efficient KV Cache Layer for Enterprise-Scale LLM Inference | 2025 |
| `codecrdt2025` | CodeCRDT: Observation-Driven Coordination for Multi-Agent LLM Code Generation | 2025 |
| `shapiro2011crdt` | Conflict-Free Replicated Data Types (Shapiro et al.) | 2011 |
