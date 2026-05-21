---
name: detect-completed
description: Scans open feature requests for a WooCommerce Marketplace product against its changelog and flags requests whose feature has already shipped. Recommends marking them as completed with a reply pointing to the version. Use when asked to find or close fulfilled/shipped feature requests on WooCommerce.com.
---

# Detect Completed Feature Requests

You are helping a WooCommerce Marketplace team member identify open feature
requests that have already been fulfilled by a shipped release or documented
capability.

**Read first:**
- `.claude/skills/shared/RULES.md`
- `.claude/skills/shared/DISPLAY.md`
- `.claude/skills/shared/PHASE_LOOP.md`
- `.claude/skills/shared/KNOWLEDGE_BASE.md` — changelog + docs crawl

---

## Step 1 — Resolve the product

Follow `.claude/skills/shared/RESOLVE_PRODUCT.md`. Keep the product slug —
it is needed by the knowledge base step.

---

## Step 2 — Build the knowledge base

> **Skip this step if invoked by the orchestrator.** The orchestrator passes
> `kb_path` to `.triage-state/<id>/knowledge_base.json` — load it from there.

Follow `.claude/skills/shared/KNOWLEDGE_BASE.md` in full. Store the result
in memory (changelog entries, doc capabilities, `latest_version`).

---

## Step 3 — Fetch open feature requests

> **Skip this step if invoked by the orchestrator.** Read FRs from
> `input_path` as JSONL.

Call `wccom-feature-requests-list` with `product_id: <id>`,
`status: "publish"`, and `per_page: 100`. Paginate until a page returns fewer
than 100 items. Collect `id`, `title`, `description`, `status`, `votes`,
`date`, `url`.

URL carry-through is mandatory — see `RULES.md`.

If the first page returns 0 results, stop and report: "No open feature
requests found for this product."

---

## Step 4 — DETECTION STARTS HERE — Match ALL FRs against the knowledge base

(Orchestrator subagent: begin reading from this step.)

One pass over every FR. For each FR, reason about whether any knowledge base
entry (changelog or docs) describes a shipped or documented feature that
fulfils the FR's core ask.

A match means: a user who submitted this FR would consider their request
addressed. Be conservative — only flag matches you're reasonably confident
about.

Assign confidence per `RULES.md`:
- **High** — the knowledge base directly and fully addresses the FR
- **Low** — partially addressed, or likely addressed but with ambiguity

For each match record:
- FR fields: `id`, `title`, `votes`, `date`, `url`
- Source: changelog version + date, OR docs page URL
- The specific line / feature description that addresses it
- Confidence and a one-sentence reason
- Excerpt: first 1–3 sentences of the FR description, trimmed

**Docs source rule** — see `KNOWLEDGE_BASE.md`. A docs match may only cite a
URL fetched and verified in Step 2 (HTTP 200, content read). Never infer or
construct a docs URL.

Do not present partial results mid-pass. Complete the full pass, then
present all matches.

### Flagged record schema (for orchestrator output JSONL)

```
{ "id": <int>, "title": "<str>", "url": "<str>",
  "reason": "<one sentence>", "confidence": "High" | "Low",
  "excerpt": "<first 1–3 sentences of description>",
  "shipped_version": "<vX.Y.Z>" | null,
  "shipped_date": "<YYYY-MM-DD>" | null,
  "source": "changelog" | "docs",
  "docs_url": "<verified URL>" | null,
  "ship_line": "<specific changelog line or doc excerpt>" }
```

---

## Step 5 — Present the report

Follow `DISPLAY.md` pagination. Decode HTML entities. Translate non-English
excerpts per `RULES.md`.

For each match:

```
## Match [N]: "[FR title]"
Confidence: High / Low
Source: changelog · [Product Name] [version] ([release date])
     OR docs · [docs page URL]
Reason: [one sentence — why this FR is fulfilled]

FR:   ID [id] — "[title]" ([votes] votes · [date])
      [url]
      "[description — first 2–3 sentences, trimmed if long]"
Ship: [specific changelog line or doc excerpt that addresses it]
```

End with:
_X open FRs scanned · Y likely completed (Z high confidence, W low confidence)._

If no matches, report that and stop.

---

## Step 6 — Confirmation menu

```
Which matches should I mark as completed?

  [1] "[short FR title]" → [source: version or docs]
  [2] "[short FR title]" → [source: version or docs]
  ...
  [A] All of the above
  [H] High confidence only      ← omit if no High items (see RULES.md)
  [N] None / skip

Reply with numbers (e.g. "1 3"), A for all, H for high confidence only, or N to skip.
```

Wait for the user's reply.

---

## Step 7 — Preview comments

Plain text only (see `RULES.md`).

Render a preview for every approved match with placeholders filled in:

```
📝 Comment preview — ID [id] — "[title]"

---
[full comment text]
---
```

**Changelog-sourced template:**

```
Hi there,

Thank you for your suggestion!

Great news! This feature was shipped in [product_name] [version] ([release_date])!

Therefore, I am marking this request as completed. Please update to [version] or later to access this feature.
```

**Docs-sourced template** (feature documented but no specific changelog
version):

```
Hi there,

Thank you for your suggestion!

Great news! This feature is already supported by [product_name] (as of version [latest_version]). You can find more details in our documentation: [docs page URL]

Therefore, I am marking this request as completed.
```

> `[docs page URL]` must be a URL verified in Step 2. If none, fall back to
> the changelog template (or omit the match if no version exists).

After all previews: **"Post these comments and mark as completed? (Y / N)"**
If N, abort.

---

## Step 8 — Close approved matches

For each approved match, in this order:

1. **Post a comment** via `wccom-feature-requests-comment`.
2. **Update status** via `wccom-feature-requests-update-status` →
   `"completed"`.
3. **Write failure handling** — if either call fails, do not record as
   actioned. Report in the summary; continue. If the comment posted but
   status update failed, note the half-completed state — manual cleanup
   required.

---

## Step 9 — Confirmation summary

```
Done.

✅ Completed: ID [id] — "[title]"
   Source: [product_name] [version] ([release_date]) OR [docs page URL]
   [url]

⚠️  Failed: ID [id] — "[title]" — [error]
   [url]
```

One line per actioned FR, then: _N marked as completed · F failed._

Then follow `PHASE_LOOP.md`.
