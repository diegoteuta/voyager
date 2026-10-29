# public-corpus-pipeline

A layered, robots-compliant corpus pipeline for public web sources, packaged as an agent
skill. Bronze keeps the raw HTML and an append-only manifest. Silver strips chrome,
normalizes text and removes near-duplicates. Gold is validated Markdown with frontmatter —
the only layer an LLM is allowed to read.

```text
data/raw/        immutable HTML + manifest.jsonl (url, fetched_at, status, sha256)
data/processed/  clean text, deduplicated
data/gold/       Markdown + YAML frontmatter + reconciliation report
```

## Install

```bash
npx skills add diegoteuta/public-corpus-pipeline
```

Then ask your agent to build or refresh a corpus. The skill loads on mentions of corpus
pipelines, Bronze/Silver/Gold, RAG datasets, robots.txt or public-source extraction.

## What it enforces

- `robots.txt` is checked for the exact URL and user agent before every request.
- Disallowed query strings stay disallowed: if the site blocks `/*?`, its JSON API with
  parameters is off-limits even though it answers.
- An honest user agent is mandatory; `wget` and `HTTrack` are blocked by name on many sites.
- Serial requests with a >= 1.5 s delay, 20 s timeout, hard stop on `429`.
- No personal data reaches Gold; forms, CVs and ethics hotlines are excluded.
- Answers must cite `source_url`; anything absent from Gold is reported as absent.

## Why the code looks like this

Two defects ship silently and produce an empty corpus without raising an exception:

1. `urllib.robotparser` treats `*` as a literal character. On robots files that use
   `Disallow: /*?` or `Allow: /wp-content/uploads/*` it fails in **both** directions.
   `assets/bronze_fetch.py` ships an RFC 9309 matcher instead.
2. Broad CSS attribute selectors delete the article. `[class*=cookie]` can match a page
   wrapper holding most of the HTML; combined with `nav` it leaves trafilatura with nothing.
   Pass raw HTML to trafilatura and use BeautifulSoup only as a fallback.

`references/site-profile.md` documents a WordPress site measured end to end: sitemaps,
robots traps, thin pages, and the measured URL counts. `assets/toolchain.md` maps each
source type (HTML, PDF, video) to the library that fits and its failure mode.

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
