# Toolchain: what to use and when it hurts

| Source | Tool | Why | Failure mode to watch |
|---|---|---|---|
| HV pages (WordPress, server-rendered) | `requests` + `trafilatura` | Content is in the initial HTML; trafilatura drops chrome better than hand-written CSS selectors | Elementor popups leak as body text; strip `[class*=popup]` first |
| JS-only content | `playwright` | Last resort: slower, detectable, heavier | Runs JS without a visible robots check; enforce `can_fetch` before `goto` |
| PDFs (`/wp-content/uploads/*.pdf`) | `docling` | Keeps tables as tables | Scanned PDFs need OCR; the footer repeats one manual on every page, fetch it once |
| Video | `yt-dlp` + `youtube-transcript-api` | Gets subtitles without downloading media | No captions = no corpus; do not transcribe 300 videos in a class session |
| Near-duplicates | `datasketch` MinHashLSH | O(n) instead of O(n²) pairwise comparison | Threshold 0.85 on 5-word shingles; lower it and you delete real news |
| Chunking for RAG (Módulo 2) | `langchain-text-splitters` | Splits on headings, keeps tables intact | Chunking before dedup produces duplicated chunks with different ids |
| Encoding damage | `ftfy` | Fixes mojibake (`Ã³` → `ó`) | Apply once, after extraction, never before |
| Metadata | `pydantic` + `python-frontmatter` | Frontmatter is validated, not hoped for | A missing `source_url` breaks citation and cannot be recovered later |

## Non-tools

- **No Selenium for HV.** It adds a browser to a site that already ships its text.
- **No `wp-json` with query strings.** `Disallow: /*?` makes it non-compliant even though it returns JSON.
- **No pandas before Gold.** pandas is for analysis; using it as a cleaning layer hides which row lost which field.
