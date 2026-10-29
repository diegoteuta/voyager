# Reference site profile: a WordPress corporate site

Evidence for every rule in `SKILL.md`, measured on the reference site used in this course
(`https://www.hv.com.co`, 2026-10-29). Re-measure before trusting these numbers on another
site; the patterns (unverified sitemaps, wildcard robots, thin policy pages) generalize.

## Domain

- `harineradelvalle.com` answers **301** and redirects to `https://www.hv.com.co/`.
- Canonical host: `www.hv.com.co`. Use it directly; do not keep both hosts in the corpus.

## Stack

- WordPress + Elementor + Yoast SEO + Autoptimize, hosted at Raiola Networks.
- Pages are **server-rendered**: article paragraphs are in the initial HTML (~280 KB per page). A headless browser adds cost and no content, so `playwright` is not part of the default path.
- No e-commerce: no prices, no cart, no product CPT. `/portafolio-de-productos-y-servicios/` is a **supplier application form**, not a catalog.
- `wp-json` types: `post`, `page`, `attachment`, `portfolio`, `elementor_library`, `popup`, plus WP internals.

## Sitemaps (clean URLs, robots-allowed)

| Sitemap | URLs |
|---|---|
| `post-sitemap.xml` | 333 (news, press room) |
| `page-sitemap.xml` | 70 (about, policies, brand pages) |
| `portfolio-sitemap.xml` | projects |
| `category-sitemap.xml` | taxonomy |
| `attachment-sitemap*.xml` | media; skip for a text corpus |

`/sitemap_index.xml` lists all of them. Sitemaps are **not** verified by the CMS: at least one `post-sitemap` entry returns **HTTP 404**, so status filtering in Bronze is mandatory.

## robots.txt traps

```
Disallow: /*?              # every URL with a query string, including the WP REST API with params
Disallow: /*/attachment/
Disallow: /wp-content/plugins/
Disallow: /wp-includes/
Allow:    /wp-content/uploads/*
Disallow: /              # applies to wget, HTTrack, WebCopier, Offline Explorer, ...
```

Consequences:

- The WordPress REST API is reachable and returns JSON, but **every paginated call needs `?per_page=`**, which robots disallows. Do not use it; crawl sitemap URLs instead.
- The user agent string matters: `wget` and `HTTrack` are blocked by name. Use the project UA.
- PDFs under `/wp-content/uploads/` are explicitly allowed, which makes them the one place where a document pipeline is legitimate.

## Content shapes and traps

- ~280 KB HTML per page, dominated by menu, cookie/popup markup and footer.
- The footer repeats a compliance PDF (`Manual_LAFTFPYCST.pdf`) on **every** page. Drop footer links or you will fetch the same PDF hundreds of times.
- Some "policy" pages are thin: their body is an embedded PDF or an image. Gate Silver on `--min-chars` and route those URLs to the PDF pipeline instead.
- Sitemap 404s render a styled error page with the full site chrome (~318 KB). Detect them by status **and** by soft-404 markers in the title.
- High-PII pages: `/envia-tu-hoja-de-vida/` (CV submissions), `/contacto/`, `/linea-etica/`, `/facturacion-electronica-*/`. Exclude them from the corpus; they are forms, not knowledge.

## Suggested scope for the course corpus

1. `sala-de-prensa/noticias/*` — 333 news posts, the bulk of real text.
2. `nosotros/*` and brand pages — policies, history, brands.
3. `portfolio-sitemap.xml` — projects, only if the topic needs them.

## Measured crawl (2026-10-29, sitemap index, project UA)

| Bucket | URLs |
|---|---|
| Allowed and crawlable | 464 |
| Blocked by robots (`/*/attachment/`) | 1808 |
| Excluded (forms, PII) | 8 |
| Rejected for query string | 2 |

Smoke run on 6 news posts: 6 HTTP 200, 5 kept, 1 dropped as thin, 1295 Gold tokens,
all reconciliation checks PASS.

## Pipeline traps found the hard way

- `urllib.robotparser` treats `*` as a literal character. It allows `Disallow: /*?` and
  blocks `Allow: /wp-content/uploads/*`, i.e. it fails in both directions on this exact
  robots file. `bronze_fetch.py` ships an RFC 9309 matcher instead.
- `[class*=cookie]` matches a wrapper that contains ~69% of the page (192 KB of 280 KB).
  Broad attribute selectors delete the article. Only exact Elementor classes are safe.
- `nav` and `header` together carry ~250 KB of mega-menu. Let trafilatura remove them; do
  not pre-strip and then feed it the leftovers.
- Do not require more than `--min-chars 400` by default: policy pages whose body is a PDF
  legitimately fall through to the document pipeline.
