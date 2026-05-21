# Shared — Display & Output Rules

Applies to every triage skill whenever feature requests are shown to the user
or written back to the API.

---

## Confidence levels

Every flagged FR carries a confidence label:

- **High** — pattern is unambiguous; safe default-to-action
- **Low** — pattern is plausible but worth a human look

Use these exact strings (capitalised). The duplicate-detection script emits
lowercase `high` / `low` in JSON — normalise to capitalised when displaying.
The stale phase uses confidence too: High = stale pattern is clean (≤2 votes,
>3 years, no engagement); Low = borderline (e.g. recent comment activity).

---

## ID display

**Never use `#[id]` syntax.** It auto-links to GitHub issues in markdown
renderers. Always write plain `ID [id]` or the full FR URL.

## URL carry-through

Always carry the `url` field from the `wccom-feature-requests-list` response
through every downstream step. **Never construct, infer, or derive an FR URL
from title, slug, or ID** — use the API value verbatim.

---

## HTML entity decoding

FR `title` and `description` fields returned by the API may contain HTML
entities (`&nbsp;`, `&amp;`, `&lt;`, `&#8220;`, etc.). **Decode to plain text
before displaying.** Never render raw entities in terminal output, comment
previews, or report excerpts.

---

## Non-English content — translate previews

When a title or description excerpt is not in English, show both forms:

```
[Original] <original title / excerpt>
[Translated from <language>] <English translation>
```

This applies in every report, confirmation menu, and preview — not only in
the orchestrator.

---

## Comments — plain text only

All comment content posted via `wccom-feature-requests-comment` must be
**plain text**. The platform does not render markdown — no `**bold**`,
`*italic*`, `#` headings, backticks, or list syntax. Verbatim URLs are fine.

---

## High-confidence shortcut menu option

Confirmation menus offer an `[H] High confidence only` option **only when at
least one flagged item has High confidence**. If every flagged item is Low,
omit the `[H]` line entirely.
