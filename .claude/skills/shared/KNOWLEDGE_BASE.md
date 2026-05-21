# Shared — Build Product Knowledge Base

Builds the changelog + documentation knowledge base used by the
detect-completed phase. Used by the detect-completed skill (standalone) and
by the orchestrator (Phase 0 prep when Completed is selected).

---

## Step KB-1 — Get the changelog

Construct the URL:

`https://woocommerce.com/wp-json/wccom/changelog/1.0/product/<id>`

Fetch using `curl -fsSL <url>` via Bash (not WebFetch) so the full raw text
is returned without summarisation. The response is plain text — no JSON
parsing needed.

If the URL fails or returns empty content, ask the user to provide the
changelog as either a URL (e.g. a GitHub raw `readme.txt` or `CHANGELOG.md`)
or pasted text, then use it directly.

Parse into version entries with:
- Version number
- Release date (or "date unknown")
- List of individual changes

---

## Step KB-2 — Crawl the documentation

### KB-2a — Find the main docs URL

Derive from the product slug. Try in order, stopping at the first 200 OK:

1. `https://woocommerce.com/document/<slug>/`
2. `https://woocommerce.com/document/<slug-without-leading-"woocommerce-">/`
   (e.g. `woocommerce-subscriptions` → `subscriptions`)
3. Fetch `https://woocommerce.com/products/<slug>/` with `curl -fsSL` and
   find an anchor whose `href` starts with `https://woocommerce.com/document/`.
   Use the first match.
4. If all three fail: skip docs crawl, note it in the final report.

### KB-2b — Crawl linked sub-pages

From the main docs page, extract `href` values that:
- Start with `https://woocommerce.com/document/`
- Share the same first path segment as the main docs URL

Fetch each sub-page with `curl -fsSL`. Cap at **20 sub-pages**. Fetch
sequentially.

### KB-2c — Extract features

From all fetched pages (main + sub-pages), extract a list of features and
capabilities: named features, options/settings/modes, integration points.
Strip navigation, footer, boilerplate.

---

## Step KB-3 — Assemble

Combine into a single feature knowledge base:

- Changelog entries — tagged with version + date (source: `changelog`)
- Doc capabilities — tagged with page URL (source: `docs`)

Deduplicate overlap. Record the **latest version** (top of changelog) as
`[latest_version]` for use in docs-sourced comment templates.

Print:
```
Knowledge base ready: [N] changelog entries · [M] doc features from [P] pages crawled.
```

---

## Output shape (when invoked by orchestrator)

Write JSON to `.triage-state/<id>/knowledge_base.json`:

```json
{
  "latest_version": "8.7.1",
  "changelog": [{"version": "...", "date": "...", "changes": ["..."]}],
  "docs": [{"url": "...", "features": ["..."]}]
}
```

---

## Docs source rule (carried into detect-completed)

A docs-sourced match may only cite a URL that was actually fetched here and
returned HTTP 200. **Never infer, guess, or construct a docs URL** from
product name or slug. If you believe a feature is documented but cannot
point to a verified URL from this step, record the match as changelog-sourced
(if a version exists) or drop it entirely.
