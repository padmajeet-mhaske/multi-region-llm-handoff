# How to Run the Experiments

Complete step-by-step guide for setting up and executing the multi-region
LLM agent experiment framework.

---

## Table of Contents

1. [System Requirements](#1-system-requirements)
2. [Get the Code](#2-get-the-code)
3. [Set Your API Key](#3-set-your-api-key)
4. [Python Environment](#4-python-environment)
5. [Start Docker Infrastructure](#5-start-docker-infrastructure)
6. [Verify Infrastructure Health](#6-verify-infrastructure-health)
7. [Run Experiment A — Write Engine Ablation](#7-run-experiment-a--write-engine-ablation)
8. [Run Experiment B — Read Engine Ablation](#8-run-experiment-b--read-engine-ablation)
9. [Run Experiment C — Hybrid Comparison](#9-run-experiment-c--hybrid-comparison)
10. [Generate Paper Figures](#10-generate-paper-figures)
11. [Full CLI Reference](#11-full-cli-reference)
12. [Cost Estimates](#12-cost-estimates)
13. [Troubleshooting](#13-troubleshooting)
14. [Running Without Docker (local Redis only)](#14-running-without-docker-local-redis-only)

---

## 1. System Requirements

| Requirement | Minimum | Recommended |
|-------------|---------|-------------|
| OS | macOS 12+, Ubuntu 20.04+, Windows WSL2 | Ubuntu 22.04 |
| Python | 3.10 | 3.11 |
| Docker | 24.0 | latest |
| Docker Compose | v2.20 | latest |
| RAM | 4 GB free | 8 GB free |
| Disk | 3 GB free | 5 GB free |
| CPU | 2 cores | 4 cores |

---

## 2. Get the Code

```bash
git clone https://github.com/padmajeet-mhaske/pedomatic.git
cd pedomatic/multi-region-llm
```

---

## 3. Set Your API Key

The key is **always read from the environment** — never stored in any file.

```bash
# macOS / Linux (add to ~/.bashrc or ~/.zshrc to persist)
export ANTHROPIC_API_KEY=sk-ant-api03-...

# Windows PowerShell
$env:ANTHROPIC_API_KEY = "sk-ant-api03-..."

# Or use a .env file (never commit this)
cp .env.example .env
# Edit .env and fill in your key, then:
source .env        # macOS/Linux only
```

Verify the key is set:

```bash
echo $ANTHROPIC_API_KEY   # should print your key (not empty)
```

---

## 4. Python Environment

Create an isolated virtual environment to avoid package conflicts:

```bash
# Create and activate
python3 -m venv .venv
source .venv/bin/activate      # macOS/Linux
# .venv\Scripts\activate       # Windows

# Install all dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

The install will download `sentence-transformers` and its model weights
(~90 MB for `all-MiniLM-L6-v2`) on first use by Experiment B's R3 algorithm.

---

## 5. Start Docker Infrastructure

From the `multi-region-llm/` directory:

```bash
# Start all services in the background
docker compose up -d

# Cassandra needs ~60 seconds to bootstrap. Watch it with:
docker compose logs -f cassandra
# Wait until you see: "Created default superuser role 'cassandra'"
# Then Ctrl+C to exit the log tail.
```

Once Cassandra is ready, configure Toxiproxy to simulate WAN latency:

```bash
python config/toxiproxy_setup.py
# Expected output:
# Setting up Toxiproxy WAN simulation...
# WAN simulation active: 120ms latency, ~0.1% loss
```

---

## 6. Verify Infrastructure Health

Run this quick sanity check before starting experiments:

```bash
# Redis A
redis-cli -p 6379 ping              # should return PONG

# Redis B
redis-cli -p 6380 ping              # should return PONG

# Cassandra
docker exec cassandra-global cqlsh -e "DESCRIBE KEYSPACES;"
# should list: system, system_auth, system_distributed, system_traces

# Toxiproxy
curl -s http://localhost:8474/proxies | python3 -m json.tool
# should show redis-a-wan and redis-b-wan proxies

# Claude API
python3 -c "
import anthropic, os
c = anthropic.Anthropic()
r = c.messages.create(model='claude-haiku-4-5', max_tokens=10,
    messages=[{'role':'user','content':'ping'}])
print('Claude OK:', r.usage)
"
```

---

## 7. Run Experiment A — Write Engine Ablation

Compares W0 (naive baseline) vs W1, W2, W3, W4 with read fixed at R0.

**Quick test (10 iterations, ~5 min, low cost):**

```bash
python -m experiments.run_experiment_a \
    --iterations 10 \
    --output results/experiment_a
```

**Standard run (100 iterations per condition, ~30 min):**

```bash
python -m experiments.run_experiment_a \
    --iterations 100 \
    --output results/experiment_a
```

**Paper-quality run (1000 iterations, higher-quality model):**

```bash
python -m experiments.run_experiment_a \
    --iterations 1000 \
    --model claude-sonnet-4-6 \
    --output results/experiment_a_paper
```

**Output files produced:**

```
results/experiment_a/
├── experiment_a_raw.csv          # one row per iteration
├── experiment_a_raw.json         # same data as JSON
├── experiment_a_summary.csv      # p50/p95/p99/mean per condition
├── wilcoxon_write_latency_ms.csv # statistical significance vs baseline
└── wilcoxon_flush_latency_ms.csv
```

---

## 8. Run Experiment B — Read Engine Ablation

Compares R0 (full dump baseline) vs R1, R2, R3, R4 with write fixed at W0.

**Quick test:**

```bash
python -m experiments.run_experiment_b \
    --iterations 10 \
    --output results/experiment_b
```

**Standard run:**

```bash
python -m experiments.run_experiment_b \
    --iterations 100 \
    --output results/experiment_b
```

**Output files produced:**

```
results/experiment_b/
├── experiment_b_raw.csv
├── experiment_b_raw.json
├── experiment_b_summary.csv
├── wilcoxon_handoff_latency_ms.csv
├── wilcoxon_context_token_count.csv
├── wilcoxon_compression_ratio.csv
├── wilcoxon_input_token_delta.csv
└── wilcoxon_estimated_cost_usd.csv
```

> **Note on R3 (Semantic RAG):** The first run downloads the `all-MiniLM-L6-v2`
> model (~90 MB). Subsequent runs use the local cache and are faster.

---

## 9. Run Experiment C — Hybrid Comparison

Combines the best write algorithm (from Exp A results) with the best read
algorithm (from Exp B results). Defaults to W1 + R1.

**Quick test:**

```bash
python -m experiments.run_experiment_c \
    --iterations 10 \
    --best-write W1 \
    --best-read R1 \
    --output results/experiment_c
```

**Standard run with custom best algorithms:**

```bash
# After reviewing Exp A/B results, pick your winners:
python -m experiments.run_experiment_c \
    --iterations 100 \
    --best-write W1 \
    --best-read R1 \
    --output results/experiment_c
```

The script automatically creates 4 conditions:
- `C0_Baseline` (W0 + R0)
- `C1_WriteOnly_W1` (W1 + R0)
- `C2_ReadOnly_R1` (W0 + R1)
- `C3_Hybrid_W1_R1` (W1 + R1)

**Output files produced:**

```
results/experiment_c/
├── experiment_c_raw.csv
├── experiment_c_raw.json
├── experiment_c_summary.csv
├── wilcoxon_write_latency_ms.csv
├── wilcoxon_handoff_latency_ms.csv
├── wilcoxon_context_token_count.csv
├── wilcoxon_compression_ratio.csv
└── wilcoxon_estimated_cost_usd.csv
```

---

## 10. Generate Paper Figures

After all three experiments have produced output:

```bash
cd analysis
jupyter notebook analysis.ipynb
```

Or run headlessly to export all figures at once:

```bash
cd analysis
jupyter nbconvert --to notebook --execute analysis.ipynb \
    --output analysis_executed.ipynb
```

Figures are saved to `figures/`:

| File | Content |
|------|---------|
| `fig1_write_engine_cdf.pdf` | Write latency CDF for W0–W4 |
| `fig2_write_boxplot.pdf` | Write latency box plot |
| `fig3_read_engine_comparison.pdf` | Handoff latency / tokens / integrity |
| `fig4_compression_vs_integrity.pdf` | Compression vs integrity scatter |
| `fig5_hybrid_comparison.pdf` | Hybrid vs all conditions grouped bar |

---

## 11. Full CLI Reference

All three experiment scripts share these common flags:

| Flag | Default | Description |
|------|---------|-------------|
| `--iterations N` | 100 | Number of agent sessions per condition |
| `--output PATH` | varies | Directory for CSV/JSON result files |
| `--model MODEL` | `claude-haiku-4-5` | Claude model for agent calls |
| `--redis-a-port PORT` | 6379 | Redis A port (Region A hot cache) |
| `--redis-b-port PORT` | 6380 | Redis B port (Region B hot cache) |
| `--cassandra-host HOST` | localhost | Cassandra host |

**Experiment C only:**

| Flag | Default | Description |
|------|---------|-------------|
| `--best-write W?` | W1 | Write algorithm to use in hybrid |
| `--best-read R?` | R1 | Read algorithm to use in hybrid |

**Available model values:**

| Value | Cost | Use case |
|-------|------|----------|
| `claude-haiku-4-5` | $1/1M input | Development, stress tests, quick runs |
| `claude-sonnet-4-6` | $3/1M input | Paper-quality measurements |

---

## 12. Cost Estimates

All estimates assume the default `claude-haiku-4-5` model
($1.00/M input tokens, $5.00/M output tokens).

| Run type | Iterations/condition | Conditions | Est. total cost |
|----------|---------------------|------------|-----------------|
| Quick test | 10 | 5 | ~$0.05 |
| Standard | 100 | 5 | ~$0.50 |
| Full paper (A+B+C) | 1000 | 14 | ~$7–10 |
| Full paper (Sonnet) | 1000 | 14 | ~$20–30 |

Prompt caching is enabled on stable system prompts, cutting repeated-call
costs by up to 90% on cache hits. Actual costs logged per-iteration in
`estimated_cost_usd` column.

---

## 13. Troubleshooting

**`ANTHROPIC_API_KEY not set`**
```bash
export ANTHROPIC_API_KEY=sk-ant-...
# Verify: python3 -c "import os; print(os.environ['ANTHROPIC_API_KEY'][:10])"
```

**`redis.exceptions.ConnectionError`**
```bash
docker compose ps          # check redis-a and redis-b are "Up"
docker compose restart redis-a redis-b
```

**`cassandra.cluster.NoHostAvailable`**
```bash
docker compose ps cassandra   # check status
docker compose logs cassandra | tail -20
# If "not ready", wait another 30s and retry
docker compose restart cassandra
```

**Toxiproxy `ConnectionRefused` on port 8474**
```bash
docker compose ps toxiproxy
docker compose restart toxiproxy
python config/toxiproxy_setup.py   # re-run after restart
```

**`sentence_transformers` import error (R3 RAG)**
```bash
pip install sentence-transformers torch --upgrade
# On Apple Silicon, torch may need:
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

**Cassandra schema errors on first run**

The DDL is auto-applied by `HandoffRunner.__init__`. If you see
`AlreadyExists` warnings, those are safe to ignore — they mean the
tables already exist from a previous run.

**Experiment crashes mid-run**

Results written so far are already saved to CSV/JSON. You can resume
from a specific iteration range by running the script again — it appends,
it does not overwrite. Then filter out duplicates by `iteration` + `condition`
when loading in the notebook.

**High latency / test taking too long**

The WAN simulation (120ms) is intentional. To disable it for faster
iteration during development:

```bash
curl -X DELETE http://localhost:8474/proxies/redis-a-wan
curl -X DELETE http://localhost:8474/proxies/redis-b-wan
```

Re-enable with `python config/toxiproxy_setup.py`.

---

## 14. Running Without Docker (local Redis only)

If Docker is unavailable, you can run a minimal version using only
local Redis (no Cassandra, no Toxiproxy):

```bash
# Start Redis manually (macOS: brew install redis)
redis-server --port 6379 &
redis-server --port 6380 &

# Mock Cassandra by overriding the connect function
# Edit src/handoff_runner.py → connect_cassandra() to use a dict-based stub:
```

A lightweight stub implementation is provided for this case — create
`src/cassandra_stub.py`:

```python
class StubSession:
    def execute(self, *args, **kwargs):
        pass  # no-op

def connect_cassandra_stub():
    return StubSession()
```

Then patch `connect_cassandra` in `handoff_runner.py` to call
`connect_cassandra_stub()` during local-only testing.

Note: With the stub, write engine metrics (flush latency) will be near-zero
and won't reflect realistic global-DB write costs. Only use for algorithm
logic validation, not for paper measurements.

---

## Stopping Everything

```bash
# Stop Docker services
docker compose down

# Remove volumes (clears all Cassandra data)
docker compose down -v

# Deactivate virtual environment
deactivate
```
