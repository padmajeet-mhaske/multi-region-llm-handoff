# IEEE TKDE DK-GenAI — Paper TODO

Track progress toward submission-ready draft.  
Branch: `claude/multi-region-redis-testing-9GiVw`

---

## Status Legend
- `[ ]` Not started
- `[~]` In progress / partial
- `[x]` Done

---

## BLOCKER: Data Quality (must fix before stats-heavy sections)

### Step 1 — Install Docker Desktop (your laptop, one-time)
- [ ] Download and install Docker Desktop: https://docker.com/products/docker-desktop
  - Works on Mac, Windows, Linux
  - No AWS/GCP needed — everything runs locally in containers
  - Gives us: real Cassandra + real Redis + Toxiproxy WAN simulation

### Step 2 — Install sentence-transformers (one command, one-time)
- [ ] `pip install sentence-transformers`
  - Unlocks R3 column (5 missing cells) — needed for W1+R3 CatastrophicInterference finding
  - Downloads all-MiniLM-L6-v2 model (~90 MB) automatically on first run
  - No GPU needed — CPU inference is fine for our use case
  - Without this: W1+R3 (core paper claim) has zero data points

### Step 3 — Get a new Anthropic API key
- [ ] Go to https://console.anthropic.com → API Keys → Create new key
- [ ] Revoke both previous keys used in this project (see session summary)
- [ ] Cost estimate for full paper-quality run:
  - n=30/pair  → ~$2.25   (acceptable for validation run)
  - n=100/pair → ~$7.50   (paper quality — recommended)

### Step 4 — Run the full experiment together
- [ ] Start containers: `docker compose up -d`
- [ ] Enable WAN simulation: `python config/toxiproxy_setup.py`
  - Adds 120ms + 10ms jitter between Redis A → Cassandra (realistic cross-region latency)
- [ ] Run Experiment D (n=100):
  ```bash
  ANTHROPIC_API_KEY=<new_key> \
  python -m experiments.run_experiment_d \
    --enabled --iterations 100 \
    --output results/run_004 \
    --surface-plots
  ```
- [ ] Output goes to `results/run_004/` — will auto-generate 3D surface plots

### Step 5 — Generate heatmaps (I will do this after Step 4)
- [ ] Install seaborn: `pip install seaborn`
- [ ] I will run `plot_heatmap()` against the new CSV — produces 4 publication PNGs:
  - Fig. 2: State integrity heatmap (5×5)
  - Fig. 3: Handoff latency heatmap (5×5)
  - Fig. 6: Bar chart — Experiment A write ablation
  - Fig. 7: Box plot — WAN latency sensitivity
- [ ] All figures saved to `results/run_004/`

### Step 6 — Fill in Results section (I will do this after Step 4)
- [ ] Tables III–VI with real n=100 numbers (replacing n=3 prototype values)
- [ ] Wilcoxon significance table with valid p-values
- [ ] §VII Finding E: W1+R3 CatastrophicInterference — write with real measured values

### Step 7 — Final paper touches (you provide, I format)
- [ ] Author names, affiliations, ORCIDs → I will format into IEEE style
- [ ] Funding acknowledgment text → I will insert into Acknowledgment section
- [ ] Author headshots (1×1.25 in, 300 dpi) → submit separately with manuscript

---

## Section I — Introduction

- [x] Problem statement — rewritten into IEEE prose style
- [x] Write opening "T HIS paper..." drop-cap paragraph
- [x] Forward references to figures ("as shown in Fig. 1")
- [x] State 4 research questions (RQ1–RQ4) formally in numbered list
- [x] Add 5-point contributions summary
  - → See PAPER_DRAFT.md § SECTION I

---

## Section II — Related Work

- [x] **Cluster A: Multi-region distributed storage** — [1]–[6]: Shapiro CRDTs ×2,
      Dynamo, Cassandra, Spanner, CockroachDB
- [x] **Cluster B: LLM agent memory / context management** — [7]–[11]: MemGPT, RAG,
      Sentence-BERT, ReAct, LLMLingua
- [x] **Cluster C: LLM evaluation / LLM-as-a-Judge** — [12]–[13]: G-Eval, MT-Bench
- [x] **Cluster D: Cost-efficient inference** — [11], [14]: LLMLingua, PagedAttention
- [x] Write ~900-word related work section in IEEE style with [1]–[14] citations
- [x] Gap confirmed: "No prior work examines write+read strategy *interaction*
      for cross-region LLM handoff"
  - → See PAPER_DRAFT.md § SECTION II

---

## Section III — System Architecture

- [x] Two-tier design — written in full IEEE prose (~700 words)
- [x] Fig. 1 — ASCII architecture diagram with crossover labels included in draft
- [x] Formal session state definition referencing Eq. (1)
- [x] Cassandra justification sub-section (§III-E)
- [x] Both crossover points explained (§III-C, §III-D)
  - → See PAPER_DRAFT.md § SECTION III

---

## Section IV — Algorithm Design

- [x] **Algorithm 1** — W0: Naive Synchronous Write
- [x] **Algorithm 2** — W1: Selective Flush (milestone-triggered)
- [x] **Algorithm 3** — W2: WAL + Async Batch
- [x] **Algorithm 4** — W3: CRDT G-Set Merge (with `S_A ⊔ S_B` join formula)
- [x] **Algorithm 5** — W4: Adaptive Pre-flush (with sigmoid predictor)
- [x] **Algorithm 6** — R0: Full Dump Hydration
- [x] **Algorithm 7** — R1: Milestone Hydration
- [x] **Algorithm 8** — R2: LLM Summarization Read
- [x] **Algorithm 9** — R3: Semantic RAG (all-MiniLM-L6-v2 embeddings)
- [x] **Algorithm 10** — R4: MemGPT Hierarchical Retrieval
- [x] Eq. (3) — W4 sigmoid: `p(flush) = 1 / (1 + exp(-k(t - t₀)))`
- [x] Eq. (2) — W3 CRDT: `S_merged = S_A ∪ S_B, vc_merged = max(vc_A, vc_B)`
- [x] Eq. (5) — Compression ratio: `CR = T_R0 / T_Rx`
- [x] Eq. (1) — State definition
- [x] Eq. (4) — LLM-as-a-Judge scoring (integrity + retrieval)
- [x] Eq. (6) — Per-iteration API cost
  - → All in PAPER_DRAFT.md § SECTION III and § SECTION IV

---

## Section V — Experimental Methodology

- [x] RQ1–RQ4 — rewritten in IEEE prose with RQ numbering
- [x] Ablation rationale — written (A/B/C/D structure explained)
- [x] **Table I** — Environment configuration (all components, versions, parameters)
- [x] **Table II** — All 10 metrics with formula, unit, and paper use
- [x] LLM-as-a-Judge sub-section (fidelity + continuity, separation rationale)
- [x] Statistical testing sub-section (Wilcoxon, Holm-Bonferroni, n≥100 note)
- [x] Reproducibility note with minimal and full-Docker commands
  - → See PAPER_DRAFT.md § SECTION V

---

## Section VI — Results

- [~] RUN-002 and RUN-003 data in RESULTS.md — needs restructuring into paper tables/figures
- [ ] **Table III** — Experiment A: Write ablation (W0–W4, R0 fixed) — key metrics, n≥30
- [ ] **Table IV** — Experiment B: Read ablation (R0–R4, W0 fixed) — key metrics, n≥30
- [ ] **Table V** — Experiment C: Compatibility matrix (5 hand-picked pairs)
- [ ] **Table VI** — Experiment D: Full 5×5 surface summary (25 cells, p50 latency + integrity)
- [ ] **Fig. 2** — Heatmap: State integrity score (5×5, seaborn, with class annotations)
- [ ] **Fig. 3** — Heatmap: Handoff latency p50 ms (5×5)
- [ ] **Fig. 4** — 3D surface: Handoff latency (already have PNG from RUN-003 ✅)
- [ ] **Fig. 5** — 3D surface: State integrity score (already have PNG from RUN-003 ✅)
- [ ] **Fig. 6** — Bar chart: Write algorithm comparison (Experiment A)
- [ ] **Fig. 7** — Box plot: Latency survival / WAN sensitivity (requires Toxiproxy run)
- [ ] Add Wilcoxon significance table (requires n≥30 — currently n=3)

---

## Section VII — Discussion

- [x] Finding A: W4+R4 Pareto-optimal — mechanism explained (temporal decoupling)
- [x] Finding B: W1+R1 double-filter anti-pattern (0.417 integrity) — mechanism explained
- [x] Finding C: W3+R1 latency penalty — metadata amplification mechanism explained
- [x] Finding D: Co-design principle — deployment constraint table referenced
- [x] Threats to validity sub-section (n=3, Cassandra stub, single model, R3 missing)
- [ ] Finding E: W1+R3 CatastrophicInterference — BLOCKED (requires R3 data / Docker)
  - → See PAPER_DRAFT.md § SECTION VII

---

## Section VIII — Conclusion

- [x] Write 3-paragraph conclusion:
  - Para 1: What we did (5×5 surface, LLM-as-a-Judge evaluation)
  - Para 2: Key findings (W4+R4 winner, W1+R3 toxic, co-design principle)
  - Para 3: Future work (WAN sensitivity, >2 regions, other LLM families)
  - → See PAPER_DRAFT.md § SECTION VIII

---

## Front Matter

- [~] **Title** — drafted: "Write-Read Co-Design for Cross-Region LLM Agent Session Handoff: An Exhaustive Compatibility Surface Analysis"
- [ ] **Authors** — real names, affiliations, ORCIDs
- [x] **Abstract** — written (~280 words, stand-alone) → See PAPER_DRAFT.md § ABSTRACT
- [x] **Index Terms** — 6 keywords written → See PAPER_DRAFT.md § INDEX TERMS

---

## Back Matter

- [x] **Acknowledgment** — placeholder written (needs funding details)
- [x] **References** — 14 fully verified IEEE-format citations [1]–[14]
      (all DOIs confirmed via ACM DL, ACL Anthology, arXiv)
- [~] **Author Biographies** — template written; needs real names/details
- [ ] **Author Photos** — 1×1.25 inch headshots at 300 dpi
  - → See PAPER_DRAFT.md § BACK MATTER

---

## Figures Checklist

| Fig # | Description | Status | Blocker |
|-------|-------------|--------|---------|
| Fig. 1 | Architecture diagram (Agent A → Redis A → Cassandra → Redis B → Agent B) | ❌ | Need to draw |
| Fig. 2 | Heatmap: state_integrity_score 5×5 | ❌ | Need seaborn + n≥30 |
| Fig. 3 | Heatmap: handoff_latency_ms 5×5 | ❌ | Need seaborn + n≥30 |
| Fig. 4 | 3D surface: handoff_latency_ms | ✅ | In results/run_003/ |
| Fig. 5 | 3D surface: state_integrity_score | ✅ | In results/run_003/ |
| Fig. 6 | Bar chart: Experiment A write ablation | ❌ | Need n≥30 data |
| Fig. 7 | Box plot: WAN latency sensitivity | ❌ | Need Toxiproxy run |

---

## Quick-Start Order (recommended sequence)

```
Step 1 (now, no data needed):   Write Abstract + Conclusion + Index Terms
Step 2 (now, no data needed):   Write Algorithm pseudocode blocks (all 10)
Step 3 (now, no data needed):   Write formal equations (CRDT, sigmoid, scoring)
Step 4 (research needed):       Write Related Work with citations (~2 hrs)
Step 5 (Docker + new API key):  Rerun at n=30, fix R3 column → unlock all stats
Step 6 (after Step 5):          Generate final heatmaps, bar charts, box plots
Step 7 (after Step 6):          Fill in all results tables with real numbers
Step 8 (final):                 Author bios, acknowledgment, reference list
```

---

*Last updated: 2026-06-09*
