---
name: public-corpus-pipeline
description: "Trigger: web scraping corpus, Bronze/Silver/Gold, RAG dataset, robots.txt, public sources. Build a robots-compliant layered corpus pipeline."
license: MIT
metadata:
  author: "diegoteuta"
  version: "1.1"
---

# Public Corpus Pipeline

## Activation Contract

Load when the task is to build, refresh, clean, deduplicate, enrich or validate a corpus of
public web sources under `data/{raw,processed,gold}`, or when a model needs a citable
knowledge base instead of raw HTML. Not for fetching a single page.

## Hard Rules

1. **robots.txt decides.** Fetch `<site>/robots.txt` before the first page and evaluate
   `can_fetch(UA, url)` per URL. Never request a disallowed path.
2. **Honor what robots blocks.** If the site disallows query strings (`Disallow: /*?`), never
   call an API that needs `?per_page=`: crawl the sitemaps instead.
3. **Honest identity.** Send `proyecto-ta-corpus/0.1 (+academic; contact: <real email>)`.
   Never use a browser, `wget` or `HTTrack` user agent: many robots block those by name.
4. **Bronze is immutable.** `data/raw/` is never edited by hand. Every fetch appends
   `{url, fetched_at, status, sha256, bytes}` to `manifest.jsonl`, including failures.
5. **Serial and slow.** One request at a time, `delay >= 1.5s`, `timeout = 20s`. On `429`,
   stop the run and honor `Retry-After`.
6. **No PII downstream.** Mask emails and phone numbers before Gold, and exclude forms,
   job applications and ethics hotlines (Ley 1581/2012 in Colombia).
7. **Gold is the only LLM input.** Never feed raw HTML to a model. If a fact is not in
   `data/gold/`, answer "not in the corpus" instead of guessing.

## Decision Gates

| Source | Tool |
|---|---|
| Server-rendered HTML (WordPress, static sites) | `requests` + `trafilatura`; no browser |
| Content that only appears after JS | `playwright`, still robots-checked |
| PDFs | `docling`, own manifest |
| Video and transcripts | `yt-dlp` + `youtube-transcript-api` |
| Near-duplicate pages | `datasketch` MinHashLSH, Jaccard >= 0.85 |
| RAG chunking | `langchain-text-splitters`, split on headings |

## Execution Steps

Run from the repository that will hold the corpus. Scripts live in this skill's directory.

1. `uv add requests beautifulsoup4 lxml trafilatura python-frontmatter pydantic datasketch ftfy`
2. Bronze: `uv run assets/bronze_fetch.py --site https://example.com --contact you@example.com --out data/raw`
3. Silver: `uv run assets/silver_extract.py --raw data/raw --out data/processed --min-chars 400`
4. Gold: `uv run assets/gold_enrich.py --raw data/raw --silver data/processed --out data/gold`
5. Read `data/gold/report.md`. Fix any reconciliation mismatch before building the RAG.
6. The UI reads `data/gold/` only and always renders `source_url`.

## Output Contract

Report, in this order: robots verdict (allowed/blocked), bronze rows by status, silver kept
vs dropped (thin, duplicate), gold files and total tokens, and the reconciliation result.
Cite file paths; never paste raw HTML.

## References

- `references/site-profile.md` — worked example: a WordPress site measured end to end, with
  its sitemaps, robots traps and pipeline failures worth copying.
- `assets/toolchain.md` — library per source type and its failure mode.
- `assets/*.py` — runnable Bronze, Silver and Gold stages.
