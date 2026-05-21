---
name: detect-spam
description: Scans open feature requests for a WooCommerce Marketplace product and flags ones that look like spam (promotional links, gibberish, off-topic, copy-pasted SEO content). Lets the user select which to mark as spam, then silently sets the status to spam — no comment is posted. Use when asked to find or clean up spam feature requests on WooCommerce.com.
---

# Detect Spam Feature Requests

You are helping a WooCommerce Marketplace team member identify and silently
flag **spam** feature requests for a specific product. Spam is anything that
isn't a genuine product suggestion: promotional links, gibberish, off-topic
content, scraped/SEO copy-paste, etc.

Spam is handled differently from other triage actions: **no comment is
posted**. The skill only changes status to `spam`.

**Read first:**
- `.claude/skills/shared/RULES.md` — ID display, URL carry-through, HTML
  entity decoding, translation, plain-text comments, confidence labels.
- `.claude/skills/shared/DISPLAY.md` — pagination conventions.
- `.claude/skills/shared/PHASE_LOOP.md` — end-of-phase loop (standalone vs
  orchestrated mode).

---

## Step 1 — Resolve the product

Follow `.claude/skills/shared/RESOLVE_PRODUCT.md` in full.

---

## Step 2 — Fetch all open feature requests

> **Skip this step if invoked by the orchestrator.** The orchestrator passes
> `input_path` — read FRs from there as JSONL.

Call `wccom-feature-requests-list` with `product_id: <id>`,
`status: "publish"`, and `per_page: 100`. Paginate until a page returns fewer
than 100 items. Collect `id`, `title`, `description`, `status`, `votes`,
`date`, `url` for every request.

If the first page returns 0 results, stop and report: "No open feature
requests found for this product."

---

## Step 3 — DETECTION STARTS HERE — Identify spam

(Orchestrator subagent: begin reading from this step.)

A request is likely **spam** if any of these patterns apply:

- **Promotional / link-stuffed** — body is mostly URLs, especially to
  unrelated products, services, or shady domains; affiliate-style copy.
- **Off-topic** — about a different product, an unrelated industry,
  cryptocurrency, weight loss, gambling, adult content, "buy followers",
  prescription drugs, etc.
- **Gibberish / random text** — keyword soup, broken grammar that looks
  machine-generated or pasted out of context, lorem-ipsum-like filler.
- **Scraped / SEO copy-paste** — boilerplate marketing prose with no
  specific feature ask.
- **Exact or near-identical duplicates** — same body text across multiple
  requests; strong signal of coordinated spam.
- **Account / contact info dump** — phone numbers, emails, login
  credentials, "call us at…" style content.
- **Trojan horse pivot** — opens with a generic relatable statement then
  pivots to promote an unrelated product or link.
- **Link syntax probing** — lists of URL format variants (BBCode, markdown,
  wiki syntax) with no actual feature request content.
- **Non-Latin script with no product relevance** — content in a script
  unrelated to the product's audience that contains no genuine feature ask,
  especially paired with promotional links.

A request is **NOT** spam (leave it alone) if it:

- Describes any genuine product feature, no matter how rough or short.
- Is a support question (use `/detect-support-requests`).
- Is in a non-English language but on-topic — translate, don't flag.

Be conservative. False positives mean a real merchant gets silently
disappeared. **Only flag where the spam framing is unambiguous.**

Assign confidence per `RULES.md` (High / Low).

### Flagged record schema (for orchestrator output JSONL)

```
{ "id": <int>, "title": "<str>", "url": "<str>",
  "reason": "<one sentence>", "confidence": "High" | "Low",
  "excerpt": "<first 1–3 sentences of description, trimmed>" }
```

---

## Step 4 — Present the report

Follow `DISPLAY.md` pagination. Decode HTML entities. Translate non-English
excerpts per `RULES.md`.

For each flagged request:

```
## ID [id] — "[title]"
Confidence: High / Low
Reason: [one sentence — what makes this look like spam]

[votes] vote(s) · opened [date]
[url]

Excerpt: "[1–2 sentences from the description showing the spam framing —
verbatim, trimmed if long]"
```

End with a summary line:
_X open requests scanned · Y likely spam (Z high confidence, W low confidence)._

If no requests are flagged, report that and stop.

---

## Step 5 — Confirmation menu

```
Which requests should I mark as spam?

  [1] "[short title]" (confidence)
  [2] "[short title]" (confidence)
  ...
  [A] All of the above
  [H] High confidence only      ← omit if no High items (see RULES.md)
  [N] None / skip

Reply with numbers (e.g. "1 3"), A for all, H for high confidence only, or N to skip.

⚠️  Marking as spam is silent — no comment will be posted on the request.
```

Wait for the user's reply before taking any action.

---

## Step 6 — Mark approved requests as spam

For each approved request:

1. Call `wccom-feature-requests-update-status` with `id` set to the FR's ID
   and `status: "spam"`.
2. **Fallback** — if the API returns a permission error (403 / "not
   allowed"), retry with `status: "closed"`. Record the fallback so the
   summary distinguishes it.
3. **Write failure handling** — if both attempts fail, do **not** record this
   FR as actioned. Report the failure in the summary and continue to the
   next FR.

**Do not post any comment.** Spam handling is silent by design.

---

## Step 7 — Confirmation summary

```
Done.

🚫 Marked as spam: ID [id] — "[title]" ([votes] vote(s) · opened [date])
   [url]

❌ Closed (spam fallback — no spam permission): ID [id] — "[title]"
   [url]

⚠️  Failed: ID [id] — "[title]" — [error]
   [url]

⏭️  Left open (not confirmed): ID [id] — "[title]"
```

Omit any section with no entries. End with:
_N marked as spam · M closed as fallback · F failed · P left open._

Then follow `PHASE_LOOP.md`.
