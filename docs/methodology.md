# Evaluation Methodology

## Overview

People Search Bench evaluates AI-powered people search platforms using **Criteria-Grounded Verification** — a factual decomposition approach that breaks evaluation into verifiable yes/no judgments rather than subjective quality scores.

Each platform is scored on three independently computed dimensions (0–100 scale):

| Dimension | Question Answered | Core Metric |
|-----------|-------------------|-------------|
| **Relevance Precision** | Are the returned people correct and well-ranked? | Padded nDCG@10 |
| **Effective Coverage** | How many correct people were found? | TCR × mean yield |
| **Information Utility** | Is the returned data actionable? | (Structural + Evidence + Actionability) / 3 |
| **Overall** | Combined score | Equal-weight average of all three |

---

## 1. Criteria-Grounded Verification

Unlike traditional LLM-as-Judge approaches that assign subjective quality scores, we decompose evaluation into **verifiable factual judgments**.

### Step 1: Criteria Extraction

For each query, an LLM extracts N explicit, checkable conditions from the search intent:

```
Query: "Find senior ML engineers at Google in Bay Area"
Criteria:
  c1: Role is Senior ML Engineer or equivalent
  c2: Currently employed at Google
  c3: Located in San Francisco Bay Area
```

### Step 2: Per-Person Verification

Each returned person is verified against every criterion using **web search evidence** (Tavily API):

```
Person: Jane Doe
  c1: met          (LinkedIn: "Staff ML Engineer at Google")
  c2: met          (confirmed via Google Research page)
  c3: not_met      (location: New York, NY)
  → relevance_grade = 2/3 = 0.67
```

Each criterion receives a three-level judgment:
- **met** (1.0) — criterion fully satisfied with evidence
- **partially_met** (0.5) — criterion partially satisfied
- **not_met** (0.0) — criterion not satisfied

### Why This Approach

| Aspect | Traditional LLM-as-Judge | Criteria-Grounded Verification |
|--------|--------------------------|-------------------------------|
| Judgment type | Subjective quality score | Factual yes/no per criterion |
| Evidence source | LLM parametric knowledge | External web search |
| Reproducibility | Low (prompt-sensitive) | High (criteria are explicit) |
| Bias risk | High (style, length bias) | Low (binary factual checks) |

---

## 2. Relevance Precision (Padded nDCG@10)

Measures whether the returned people match the query and are well-ranked.

### Computation

1. **Relevance grade** for person _i_:

   `rel(pᵢ) = Σ score(cⱼ, pᵢ) / N`

   where score is 1.0 (met), 0.5 (partially_met), or 0.0 (not_met).

2. **Discounted Cumulative Gain**:

   `DCG@K = Σᵢ₌₁ᴷ rel(pᵢ) / log₂(i+1)`

3. **Padded Ideal DCG** — the ideal DCG always assumes K=10 perfectly relevant results are achievable:

   `IDCG@K = Σᵢ₌₁¹⁰ 1.0 / log₂(i+1)`

   This prevents platforms returning few-but-perfect results from scoring 1.0. A platform that returns only 3 perfect people scores lower than one returning 10.

4. **Padded nDCG@10**:

   `nDCG@10 = DCG@10 / IDCG@10`

5. **Platform score**:

   `Relevance Precision = mean(nDCG@10 across all queries) × 100`

### Why nDCG

nDCG (Normalized Discounted Cumulative Gain) is the standard ranking quality metric in Information Retrieval, used by TREC, SIGIR, and search engines like Google and Bing (Järvelin & Kekäläinen, 2002).

### Why Padded nDCG

Standard nDCG normalizes against the actual returned results, so a platform returning 3 people all perfectly relevant scores 1.0 — the same as a platform returning 15 people all perfectly relevant. Padded nDCG fixes this by always assuming 10 perfect results are achievable, ensuring high recall is rewarded.

> Implementation: `benchmark/metrics.py` → `_ndcg()`

---

## 3. Effective Coverage

Measures how many correct people the platform found per query.

### Computation

1. **Qualified result**: a person with `relevance_grade ≥ 0.5` (matches at least half the criteria).

2. **Task success**: 1 if at least one qualified result, 0 otherwise.

3. **Yield per query**:

   `yield(q) = min(qualified_count(q) / K, 1.0)`

4. **Platform score**:

   `Task Completion Rate (TCR) = count(task_success=1) / total_queries × 100`

   `Effective Coverage = TCR × mean(yield) × 100`

### Difference from Relevance Precision

- **Relevance Precision** is a *rate* (hit rate) — how good are the results you returned?
- **Effective Coverage** is a *volume* metric — how many good results did you find?

A platform returning 5 people all perfect scores high on Precision but low on Coverage. A platform returning 25 people with 20 qualified scores high on both.

### Reported Sub-Metrics

| Metric | Description |
|--------|-------------|
| Effective Coverage (0–100) | Combined score |
| Task Completion Rate (%) | Queries with ≥1 qualified result |
| Mean Qualified Results | Average qualified people per query |

> Implementation: `benchmark/metrics.py` → `compute_query_metrics()`

---

## 4. Information Utility

Measures whether the returned person data is actionable without manual verification.

### Three Sub-Dimensions (LLM-Assessed)

An LLM evaluates each person's raw result data on three aspects:

1. **Profile Completeness** (structural) — How rich is the person's data? Name, title, company, contact info, work history, education, etc.

2. **Query-Specific Evidence** (evidence_quality) — Does the result include specific proof showing *why* this person matches the query? Look for: per-criterion match explanations, verification sources, data provenance.

3. **Actionability** — Can the user take next steps (contact, shortlist, outreach) based on this data alone, without additional research?

### Computation

Each sub-dimension is scored 0.0–1.0 by the LLM:

`utility(pᵢ) = (structural + evidence_quality + actionability) / 3`

`Information Utility = mean(utility across all persons in all queries) × 100`

> Implementation: `benchmark/evaluators/criteria_evaluator.py`

---

### Fairness Considerations

The **Query-Specific Evidence** sub-dimension rewards platforms that provide per-result match explanations showing *why* a person matches the query. Platforms with built-in verification pipelines (e.g., Lessie's checkpoint system) naturally produce this evidence, while platforms returning raw profile data without explanations score lower on this dimension.

This is an intentional design choice: from the user's perspective, a result that explains *why* it matches is more useful than one that doesn't. However, we acknowledge this rewards platform architecture, not just search quality. The equal-weight averaging (1/3 per sub-dimension) ensures that evidence quality is only one of three factors in Utility, and Utility itself is only one of three factors in the Overall score.

---

## 5. Overall Score

`Overall = (Relevance Precision + Effective Coverage + Information Utility) / 3`

Equal-weight averaging follows the Multi-Criteria Decision Analysis (MCDA) principle that equal weights perform as well as optimized weights in most multi-attribute decisions (Dawes & Corrigan, 1974).

---

## 6. Evaluation Setup

| Parameter | Value |
|-----------|-------|
| Total queries | 119 |
| Categories | 4 (Recruiting, B2B, Expert/Deterministic, Influencer/KOL) |
| Max results per query | 15 |
| Evaluation LLM | Gemini 3.1 Flash Lite (via OpenRouter) |
| Web verification | Tavily Advanced Search API |
| Platforms evaluated | Lessie, Exa, Juicebox (PeopleGPT), Claude Code |

---

## 7. References

1. Järvelin, K. & Kekäläinen, J. (2002). Cumulated gain-based evaluation of IR techniques. *ACM TOIS*, 20(4), 422–446.
2. Zheng, L. et al. (2023). Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena. *NeurIPS 2023*.
3. Shankar, V. et al. (2024). Who Validates the Validators? Aligning LLM-Assisted Evaluation with Human Preferences. *arXiv:2404.12272*.
4. Kim, S. et al. (2024). Prometheus 2: An Open Source Language Model Specialized in Evaluating Other Language Models. *arXiv:2405.01535*.
5. Dawes, R. M. & Corrigan, B. (1974). Linear models in decision making. *Psychological Bulletin*, 81(2), 95–106.
