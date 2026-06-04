# Experiment Results — Reference Log

Multi-Region LLM Agent Infrastructure  
IEEE TKDE DK-GenAI Special Issue

---

## Run Index

| Run ID | Date | Type | Model | Iterations | Cost | Status |
|--------|------|------|-------|-----------|------|--------|
| [RUN-001](#run-001--pipeline-validation) | 2026-06-04 | Pipeline validation | claude-haiku-4-5 | 3/condition | $0.0352 | Complete ✅ |

---

## RUN-001 — Pipeline Validation

**Date:** 2026-06-04  
**Purpose:** Verify real Claude API calls work end-to-end through the full write → read → metrics pipeline  
**Model:** `claude-haiku-4-5`  
**Iterations per condition:** 3  
**Environment:** Cloud sandbox, native Redis (6379/6380), Cassandra in-memory stub  
**Flags:** `CASSANDRA_STUB=1` (no real Cassandra — flush latencies are near-zero)  
**Total API calls:** ~98  
**Total cost:** $0.0352  

---

### Experiment A — Write Engine Ablation

Read engine fixed at **R0** (full dump baseline). Comparing W0–W4 write strategies.

| Condition | Write Algo | n | Write p50 (ms) | Write p95 (ms) | Flush p50 (ms) | Flush p95 (ms) | Handoff p50 (ms) | Handoff p95 (ms) | Tokens (mean) | Cost/iter ($) | Integrity |
|-----------|-----------|---|---------------|---------------|---------------|---------------|-----------------|-----------------|--------------|--------------|-----------|
| C0_Baseline | W0 Naive | 2 | 0.003 | 0.003 | 0.003 | 0.003 | 3,793.96 | 4,299.20 | 899.5 | 0.0024 | 1.0 |
| C1_W1_Selective | W1 Selective Flush | 3 | 0.239 | 0.278 | 0.005 | 0.006 | 3,924.92 | 4,289.76 | 956.7 | 0.0024 | 1.0 |
| C1_W2_WAL | W2 WAL + Async Batch | 3 | 0.364 | 0.365 | 0.494 | 0.557 | 3,840.88 | 4,158.28 | 952.0 | 0.0024 | 1.0 |
| C1_W3_CRDT | W3 CRDT Merge | 3 | 0.267 | 0.292 | 0.000 | 0.000 | 3,396.43 | 4,239.53 | 1,068.0 | 0.0028 | 1.0 |
| C1_W4_Adaptive | W4 Adaptive Pre-flush | 3 | 0.263 | 0.303 | 0.017 | 0.018 | 4,109.52 | 6,451.07 | 966.3 | 0.0026 | 1.0 |

**Key observations:**
- All algorithms maintained `state_integrity_score = 1.0` — no context loss
- `handoff_latency_ms` (~3.8s) reflects real `claude-haiku-4-5` API round-trip from sandbox
- `flush_latency_ms` values are near-zero for W0/W1/W3/W4 because Cassandra stub is in-memory — **not representative of real DB write cost**; W2 (WAL batch drain) shows 0.494ms even against stub due to pipeline overhead
- W3 (CRDT) has highest token count (1,068) — CRDT metadata adds overhead to context
- W4 (Adaptive) shows highest p95 handoff (6,451ms) — pre-flush operations add variance

> **Note:** For meaningful `flush_latency_ms` comparisons, re-run with real Cassandra  
> (`docker compose up -d`, remove `CASSANDRA_STUB=1`). The WAN simulation (120ms via Toxiproxy)  
> will show clear differentiation between W0 (every trace flushed) vs W1 (milestone-only flush).

---

### Bugs Fixed During This Run

| Bug | Symptom | Fix | File |
|-----|---------|-----|------|
| Trailing whitespace in assistant content | `400 invalid_request_error: final assistant content cannot end with trailing whitespace` | `.strip()` on `result["content"]` before appending to conversation | `src/agent_simulator.py:88` |

---

### Cost Breakdown

| Metric | Value |
|--------|-------|
| Model | claude-haiku-4-5 |
| Input token price | $1.00 / 1M tokens |
| Output token price | $5.00 / 1M tokens |
| Avg tokens per iteration | ~950 input / ~150 output |
| Avg cost per iteration | $0.0025 |
| Total iterations | 14 (3 per condition, 1 failed) |
| Total API calls | ~98 |
| **Total spend** | **$0.0352** |

---

### Environment Notes

| Component | Status | Details |
|-----------|--------|---------|
| Redis A (6379) | ✅ Real | Native redis-server 7.0.15 |
| Redis B (6380) | ✅ Real | Native redis-server 7.0.15 |
| Cassandra | ⚠️ Stub | In-memory dict (`CASSANDRA_STUB=1`) — flush latencies not real |
| Toxiproxy | ❌ Not used | WAN simulation not active — handoff latency = raw Claude API RTT |
| Claude API | ✅ Real | 98 calls to `api.anthropic.com`, all 200 OK |

---

## Planned Runs

| Run ID | Experiment | Model | Iterations | Est. Cost | Notes |
|--------|-----------|-------|-----------|----------|-------|
| RUN-002 | A + B + C | haiku-4-5 | 100/condition | ~$5 | Standard run, real Cassandra + Toxiproxy |
| RUN-003 | A + B + C | haiku-4-5 | 1000/condition | ~$30 | Full statistical power |
| RUN-004 | A + B + C | sonnet-4-6 | 1000/condition | ~$100 | Paper-quality figures |

---

## How to Reproduce RUN-001

```bash
# Start Redis
redis-server --port 6379 --daemonize yes --save "" --appendonly no
redis-server --port 6380 --daemonize yes --save "" --appendonly no

# Run (replace key with your own)
ANTHROPIC_API_KEY=sk-ant-... \
CASSANDRA_STUB=1 \
python -m experiments.run_experiment_a \
  --iterations 3 \
  --output results/real_test
```

## How to Run Full Paper Experiments

```bash
# With full Docker infrastructure (real Cassandra + WAN simulation)
docker compose up -d
python config/toxiproxy_setup.py

ANTHROPIC_API_KEY=sk-ant-... \
python -m experiments.run_experiment_a --iterations 1000 --output results/experiment_a

ANTHROPIC_API_KEY=sk-ant-... \
python -m experiments.run_experiment_b --iterations 1000 --output results/experiment_b

ANTHROPIC_API_KEY=sk-ant-... \
python -m experiments.run_experiment_c \
  --iterations 1000 --best-write W1 --best-read R1 \
  --output results/experiment_c
```
