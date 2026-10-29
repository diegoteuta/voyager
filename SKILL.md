---
name: hv-scraper
description: "Trigger: scrapear Harinera del Valle, HV, hv.com.co, corpus Bronze/Silver/Gold. Build a robots-compliant layered corpus pipeline."
license: MIT
metadata:
  author: "ingelec2"
  version: "1.0"
---

# HV Corpus Pipeline

## Activation Contract

Load when the task mentions Harinera del Valle, HV, `hv.com.co` or `harineradelvalle.com`, or asks to build, refresh, clean, deduplicate, enrich or validate the corpus under `data/{raw,processed,gold}`. Do not load for unrelated crawling.

## Hard Rules

1. **robots.txt decides.** Fetch `https://www.hv.com.co/robots.txt` before the first page. Never request a URL where `can_fetch(UA, url)` is `False`.
2. **No query strings on HV.** Its robots has `Disallow: /*?`, so every `?` URL is off-limits, including `/wp-json/wp/v2/posts?per_page=`. Crawl clean sitemap URLs only.
3. **Honest identity.** Send `proyecto-ta-corpus/0.1 (+academic; contact: <real email>)`. Never use a browser, `wget` or `HTTrack` user agent: robots block those by name.
4. **Bronze is immutable.** `data/raw/` is never edited by hand. Every fetch appends `{url, fetched_at, status, sha256, bytes}` to `manifest.jsonl`.
5. **Serial and slow.** One request at a time, `delay >= 1.5s`, `timeout = 20s`. On `429`, stop and honor `Retry-After`.
6. **No PII downstream.** Mask emails and phone numbers before Gold, and exclude recruitment/contact-form pages (Ley 1581/2012).
7. **Gold is the only LLM input.** Never feed raw HTML to a model. If a fact is not in `data/gold/`, answer "not in the corpus" instead of guessing.

## Decision Gates

| Source | Tool |
|---|---|
| HV pages (server-rendered WordPress) | `requests` + `trafilatura`; no browser |
| Content that only appears after JS | `playwright`, still robots-checked |
| PDFs under `/wp-content/uploads/` | `docling`, own manifest |
| Video and transcripts | `yt-dlp` + `youtube-transcript-api` |
| Near-duplicate pages | `datasketch` MinHashLSH, Jaccard >= 0.85 |
| RAG chunking | `langchain-text-splitters`, split on headings |

## Execution Steps

Run from the repository root.

1. `uv add requests beautifulsoup4 lxml trafilatura python-frontmatter pydantic datasketch ftfy`
2. Bronze: `uv run .opencode/skills/hv-scraper/assets/bronze_fetch.py --contact you@example.com --out data/raw`
3. Silver: `uv run .opencode/skills/hv-scraper/assets/silver_extract.py --raw data/raw --out data/processed --min-chars 400`
4. Gold: `uv run .opencode/skills/hv-scraper/assets/gold_enrich.py --raw data/raw --silver data/processed --out data/gold`
5. Read `data/gold/report.md`. Fix any reconciliation mismatch before building the RAG.
6. The Streamlit interface reads `data/gold/` only and always renders `source_url`.

## Output Contract

Report, in this order: robots verdict (allowed/blocked), bronze rows by status, silver kept vs dropped (thin, duplicate), gold files and total tokens, and the reconciliation result. Cite file paths; never paste raw HTML.

## References

- `references/site-profile.md` — HV domain, stack, sitemaps, robots traps, measured counts.
- `assets/toolchain.md` — library per source type and its failure mode.
- `assets/*.py` — runnable Bronze, Silver and Gold stages.
