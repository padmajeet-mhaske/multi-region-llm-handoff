# How to Run the Experiments

Complete step-by-step guide for setting up and executing the multi-region
LLM agent experiment framework.

---

## Table of Contents

1. [System Requirements](#1-system-requirements)
2. [Running on Windows](#2-running-on-windows)
3. [Get the Code](#3-get-the-code)
4. [Set Your API Key](#4-set-your-api-key)
5. [Python Environment](#5-python-environment)
6. [Start Docker Infrastructure](#6-start-docker-infrastructure)
7. [Verify Infrastructure Health](#7-verify-infrastructure-health)
8. [Run Experiment A — Write Engine Ablation](#8-run-experiment-a--write-engine-ablation)
9. [Run Experiment B — Read Engine Ablation](#9-run-experiment-b--read-engine-ablation)
10. [Run Experiment C — Hybrid Comparison](#10-run-experiment-c--hybrid-comparison)
11. [Generate Paper Figures](#11-generate-paper-figures)
12. [Full CLI Reference](#12-full-cli-reference)
13. [How Algorithm Comparison Data is Captured](#13-how-algorithm-comparison-data-is-captured)
14. [Cost Estimates](#14-cost-estimates)
15. [Troubleshooting](#15-troubleshooting)
16. [Running Without Docker (local Redis only)](#16-running-without-docker-local-redis-only)
12. [Cost Estimates](#12-cost-estimates)
13. [Troubleshooting](#13-troubleshooting)
14. [Running Without Docker (local Redis only)](#14-running-without-docker-local-redis-only)

---

## 0. How It Works — Input Data & Data Flow

### What does the end user actually need to provide?

**One thing: your `ANTHROPIC_API_KEY`.**

You do not write any prompts. You do not prepare any dataset. The framework
generates all conversation data automatically using Claude itself.

Here is what happens under the hood when you run an experiment:

```
┌─────────────────────────────────────────────────────────────────────┐
│                        WHAT YOU PROVIDE                             │
│                                                                     │
│   export ANTHROPIC_API_KEY=sk-ant-...    (your API key)            │
│   docker compose up -d                   (infrastructure)           │
│   python -m experiments.run_experiment_a (one command to run)       │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   STEP 1 — GENERATE SYNTHETIC SESSION               │
│                                                                     │
│  AgentSimulator picks a random built-in scenario, e.g.:            │
│  "Debug a distributed microservices outage affecting payments"      │
│                                                                     │
│  Then calls Claude 6 times to simulate a real conversation:         │
│                                                                     │
│  [user]      "I need your help: Debug a microservices outage..."   │
│  [assistant] "Let's start by checking the service mesh logs..."    │
│  [user]      "Can you elaborate on that?"                          │
│  [assistant] "The key issue is likely a cascading timeout..."      │
│  [user]      "What are the risks involved?"                        │
│  [assistant] "Resolved: circuit breaker confirmed as root cause."  │
│                    ↑ milestone (keyword "Resolved" detected)        │
│                                                                     │
│  Output: AgentSession with 6 TraceEntry objects                    │
│  (each trace stores: content, role, timestamp, is_milestone flag)  │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
┌─────────────────────────┐ ┌───────────────────────────────────────┐
│  STEP 2 — WRITE ENGINE  │ │  STEP 3 — READ ENGINE                 │
│                         │ │                                       │
│  W0 Naive (baseline):   │ │  R0 Full Dump (baseline):             │
│  Every trace → Cassandra│ │  Sends all 6 turns to Claude          │
│  synchronously          │ │                                       │
│                         │ │  R1 Hydration Protocol:               │
│  W1 Selective Flush:    │ │  Sends only milestones + 2 recent     │
│  Redis first, flush     │ │  → ~70% fewer tokens                  │
│  only on milestones     │ │                                       │
│                         │ │  R2 LLM Summarization:                │
│  W2 WAL + Async Batch:  │ │  Compresses history into summary,     │
│  Redis WAL → Cassandra  │ │  sends summary only                   │
│  in batches             │ │                                       │
│                         │ │  R3 Semantic RAG:                     │
│  W3 CRDT Merge:         │ │  Embeds query, retrieves top-5        │
│  G-Set, merge on handoff│ │  relevant traces by cosine similarity │
│                         │ │                                       │
│  W4 Adaptive Pre-flush: │ │  R4 MemGPT Hierarchical:              │
│  Predicts handoff,      │ │  Recent turns + archived summaries    │
│  flushes proactively    │ │  of older turns                       │
│                         │ │                                       │
│  Measures:              │ │  Measures:                            │
│  • write_latency_ms     │ │  • handoff_latency_ms                 │
│  • flush_latency_ms     │ │  • context_token_count (real API)     │
│  • total_bytes_written  │ │  • compression_ratio                  │
│                         │ │  • estimated_cost_usd                 │
│                         │ │  • state_integrity_score              │
└─────────────┬───────────┘ └──────────────────┬────────────────────┘
              └────────────┬────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   STEP 4 — RECORD ONE ROW                           │
│                                                                     │
│  iteration=42, condition=C1_W1_Selective, write_algorithm=W1,       │
│  read_algorithm=R0, write_latency_ms=1.23, flush_latency_ms=18.4,  │
│  handoff_latency_ms=312.7, context_token_count=387,                 │
│  compression_ratio=1.0, estimated_cost_usd=0.000412, ...           │
│                                                                     │
│  Repeat N times (default 100) per algorithm                        │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   STEP 5 — STATISTICAL OUTPUT                       │
│                                                                     │
│  experiment_a_raw.csv    ← every iteration, every algorithm         │
│  experiment_a_summary.csv← p50 / p95 / p99 / mean per algorithm    │
│  wilcoxon_*.csv          ← p-values vs baseline (is it significant?)│
│                                                                     │
│  analysis.ipynb          ← load CSVs → generate paper figures      │
└─────────────────────────────────────────────────────────────────────┘
```

---

### Claude is called TWICE per iteration

```
Iteration N
│
├─── Call 1 (AgentSimulator): Generate a 6-turn conversation
│    Model : claude-haiku-4-5
│    Purpose: Produce realistic traces that mimic a real agent session
│    Cost  : ~$0.0002 per session
│
└─── Call 2 (ReadEngine): Simulate Region B resuming the conversation
     Model : claude-haiku-4-5
     Purpose: Measure how well each algorithm reconstructs context
     Cost  : ~$0.0002–0.001 depending on algorithm (R0 is most expensive)
```

The key insight: **the second call is the actual experiment**. The read engine
sends different amounts of context to Claude, and we measure real token counts
and latency from the API response. The first call just generates the raw data
that gets stored and later retrieved.

---

### Built-in Scenarios (no input needed)

The simulator randomly picks from 8 pre-written business scenarios each iteration:

| # | Scenario |
|---|----------|
| 1 | Analyze quarterly financial data and identify cost-reduction opportunities |
| 2 | Debug a distributed microservices outage affecting payment processing |
| 3 | Generate a product roadmap for the next two quarters |
| 4 | Draft a technical specification for a new API endpoint |
| 5 | Evaluate three competing cloud infrastructure proposals |
| 6 | Summarize recent research papers on transformer architecture improvements |
| 7 | Plan a phased database migration with zero-downtime requirements |
| 8 | Review and fix security vulnerabilities in a Python web application |

You can add your own scenarios by editing `src/agent_simulator.py` → `TASK_SCENARIOS`.

---

### End User Checklist

```
□ 1. Get an Anthropic API key from console.anthropic.com
□ 2. Install Docker Desktop
□ 3. Clone the repo and cd into multi-region-llm/
□ 4. pip install -r requirements.txt
□ 5. export ANTHROPIC_API_KEY=sk-ant-...
□ 6. docker compose up -d  &&  python config/toxiproxy_setup.py
□ 7. python -m experiments.run_experiment_a --iterations 10   ← quick test
□ 8. Open analysis/analysis.ipynb to see figures
```

That is the complete end-user journey. No dataset preparation. No prompt writing.
No manual labelling. The framework is self-contained.

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

## 2. Running on Windows

**Short answer: Yes, Windows works.** The recommended path is WSL2 — it
gives you a full Linux environment on Windows with zero friction. Native
Windows (PowerShell) also works with small differences noted below.

---

### Option A — WSL2 + Ubuntu (Recommended)

WSL2 runs a real Linux kernel inside Windows. Docker Desktop integrates
with it directly, and you follow the rest of this guide verbatim.

**Step 1: Install WSL2**

Open PowerShell as Administrator:

```powershell
wsl --install -d Ubuntu
# Restart your machine when prompted
```

After restart, open the **Ubuntu** app from the Start menu, create a
username and password, then continue from [Section 3](#3-get-the-code)
inside that Ubuntu terminal.

**Step 2: Install Docker Desktop with WSL2 backend**

1. Download Docker Desktop from [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/)
2. During install, make sure **"Use WSL2 instead of Hyper-V"** is checked
3. After install → Docker Desktop Settings → Resources → WSL Integration →
   enable integration for your Ubuntu distro

Everything else — `docker compose`, `python`, `pip`, `git` — runs inside
the Ubuntu terminal exactly as documented.

---

### Option B — Native Windows (PowerShell)

All Python and Docker commands work natively. The differences vs Linux/Mac:

| Step | Linux / Mac | Windows PowerShell |
|------|-------------|-------------------|
| Set API key | `export ANTHROPIC_API_KEY=sk-...` | `$env:ANTHROPIC_API_KEY = "sk-..."` |
| Persist key across sessions | Add to `~/.bashrc` | Add to PowerShell `$PROFILE` |
| Activate venv | `source .venv/bin/activate` | `.venv\Scripts\Activate.ps1` |
| Test Redis locally | `redis-cli -p 6379 ping` | `docker exec redis-region-a redis-cli ping` |
| Source .env file | `source .env` | Does not work — set vars manually (see below) |
| Line endings | LF | CRLF — no impact on Python execution |

**Setting the API key in PowerShell (persisted):**

```powershell
# Add to your PowerShell profile so it survives restarts:
notepad $PROFILE
# Add this line and save:
$env:ANTHROPIC_API_KEY = "sk-ant-your-key-here"
```

**Activating the virtual environment in PowerShell:**

```powershell
# If you see "running scripts is disabled", run this once:
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# Then activate normally:
.venv\Scripts\Activate.ps1
```

**Running experiment scripts in PowerShell:**

```powershell
# Multi-line commands use backtick ` instead of backslash \
python -m experiments.run_experiment_c `
    --iterations 100 `
    --best-write W1 `
    --best-read R1 `
    --output results/experiment_c
```

---

### Option C — Cloud Environment (No local setup)

Best if you want to skip Docker on your machine entirely.

| Platform | Free tier | Notes |
|----------|-----------|-------|
| **GitHub Codespaces** | 60 hrs/month free | Linux + Docker pre-installed; open repo and go |
| **Google Cloud Shell** | Always free | Docker available; 5 GB persistent disk |
| **AWS EC2 t3.medium** | ~$0.04/hr | Best for 1000-iteration paper runs |
| **Google Colab** | Free (no Docker) | Redis-only mode only (see Section 16) |

For Codespaces: open the repo on GitHub → click **Code → Codespaces → New codespace** → follow this guide from Section 4.

---

## 3. Get the Code

```bash
git clone https://github.com/padmajeet-mhaske/pedomatic.git
cd pedomatic/multi-region-llm
```

---

## 4. Set Your API Key

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

## 5. Python Environment

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

## 6. Start Docker Infrastructure

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

## 7. Verify Infrastructure Health

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

## 8. Run Experiment A — Write Engine Ablation

> **Windows users:** use `python` instead of `python3`, and replace `\` line continuation with `` ` `` in PowerShell.

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

## 9. Run Experiment B — Read Engine Ablation

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

## 10. Run Experiment C — Hybrid Comparison

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

## 11. Generate Paper Figures

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

## 12. Full CLI Reference

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

## 13. How Algorithm Comparison Data is Captured

Understanding the data pipeline helps you know exactly what you're measuring
and where to find results.

---

### The Measurement Loop (one iteration)

Each iteration runs this sequence:

```
AgentSimulator.generate_session()
        │
        │  Multi-turn Claude conversation
        │  → produces AgentSession (6 turns, each a TraceEntry)
        ▼
WriteEngine.write_session(session)
        │
        │  Writes traces to Redis + Cassandra
        │  → measures write_latency_ms, flush_latency_ms
        ▼
ReadEngine.read_session(session)
        │
        │  Builds context payload, calls Claude to simulate Region B resuming
        │  → measures handoff_latency_ms, token counts, cost
        ▼
MetricsCollector.record(IterationMetrics)
        │
        │  Appends one row to in-memory list
        ▼
CSV / JSON on disk (after all iterations)
```

---

### What Each Layer Measures

**Write engine** (`src/write_engines/w1_selective_flush.py` etc.)

Each write algorithm returns a result object with:

| Field | How it's measured |
|-------|------------------|
| `write_latency_ms` | `time.perf_counter()` around the Redis SET call per trace |
| `flush_latency_ms` | `time.perf_counter()` around the Cassandra INSERT batch |
| `total_bytes_written` | Sum of `len(content.encode("utf-8"))` for all traces |

W1 only flushes on milestone events or when the unflushed buffer exceeds 50 KB,
so its `flush_latency_ms` is measured less frequently than W0's (which flushes
every trace). Lower `flush_latency_ms` mean + lower p99 = better write algorithm.

**Read engine** (`src/read_engines/r1_hydration_protocol.py` etc.)

Each read algorithm builds a context payload and calls Claude. It measures:

| Field | How it's measured |
|-------|------------------|
| `handoff_latency_ms` | `time.perf_counter()` wrapping the full `call_claude()` |
| `context_payload_bytes` | `len(json.dumps(message).encode("utf-8"))` per message |
| `context_token_count` | `response.usage.input_tokens` from the real Claude API response |
| `input_token_delta` | `count_tokens(full_payload) − count_tokens(compressed_payload)` using `client.messages.count_tokens()` |
| `compression_ratio` | `full_payload_bytes / compressed_payload_bytes` |
| `estimated_cost_usd` | `(input_tokens × $1.00 + output_tokens × $5.00) / 1,000,000` (Haiku pricing) |
| `state_integrity_score` | Fraction of milestone trace keywords that appear in the hydrated context (0–1) |

**Token counts are real** — the code calls `client.messages.count_tokens()`
(Anthropic's pre-send counting endpoint) for the delta comparison, and reads
`response.usage.input_tokens` from the actual Claude API response for the
final count. Nothing is estimated from word counts.

---

### The IterationMetrics Row

Every iteration produces one row in the CSV. Here's what a single row looks like:

```
iteration          = 42
condition          = C1_W1_Selective
write_algorithm    = W1
read_algorithm     = R0
session_id         = f3a9c1...
write_latency_ms   = 1.23       ← local Redis write, should be < 2ms
flush_latency_ms   = 18.4       ← Cassandra write (includes 120ms WAN sim)
total_bytes_written= 4821
handoff_latency_ms = 312.7      ← time for Region B to resume via Claude
context_payload_bytes = 2940
context_token_count= 387
compression_ratio  = 1.0        ← R0 = no compression (baseline)
input_token_delta  = 0          ← R0 = no savings vs itself
estimated_cost_usd = 0.000412
state_integrity_score = 1.0
extra              = {"flush_ratio": 0.33}   ← algorithm-specific extras
```

---

### Statistical Analysis

After all iterations complete, `MetricsCollector` computes:

**Summary stats** (`experiment_X_summary.csv`):
- `p50`, `p95`, `p99`, `mean`, `std` for every numeric metric
- Grouped by `condition` + `write_algorithm` + `read_algorithm`

**Wilcoxon signed-rank tests** (`wilcoxon_<metric>.csv`):
- Non-parametric test chosen because latency distributions are right-skewed (not normal)
- Tests each optimized algorithm against the C0 baseline
- Reports: `p_value`, `significant_p05`, `effect_size`, `median_reduction`

```
Example output row:
metric           = handoff_latency_ms
baseline         = C0_Baseline
comparison       = C2_R1_Hydration
n                = 100
p_value          = 0.0003
significant_p05  = True
effect_size      = 1.84        ← Cohen's d equivalent
median_reduction = 187.3 ms    ← median ms saved vs baseline
```

---

### Output File Reference

```
results/
├── experiment_a/
│   ├── experiment_a_raw.csv        ← one row per iteration (all conditions)
│   ├── experiment_a_raw.json       ← same data, JSON format
│   ├── experiment_a_summary.csv    ← p50/p95/p99/mean per algorithm
│   └── wilcoxon_write_latency_ms.csv
│   └── wilcoxon_flush_latency_ms.csv
├── experiment_b/
│   ├── experiment_b_raw.csv
│   ├── experiment_b_summary.csv
│   └── wilcoxon_*.csv              ← one file per metric
└── experiment_c/
    ├── experiment_c_raw.csv
    ├── experiment_c_summary.csv
    └── wilcoxon_*.csv
```

Load results manually for custom analysis:

```python
import pandas as pd

df = pd.read_csv("results/experiment_a/experiment_a_raw.csv")

# Compare W1 vs W0 handoff latency
w0 = df[df["write_algorithm"] == "W0"]["handoff_latency_ms"]
w1 = df[df["write_algorithm"] == "W1"]["handoff_latency_ms"]
print(f"W0 median: {w0.median():.1f}ms  W1 median: {w1.median():.1f}ms")
print(f"Reduction: {w0.median() - w1.median():.1f}ms ({(1 - w1.median()/w0.median())*100:.1f}%)")
```

---

## 14. Cost Estimates

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

## 15. Troubleshooting

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

## 16. Running Without Docker (local Redis only)

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
