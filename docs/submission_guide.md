# Platform Submission Guide

This guide explains how to submit your people search platform's results to the People Search Bench leaderboard.

## Step 1: Get the Benchmark Queries

All benchmark queries are in `data/queries/` as JSONL files. Each line is a JSON object:

```json
{"query_id": "rec_0001", "prompt": "Find backend developers in London with experience in microservices architecture", "category": "recruiting"}
```

Run each query through your platform and collect the results.

## Step 2: Format Your Results

Create a CSV file for each category with these columns:

| Column | Required | Description |
|--------|----------|-------------|
| `query_id` | Yes | Must match the query_id from the benchmark queries |
| `agent_name` | Yes | Your platform name (lowercase, e.g., `myplatform`) |
| `name` | Yes | Person's full name |
| `title` | No | Job title |
| `company` | No | Current company |
| `location` | No | Location |
| `linkedin_url` | No | LinkedIn profile URL |
| `email` | No | Email address |
| `bio` | No | Brief biography or summary |
| `person_data` | Yes | Full raw data returned by your platform (JSON string or free text) |

One row = one person. A single query typically returns multiple rows.

## Step 3: Submit a Pull Request

1. Place your CSV files in `data/results/<your_platform_name>/`
2. Open a PR with a brief description of your platform
3. We will run the standard evaluation pipeline and add your results to the leaderboard

## Notes

- Aim for up to 15 results per query for fair comparison
- Include as much structured data as your platform provides
- The `person_data` column should contain the complete raw output from your platform
- Do not fabricate or manually curate results — the benchmark measures real platform performance
