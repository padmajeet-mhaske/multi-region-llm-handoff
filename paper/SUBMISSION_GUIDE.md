# IEEE TKDE Submission Guide
## Write-Read Co-Design for Cross-Region LLM Agent Session Handoff

**Journal:** IEEE Transactions on Knowledge and Data Engineering (TKDE)  
**Special Issue:** DK-GenAI (Distributed Knowledge for Generative AI)  
**Paper type:** Regular Paper  
**Manuscript file:** `paper/IEEE_TKDE_MultiRegion_LLM_Handoff.docx`

---

## Step 1: Format and Prepare Your Manuscript

### Use the Official IEEE Template
- Download the latest template from the [IEEE Template Selector](https://template-selector.ieee.org/)
- Select: **IEEE Transactions** → choose *Transactions on Knowledge and Data Engineering*
- Our manuscript is already formatted using this template (`paper/IEEE_TKDE_MultiRegion_LLM_Handoff.docx`)
- Convert to PDF before upload (Word → Save As → PDF, or use Adobe Acrobat)

### Check Page Limits

| Paper Type | Hard Limit | Allowed Overlength | EIC Approval Required |
|------------|-----------|-------------------|----------------------|
| Regular Paper | 12 double-column pages | Up to 14 pages (overlength charges apply) | 15–18 pages |
| Concise Paper | 6 double-column pages | — | — |
| Survey Paper | 20 double-column pages | — | — |

**Our paper target:** Regular Paper, ≤ 12 pages (includes abstract, references, biography)

> **Action:** After converting to PDF, count pages carefully. If over 12, tighten prose in §II Related Work or move detailed algorithm pseudocode to Supplemental Material.

### Isolate Appendices / Supplemental Material
Move any nonessential material into separate files (no page limit):

| What | Destination |
|------|------------|
| Full algorithm pseudocode (W0–W4, R0–R4) | Supplemental PDF |
| Raw experiment CSVs (`results/run_006/`, `results/run_007/`) | Supplemental ZIP |
| Full 5×5 heatmaps and 3-D surface plots | Supplemental PDF or ZIP |
| `fix_cassandra_py312.py` and setup scripts | Supplemental or Code Ocean |

Supplemental files are uploaded separately in ScholarOne — do **not** embed them in the main PDF.

---

## Step 2: Organize Code and Datasets (Optional but Encouraged)

### Research Data → IEEE DataPort
1. Go to [IEEE DataPort](https://ieee-dataport.org/)
2. Create a dataset entry for the experiment results
3. Upload: `results/run_006/` and `results/run_007/` (CSVs + PNGs)
4. Get the DOI assigned by DataPort
5. Add the DOI to the paper's Data Availability statement before final submission

### Code → Code Ocean
1. Go to [Code Ocean](https://codeocean.com/)
2. Create a compute capsule with:
   - `multi-region-llm/` source tree
   - `requirements.txt` (redis, cassandra-driver, sentence-transformers, anthropic, etc.)
   - `experiments/run_experiment_d.py` as the main entry point
   - Environment: Python 3.12, Docker
3. Link the Code Ocean DOI in the paper's Code Availability statement

---

## Step 3: Create or Update Your Submission Profile

### ScholarOne / IEEE Author Portal Account
- Portal: [https://mc.manuscriptcentral.com/tkde-cs](https://mc.manuscriptcentral.com/tkde-cs)
- Create an account if you don't have one, or log in

### ORCID ID (Required)
- **Your ORCID:** [0009-0008-6285-813X](https://orcid.org/0009-0008-6285-813X)
- Link your ORCID to your ScholarOne profile under **Account → ORCID**
- IEEE requires a verified ORCID for all submitting authors

### Keywords / Reviewer Matching
Update your profile with these keywords (from IEEE Thesaurus):

```
conflict-free replicated data types
context retrieval
distributed systems
large language models
multi-region replication
session management
```

Add secondary keywords for reviewer matching:
```
agent memory
knowledge distillation
database systems
cloud computing
distributed databases
```

---

## Step 4: Submit via the Portal

### 4.1 Log In
Go to: [https://mc.manuscriptcentral.com/tkde-cs](https://mc.manuscriptcentral.com/tkde-cs)  
Click **Author Login** → enter credentials

### 4.2 Start a New Submission
1. On your **Author Dashboard**, click **Start New Submission**
2. Click **Begin Submission**

### 4.3 Select Paper Type
- **Type field:** `Regular Paper`
- **Special Issue field:** Select the exact DK-GenAI Special Issue designation from the dropdown
  - Look for: *"DK-GenAI: Distributed Knowledge for Generative AI"* or similar
  - If not in the dropdown, select the general TKDE track and note the SI in the cover letter

### 4.4 Upload Files

Upload in this order with correct designations:

| File | Designation in System | Notes |
|------|-----------------------|-------|
| `IEEE_TKDE_MultiRegion_LLM_Handoff.pdf` | **Main Document** | PDF only; must include abstract, body, refs, bio |
| `Supplemental_Algorithms.pdf` | Supplemental Material | Algorithm pseudocode, detailed equations |
| `Supplemental_Results.zip` | Supplemental Material | Raw CSVs, all heatmaps, surface plots |
| Cover Letter (see below) | Cover Letter | Plain text or PDF |

> **File size limit:** Total submission ≤ 350 MB

### 4.5 Fill in Manuscript Details

| Field | Value |
|-------|-------|
| Title | Write-Read Co-Design for Cross-Region LLM Agent Session Handoff: An Exhaustive Compatibility Surface Analysis |
| Abstract | Copy from paper (≤ 250 words) |
| Keywords | See Step 3 above |
| Author name | Padmajeet Dashrath Mhaske |
| Affiliation | JPMorgan Chase |
| ORCID | 0009-0008-6285-813X |
| Country | United States |
| Email | shradha.padmajeet@gmail.com |
| Funding | Self-funded (no grant number) |

### 4.6 Co-Authors
- If submitting as sole author, leave co-author section empty
- Check the box confirming all authors have approved the submission

### 4.7 Review Options
- **Double-anonymous review:** Optional — if selected, remove author name/affiliation from the main PDF (leave it only in your ScholarOne profile)
- **Open Access routing:** Choose between Traditional (no APC) or Author-Paid Open Access (APC applies)
- For Traditional: no charge unless the paper exceeds 12 pages

### 4.8 Submit
1. Click through each section, completing all required fields
2. Review the PDF proof generated by ScholarOne
3. Click **Submit** on the final confirmation page
4. Save the **manuscript tracking number** (format: TKDE-YYYY-XXXXXX) — you'll need it for correspondence

---

## Cover Letter Template

```
To the Editors,

We submit "Write-Read Co-Design for Cross-Region LLM Agent Session Handoff:
An Exhaustive Compatibility Surface Analysis" for consideration in the IEEE
Transactions on Knowledge and Data Engineering, DK-GenAI Special Issue.

This paper addresses a fundamental infrastructure gap in multi-region LLM agent
deployment: the interaction between write persistence strategies and context
reconstruction strategies at handoff boundaries. We define five write engines
(W0–W4) and five read engines (R0–R4), exhaustively benchmark all 25 pairings
with a dual-prompt LLM-as-a-Judge protocol (n=100 per cell), and produce the
first 5×5 compatibility surface for cross-region LLM session handoff.

Key findings: (1) The Pareto-optimal pairing (W1+R4, σ_integrity=0.985) is not
predictable from per-layer ablations alone. (2) The read engine is the primary
determinant of session continuity—write engine variation within any read tier
is statistically indistinguishable at n=100. (3) Semantic RAG (R3) is uniquely
write-engine-sensitive: W4+R3=0.942 with real Cassandra vs. W0+R3=0.858.

This work has not been published or submitted elsewhere. The experiment code and
data are available at [Code Ocean DOI] and [IEEE DataPort DOI].

Sincerely,
Padmajeet Dashrath Mhaske
Vice President, AI/ML Platform Architect, JPMorgan Chase
ORCID: 0009-0008-6285-813X
```

---

## Pre-Submission Checklist

- [ ] PDF generated from DOCX, page count verified (≤ 12 pages)
- [ ] Abstract is ≤ 250 words and self-contained
- [ ] All figures have captions and are cited in text (Fig. 1–4)
- [ ] All tables have titles and are cited in text (Tables I–VIII)
- [ ] References are in IEEE format [1]–[14]
- [ ] ORCID linked to ScholarOne account
- [ ] Supplemental files prepared (algorithms PDF, results ZIP)
- [ ] Cover letter written
- [ ] IEEE DataPort dataset DOI obtained (optional but recommended)
- [ ] Code Ocean capsule DOI obtained (optional but recommended)
- [ ] ANTHROPIC_API_KEY not present in any committed file ✅ (already verified)

---

## After Submission

| Timeline | What to Expect |
|----------|---------------|
| Immediately | Confirmation email with tracking number |
| 1–2 weeks | Editor assigns manuscript to Associate Editor |
| 2–4 weeks | Reviewers assigned |
| 6–12 weeks | First decision (Accept / Minor Revision / Major Revision / Reject) |
| Upon revision | Upload revised manuscript with a point-by-point response letter |

Track status at: [https://mc.manuscriptcentral.com/tkde-cs](https://mc.manuscriptcentral.com/tkde-cs) under **Author Dashboard → Submitted Manuscripts**
