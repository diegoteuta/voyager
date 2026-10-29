# hv-scraper

A layered, robots-compliant corpus pipeline for [Harinera del Valle](https://www.hv.com.co)
(`hv.com.co`), packaged as an agent skill.

Bronze keeps the raw HTML and an append-only manifest. Silver strips chrome, normalizes text
and removes near-duplicates. Gold is validated Markdown with frontmatter — the only layer an
LLM is allowed to read.

```text
data/raw/        immutable HTML + manifest.jsonl (url, fetched_at, status, sha256)
data/processed/  clean text, deduplicated
data/gold/       Markdown + YAML frontmatter + reconciliation report
```

## Install

```bash
npx skills add diegoteuta/hv-scraper
```

Then ask your agent to build or refresh the HV corpus. The skill loads on mentions of
Harinera del Valle, HV, `hv.com.co` or `data/{raw,processed,gold}`.

## What it enforces

- `robots.txt` is checked for the exact URL and user agent before every request.
- `Disallow: /*?` is honored, so the WordPress REST API with query parameters is off-limits
  even though it answers with JSON.
- An honest user agent is mandatory: `wget` and `HTTrack` are blocked by name on this site.
- Serial requests with a >= 1.5 s delay, 20 s timeout, and a hard stop on `429`.
- No personal data reaches Gold (Ley 1581/2012).
- Answers must cite `source_url`; anything absent from Gold is reported as absent.

## Why the code looks like this

Two defects are easy to ship silently on this site, and both produce an empty corpus without
raising an exception:

1. `urllib.robotparser` treats `*` as a literal character. On HV's robots file that means it
   allows `Disallow: /*?` URLs and blocks `Allow: /wp-content/uploads/*` — wrong in both
   directions. `assets/bronze_fetch.py` ships an RFC 9309 matcher instead.
2. Broad CSS attribute selectors delete the article. `[class*=cookie]` matches a page wrapper
   holding 69% of the HTML; combined with `nav` it leaves trafilatura with nothing. Pass the
   raw HTML to trafilatura and use BeautifulSoup only as a fallback.

`references/site-profile.md` documents the sitemaps, the robots traps and the measured URL
counts. `assets/toolchain.md` maps each source type (HTML, PDF, video) to the library that
fits and its failure mode.

## Requirements

Python 3.14 and [`uv`](https://docs.astral.sh/uv/):

```bash
uv add requests beautifulsoup4 lxml trafilatura python-frontmatter pydantic datasketch ftfy
```

## Layout

```text
SKILL.md                 activation contract, hard rules, decision gates
references/site-profile.md
assets/bronze_fetch.py
assets/silver_extract.py
assets/gold_enrich.py
assets/toolchain.md
```

## License

MIT
