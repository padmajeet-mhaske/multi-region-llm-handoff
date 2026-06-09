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

- [ ] **Rerun all experiments at n≥30/condition** (n=3 currently — Wilcoxon tests meaningless)
  - Need new API key
  - Need Docker: `docker compose up -d` (real Cassandra, real Redis)
  - Remove `CASSANDRA_STUB=1` from run commands
  - Target: `results/run_004/` with n=30, then `results/run_005/` with n=100 for final
- [ ] **Fix R3 column (5 missing cells)** — all W×R3 pairs fail due to missing `sentence_transformers`
  - `pip install sentence-transformers` inside Docker or venv
  - R3 data is critical — W1+R3 CatastrophicInterference is the core paper claim
- [ ] **Enable Toxiproxy WAN simulation** (RQ4 — WAN sensitivity)
  - `python config/toxiproxy_setup.py` adds 120ms + jitter between Redis A → Cassandra
  - Without this, latency numbers are localhost-only and not representative

---

## Section I — Introduction

- [~] Problem statement exists in RESEARCH.md §1 — needs rewrite into IEEE prose style
- [ ] Write opening "T HIS paper..." drop-cap paragraph
- [ ] Add 2–3 forward references to figures ("as shown in Fig. 1")
- [ ] State 4 research questions (RQ1–RQ4) formally in numbered list
- [ ] Add 1-paragraph contributions summary ("The main contributions of this paper are:")

---

## Section II — Related Work  ← BIGGEST GAP

- [ ] **Cluster A: Multi-region distributed storage**
  - CRDTs (Shapiro et al. 2011 — original CRDT paper)
  - Dynamo (DeCandia et al. 2007)
  - Cassandra (Lakshman & Malik 2010)
  - Spanner (Corbett et al. 2012)
- [ ] **Cluster B: LLM agent memory / context management**
  - MemGPT (Packer et al. 2023)
  - Retrieval-Augmented Generation (Lewis et al. 2020)
  - LongMem / context compression papers
  - LLM session continuity / agent state papers
- [ ] **Cluster C: LLM evaluation / LLM-as-a-Judge**
  - G-Eval (Liu et al. 2023)
  - MT-Bench / Chatbot Arena (Zheng et al. 2023)
- [ ] **Cluster D: Cost-efficient inference**
  - Token compression / prompt pruning
  - KV cache offloading
- [ ] Write ~800-word related work section in IEEE style with [1]–[N] citations
- [ ] Confirm gap: "No prior work benchmarks write+read strategy *combination* for cross-region handoff"

---

## Section III — System Architecture

- [~] Two-tier design described in RESEARCH.md §12
- [ ] Draw **Fig. 1** — architecture diagram: Agent A → Redis A → Cassandra → Redis B → Agent B
  - Label WAN crossover points (Crossover 1, Crossover 2)
  - Label latency tiers (<1ms hot, 1–10ms warm, 120ms WAN)
- [ ] Write formal section text (~600 words) from RESEARCH.md §12 content
- [ ] Add formal definition of session state `S = {(role, content, ts, milestone_flag)}`
- [ ] Add equation for state integrity score formula

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

- [~] RQ1–RQ4 defined in RESEARCH.md §2 — needs IEEE prose rewrite
- [~] Ablation rationale in RESEARCH.md §3 — good, needs light editing
- [ ] Write **Table I** — Environment configuration (hardware, Redis version, Cassandra version, model)
- [ ] Write **Table II** — Metrics definitions (all 9 metrics with formula and unit)
- [ ] Write LLM-as-a-Judge methodology sub-section
  - Fidelity prompt + Continuity prompt (can paste from code)
  - Dual-score design rationale
  - Inter-rater reliability note
- [ ] Write cost estimation methodology (token counting, pricing model)
- [ ] Add Docker compose setup as a reproducibility note

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

- [~] Key findings in RESEARCH.md §13 — ready but needs IEEE prose
- [ ] Write Finding 1: W4+R4 is the Pareto-optimal pairing (fastest + perfect integrity)
- [ ] Write Finding 2: W1+R1 double-milestone anti-pattern (integrity collapse to 0.417)
- [ ] Write Finding 3: W1+R3 CatastrophicInterference (requires R3 data — blocked)
- [ ] Write Finding 4: W3+R1 latency penalty (CRDT metadata × hydration overhead)
- [ ] Write Finding 5: Co-design principle — "independently optimal algorithms are not jointly optimal"
- [ ] Add threat to validity sub-section (sandbox stub, n=3 prototype runs, single model)

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

- [ ] **Acknowledgment** — API credits (Anthropic), any funding
- [ ] **References** — compile all [1]–[N] in IEEE format (target: 20–25 references)
- [ ] **Author Biographies** — 1 paragraph each (education, current role, research interests)
- [ ] **Author Photos** — 1×1.25 inch headshots at 300 dpi

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
