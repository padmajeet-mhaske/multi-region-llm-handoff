# Multi-Region LLM Agent Infrastructure — Experiment Framework

IEEE TKDE DK-GenAI Special Issue submission.

Compares 4 Write Engine algorithms × 4 Read Engine algorithms for
region-handoff performance of stateful LLM agents.

## Quick Start

### 1. Prerequisites

- Docker + Docker Compose
- Python 3.10+
- `ANTHROPIC_API_KEY` exported in your shell

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

### 2. Start Infrastructure

```bash
docker compose up -d
# Wait ~60s for Cassandra to initialize
python config/toxiproxy_setup.py
```

### 3. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 4. Run Experiments

```bash
# Experiment A: Write Engine Ablation (W0 vs W1–W4, read fixed at R0)
python -m experiments.run_experiment_a --iterations 100 --output results/experiment_a

# Experiment B: Read Engine Ablation (W0 fixed, R0 vs R1–R4)
python -m experiments.run_experiment_b --iterations 100 --output results/experiment_b

# Experiment C: Hybrid Comparison (best write + best read vs baseline)
python -m experiments.run_experiment_c \
    --iterations 100 --best-write W1 --best-read R1 \
    --output results/experiment_c
```

For paper-quality runs use `--iterations 1000` and `--model claude-sonnet-4-6`.

### 5. Generate Figures

```bash
cd analysis && jupyter notebook analysis.ipynb
```

---

## Algorithm Overview

### Write Engines

| ID | Algorithm | Key Property |
|----|-----------|--------------|
| W0 | Naive Full Write (baseline) | Every trace → Cassandra synchronously |
| W1 | Selective Flush | Local Redis first; flush on milestone or 50KB threshold |
| W2 | WAL + Async Batch | Redis WAL; background batch drain to Cassandra |
| W3 | CRDT Merge | G-Set CRDT; region merge on handoff |
| W4 | Adaptive Pre-flush | Sigmoid handoff predictor; proactive flush |

### Read Engines

| ID | Algorithm | Key Property |
|----|-----------|--------------|
| R0 | Full Context Dump (baseline) | Entire history sent to receiving region |
| R1 | Context Window Hydration Protocol | Milestones + 2 recent traces only |
| R2 | LLM Summarization (MemWalker) | Claude-compressed summary before handoff |
| R3 | Semantic RAG Retrieval | Top-K traces by cosine similarity |
| R4 | MemGPT Hierarchical Memory | Main context + recursive archival summaries |

---

## Metrics

- `write_latency_ms` — per-trace local write latency
- `flush_latency_ms` — batch/global flush latency
- `handoff_latency_ms` — total Region B resume latency (p50/p95/p99)
- `context_payload_bytes` — bytes sent on handoff
- `context_token_count` — actual Claude input tokens
- `compression_ratio` — full dump bytes / payload bytes
- `input_token_delta` — tokens saved vs baseline
- `estimated_cost_usd` — per-iteration Claude API cost
- `state_integrity_score` — fraction of milestone context preserved

---

## Infrastructure

```
redis-a  :6379   — Region A hot cache
redis-b  :6380   — Region B hot cache
cassandra:9042   — Global durable state store
toxiproxy:8474   — WAN latency simulation (120ms, ~0.1% loss)
prometheus:9090  — Metrics scraping
```

## Security

`ANTHROPIC_API_KEY` is **never** hardcoded. Always read from environment:

```python
import os
api_key = os.environ.get("ANTHROPIC_API_KEY")
```
