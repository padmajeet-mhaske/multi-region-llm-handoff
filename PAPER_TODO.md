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
