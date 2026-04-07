<h1 align="center">People Search Bench</h1>

<p align="center">
  An open benchmark for evaluating AI-powered people search agents
</p>

<p align="center">
  <a href="https://arxiv.org/abs/2603.27476"><img src="https://img.shields.io/badge/arXiv-2603.27476-b31b1b" alt="arXiv"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow" alt="License"></a>
</p>

<p align="center">
  <a href="#leaderboard">Leaderboard</a> •
  <a href="#methodology">Methodology</a> •
  <a href="#case-studies">Case Studies</a> •
  <a href="#data--reproducibility">Reproducibility</a>
</p>

---

People Search Bench evaluates how well AI platforms can find real people matching natural language queries. It scores platforms across three dimensions — **Relevance Precision**, **Effective Coverage**, and **Information Utility** — using Criteria-Grounded Verification with web-based fact-checking. See our [paper](https://arxiv.org/abs/2603.27476) for full details.

## Leaderboard

119 queries across 4 categories. All scores on a 0–100 scale.

<p align="center">
  <img src="assets/radar-chart.png" alt="Radar chart comparing platform scores" width="800"/>
</p>

| Platform | Relevance Precision | Effective Coverage | Information Utility | Overall |
|----------|:-------------------:|:------------------:|:-------------------:|:-------:|
| Lessie | 70.2 | 69.1 | 56.4 | 65.2 |
| Exa | 53.8 | 58.1 | 53.1 | 55.0 |
| Claude Code | 54.3 | 41.1 | 42.7 | 46.0 |
| Juicebox (PeopleGPT) | 44.7 | 41.8 | 50.9 | 45.8 |

**Platform notes:**
- **Juicebox** is a specialized recruiting platform (800M+ profiles). It ranks #2 in Recruiting with the highest Coverage (75.3) and Utility (55.8) in that category. Lower scores on Expert and KOL queries reflect its recruiting-focused design.
- **Claude Code** is a general-purpose AI agent, not a specialized people search tool. It achieves reasonable Relevance Precision but lower Coverage — it finds fewer people per query.
- Relevance Precision uses **padded nDCG@10**: the ideal DCG always assumes 10 perfectly relevant results, so platforms returning fewer results are penalized.

<details>
<summary><b>How scores are computed</b></summary>

Each dimension produces a 0–100 score using the [Criteria-Grounded Verification](#methodology) pipeline:

- **Relevance Precision (padded nDCG@10)**: The LLM extracts checkable criteria from each query. Each returned person is verified against these criteria via web search, producing a relevance grade (0.0–1.0). The ideal DCG always assumes 10 perfectly relevant results are achievable, so a platform returning only 3 perfect results scores lower than one returning 10.

- **Effective Coverage**: Counts qualified results (relevance_grade >= 0.5) per query, combined with task completion rate. Formula: `TCR × mean(min(qualified_count / K, 1.0)) × 100`.

- **Information Utility**: Three equally weighted sub-scores: (1) **Profile Completeness** — richness of person data; (2) **Query-Specific Evidence** — per-criterion verification and source links; (3) **Actionability** — can the user take next steps from this data alone. Formula: `(completeness + evidence + actionability) / 3`.

- **Overall**: Equal-weight average of all three dimensions (Dawes, 1979).

</details>

<details>
<summary><b>Results by scenario</b></summary>

#### Overall by Scenario

| Scenario | Queries | Lessie | Exa | Juicebox | Claude Code |
|----------|:-------:|:------:|:---:|:--------:|:-----------:|
| Recruiting | 30 | 68.2 | 64.7 | 65.7 | 50.5 |
| B2B Prospecting | 32 | 60.6 | 55.2 | 51.4 | 43.0 |
| Expert / Deterministic | 28 | 70.4 | 61.2 | 44.2 | 57.0 |
| Influencer / KOL | 29 | 62.3 | 41.6 | 31.1 | 43.2 |

#### Relevance Precision (padded nDCG@10)

| Scenario | Lessie | Exa | Juicebox | Claude Code |
|----------|:------:|:---:|:--------:|:-----------:|
| Recruiting | 74.8 | 66.2 | 66.1 | 59.0 |
| B2B Prospecting | 62.8 | 50.0 | 46.1 | 43.0 |
| Expert / Deterministic | 79.0 | 61.6 | 39.0 | 69.6 |
| Influencer / KOL | 65.2 | 37.4 | 26.6 | 46.9 |

#### Effective Coverage

| Scenario | Lessie | Exa | Juicebox | Claude Code |
|----------|:------:|:---:|:--------:|:-----------:|
| Recruiting | 75.6 | 73.8 | 75.3 | 46.7 |
| B2B Prospecting | 63.5 | 58.5 | 52.7 | 42.3 |
| Expert / Deterministic | 75.2 | 69.0 | 46.9 | 62.9 |
| Influencer / KOL | 62.8 | 39.3 | 22.8 | 39.3 |

#### Information Utility

| Scenario | Lessie | Exa | Juicebox | Claude Code |
|----------|:------:|:---:|:--------:|:-----------:|
| Recruiting | 54.3 | 54.0 | 55.8 | 45.8 |
| B2B Prospecting | 55.5 | 57.0 | 55.4 | 43.6 |
| Expert / Deterministic | 57.1 | 52.9 | 46.8 | 38.5 |
| Influencer / KOL | 58.9 | 48.0 | 44.0 | 43.4 |

</details>

## Methodology

Every score is backed by **verifiable web evidence**, not subjective LLM judgments.

```
Query ──→ Extract Criteria ──→ Verify via Web ──→ Grade ──→ Aggregate
         (N checkable items)    (Tavily API)      (0/0.5/1)   (nDCG + Coverage + Utility)
```

**Example:**
> **Query:** "Find senior ML engineers at Google in Bay Area"
> **Criteria:** (1) Senior ML Engineer (2) At Google (3) Bay Area
> **Jane Doe:** (1) pass (2) pass (3) fail → **relevance_grade = 2/3 = 0.67**

### Scoring

| Metric | Formula | Description |
|:-------|:--------|:------------|
| **Relevance Precision** | `padded nDCG@10` | Quality and ranking. Ideal DCG assumes 10 perfect results — returning fewer results scores lower. |
| **Effective Coverage** | `TCR × mean(min(qualified / K, 1.0)) × 100` | Qualified results (grade >= 0.5) combined with task completion rate |
| **Information Utility** | `(completeness + evidence + actionability) / 3` | Profile richness + match explanations + immediate actionability |
| **Overall** | `avg(Relevance, Coverage, Utility)` | Equal-weight average of all three dimensions |

### Why not LLM-as-Judge?

| Issue | Traditional LLM-as-Judge | Our Approach |
|:------|:-------------------------|:-------------|
| **Subjectivity** | Vague quality scores | Binary factual checks |
| **Evidence** | Stale parametric knowledge | Live web verification |
| **Reproducibility** | Prompt-sensitive | Explicit, fixed criteria |
| **Bias** | Style/length bias | Verifiable facts only |

### Query Categories

| Category | Queries | Description | Example |
|----------|:-------:|-------------|---------|
| **Recruiting** | 30 | Candidates with specific skills, experience, location | "Find backend developers in London with microservices experience" |
| **B2B Prospecting** | 32 | Decision-makers at target companies | "Find corporate innovation leaders in Europe at large enterprises" |
| **Expert / Deterministic** | 28 | Queries with verifiable answers or specific domain experts | "Find all co-founders of Together AI" |
| **Influencer / KOL** | 29 | Content creators and opinion leaders | "Find AI KOLs with 10K+ followers on Twitter" |

The benchmark includes queries in English, Portuguese, Spanish, and Dutch. The full query set is in [`data/queries/`](data/queries/).

### Platforms Evaluated

| Platform | Type | Data Sources |
|----------|------|-------------|
| [Lessie](https://lessie.ai) | AI Agent | Multi-source (web, social, professional, academic) |
| [Exa](https://exa.ai) | Search API | Structured entity database |
| [Juicebox (PeopleGPT)](https://juicebox.ai) | AI Recruiting | 800M+ profiles, 60+ sources |
| [Claude Code](https://claude.ai) | General AI Agent | Web search |

## Case Studies

Supplementary examples evaluated independently from the 119-query benchmark dataset, included to illustrate qualitative differences across challenging, cross-domain queries.

<details>
<summary><b>Case 1: Rising Stars in LLM Safety & Alignment</b> — Academic + Publication Cross-Reference</summary>

**Query**: *"Who are the rising stars in the large language model safety and alignment field? I want people who started publishing after 2021 and already have 3+ first-author papers at top venues."*

Requires cross-referencing publication databases with career profiles.

| Platform | Relevance | Coverage | Utility | Qualified |
|----------|:---------:|:--------:|:-------:|:---------:|
| Lessie | 100.0 | 100.0 | 28.9 | 15/15 |
| Claude Code | 79.6 | 73.3 | 52.5 | 11/12 |
| Juicebox | 71.7 | 86.7 | 54.0 | 13/15 |
| Exa | 65.1 | 93.3 | 42.7 | 14/15 |

</details>

<details>
<summary><b>Case 2: Brazilian Beauty Micro-Influencers on Instagram</b> — 5-Constraint Social Search</summary>

**Query**: *"Brazilian beauty niche influencers who talk about hair, hair loss, etc... with between 5k to 30k followers on Instagram, and who have a highly engaged audience"*

5 simultaneous constraints: geography + platform + niche + follower range + engagement quality.

| Platform | Relevance | Coverage | Utility | Qualified |
|----------|:---------:|:--------:|:-------:|:---------:|
| Lessie | 99.1 | 100.0 | 33.3 | 15/15 |
| Exa | 67.0 | 86.7 | 39.8 | 13/15 |
| Claude Code | 59.7 | 46.7 | 23.3 | 7/7 |
| Juicebox | 22.8 | 6.7 | 25.8 | 1/15 |

</details>

<details>
<summary><b>Case 3: Tsinghua Grads in Bay Area AI</b> — Education + Geography + Industry</summary>

**Query**: *"Find me top AI developers in Bay Area, and graduated from Tsinghua University after 2010"*

4 constraints: geography + profession + education + temporal.

| Platform | Relevance | Coverage | Utility | Qualified |
|----------|:---------:|:--------:|:-------:|:---------:|
| Lessie | 97.8 | 100.0 | 29.6 | 15/15 |
| Claude Code | 78.6 | 46.7 | 1.0 | 7/7 |
| Juicebox | 76.2 | 93.3 | 33.3 | 14/15 |
| Exa | 69.0 | 80.0 | 33.3 | 12/15 |

</details>

<details>
<summary><b>Case 4: AI Agent Startup Founders (2025 Funded)</b> — Funding Data + Founder Profiles</summary>

**Query**: *"Map the key people behind the top AI agent startups funded in 2025. For each company give me the founding team, their backgrounds, and any shared alumni networks."*

Requires synthesis of venture funding data + company databases + founder profiles.

| Platform | Relevance | Coverage | Utility | Qualified |
|----------|:---------:|:--------:|:-------:|:---------:|
| Claude Code | 92.5 | 100.0 | 30.2 | 15/15 |
| Lessie | 78.9 | 100.0 | 66.0 | 15/15 |
| Exa | 69.5 | 86.7 | 51.6 | 13/15 |
| Juicebox | 52.5 | 60.0 | 49.1 | 9/15 |

</details>

<details>
<summary><b>Case 5: Agricultural Scientists in Africa</b> — Non-LinkedIn Domain</summary>

**Query**: *"Find agricultural scientists in Africa working on food security, crop science, or sustainable farming"*

Tests coverage where most professionals are indexed in institutional databases, not LinkedIn.

| Platform | Relevance | Coverage | Utility | Qualified |
|----------|:---------:|:--------:|:-------:|:---------:|
| Exa | 97.6 | 100.0 | 61.8 | 15/15 |
| Claude Code | 96.8 | 80.0 | 13.6 | 12/12 |
| Juicebox | 94.8 | 100.0 | 66.4 | 15/15 |
| Lessie | 93.4 | 100.0 | 33.3 | 15/15 |

</details>

<details>
<summary><b>Case 6: NLP Academics Turned Industry Practitioners</b> — Cross-Profile Identity</summary>

**Query**: *"Find people who have both a strong academic publication record in NLP and also hold senior engineering positions at tech companies."*

Requires matching two distinct professional identities.

| Platform | Relevance | Coverage | Utility | Qualified |
|----------|:---------:|:--------:|:-------:|:---------:|
| Juicebox | 100.0 | 100.0 | 33.3 | 15/15 |
| Lessie | 95.6 | 100.0 | 33.1 | 15/15 |
| Claude Code | 92.6 | 100.0 | 24.9 | 15/15 |
| Exa | 73.8 | 86.7 | 33.3 | 13/15 |

</details>

<details>
<summary><b>Case 7: Google DeepMind Talent Flow</b> — Temporal Career Intelligence</summary>

**Query**: *"Find engineers who recently mass-departed from Google DeepMind in the last 6 months and identify where they went."*

Tests temporal career change detection.

| Platform | Relevance | Coverage | Utility | Qualified |
|----------|:---------:|:--------:|:-------:|:---------:|
| Lessie | 100.0 | 100.0 | 60.2 | 15/15 |
| Claude Code | 92.3 | 86.7 | 22.6 | 13/13 |
| Juicebox | 44.4 | 66.7 | 34.4 | 10/15 |
| Exa | 37.8 | 73.3 | 34.4 | 11/15 |

</details>

<details>
<summary><b>Case 8: UK Film Prop Companies Needing CNC Services</b> — Niche B2B Prospecting</summary>

**Query**: *"Find me UK film prop or event prop companies who would require an outsourced CNC service"*

Hyper-specific niche B2B query with an inferred need.

| Platform | Relevance | Coverage | Utility | Qualified |
|----------|:---------:|:--------:|:-------:|:---------:|
| Lessie | 87.5 | 100.0 | 56.9 | 15/15 |
| Juicebox | 66.7 | 60.0 | 52.2 | 9/15 |
| Exa | 53.7 | 66.7 | 56.0 | 10/15 |
| Claude Code | 19.3 | 6.7 | 0.0 | 1/1 |

</details>

## Data & Reproducibility

**What's in this repository:**
- Benchmark queries (`data/queries/`) — all search prompts used in the evaluation
- Evaluation methodology — scoring formulas, criteria extraction, and aggregation logic
- Aggregated platform scores — verifiable against the methodology

**What's NOT in this repository:**
Raw search results and per-person evaluations are excluded for privacy and compliance reasons.

**How the benchmark works:**
1. Run each query on each platform, collect returned people into CSV files.
2. Run the Criteria-Grounded Verification pipeline — extract criteria, verify via web search, compute relevance grades.
3. Aggregate per-person grades into platform-level scores using nDCG@K, Effective Coverage, and Information Utility.

## Citation

```bibtex
@misc{lessieai2026peoplesearchbench,
  title={People Search Bench: A Benchmark for Evaluating AI-Powered People Search Agents},
  author={LessieAI},
  year={2026},
  eprint={2603.27476},
  archivePrefix={arXiv},
  url={https://arxiv.org/abs/2603.27476}
}
```

## Disclosure

This benchmark was designed and maintained by [LessieAI](https://lessie.ai), which is also one of the evaluated platforms. To mitigate potential bias:

- All evaluation code and query definitions are open-source and auditable.
- Scoring uses external web verification (Tavily API), not LLM parametric knowledge.
- The same pipeline and LLM model are applied identically to all platforms.
- Results are published alongside the methodology for independent verification.

We welcome third-party reproductions and encourage other platforms to [submit their results](docs/submission_guide.md) for evaluation.

## Acknowledgments

- Evaluation methodology grounded in [MT-Bench](https://arxiv.org/abs/2306.05685) (Zheng et al., 2023), nDCG (Jarvelin & Kekalainen, 2002), and MCDA (Dawes, 1979)
- Web verification powered by [Tavily](https://tavily.com) -- LLM evaluation via [OpenRouter](https://openrouter.ai)
