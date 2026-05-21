---
name: detect-support-requests
description: Scans open feature requests for a WooCommerce Marketplace product and flags ones that are actually support questions (troubleshooting, setup help, bug reports framed as features). Lets the user select which to close, then posts a closing comment redirecting them to woocommerce.com/contact-us/. Use when asked to find or clean up support questions misfiled as feature requests.
---

# Detect Support Requests Posted as Feature Requests

You are helping a WooCommerce Marketplace team member identify and close
feature requests that are actually **support questions** — store-specific
issues, troubleshooting, setup help, or bug reports — and redirect those
users to the WooCommerce support team.

**Read first:**
- `.claude/skills/shared/RULES.md`
- `.claude/skills/shared/DISPLAY.md`
- `.claude/skills/shared/PHASE_LOOP.md`

---

## Step 1 — Resolve the product

Follow `.claude/skills/shared/RESOLVE_PRODUCT.md`.

---

## Step 2 — Fetch all open feature requests

> **Skip this step if invoked by the orchestrator.** Read FRs from
> `input_path` as JSONL.

Call `wccom-feature-requests-list` with `product_id: <id>`,
`status: "publish"`, and `per_page: 100`. Paginate until a page returns fewer
than 100 items. Collect `id`, `title`, `description`, `status`, `votes`,
`date`, `url`.

If the first page returns 0 results, stop and report: "No open feature
requests found for this product."

---

## Step 3 — DETECTION STARTS HERE — Identify support requests

(Orchestrator subagent: begin reading from this step.)

A request is likely a **support request** if any of these patterns apply:

- **Personal/store-specific language** — "I can't get X to work on **my**
  store / my checkout / my site", "When I do Y, it errors out for me".
- **Troubleshooting / how-to** — "How do I configure…?", "Why isn't X
  showing up?", "It stopped working after the update".
- **Bug report framed as a feature** — "Please fix X" describing something
  that already exists but is broken in their setup.
- **Setup / installation help** — questions about activating, connecting,
  or migrating data.
- **Diagnostic info present** — error messages, screenshots of admin
  errors, references to specific orders/products on their site.
- **Direct questions to the team** — "Can you help me?", "Where do I
  change the settings?", closing with "Thanks!" or "Please help."

A request is **NOT** a support request (leave it alone) if it:

- Asks for new functionality, an enhancement, or an integration.
- Describes a workflow improvement that would benefit other merchants.
- Is written in product-level language ("Add support for X", "It would be
  great if the plugin could Y") rather than store-level.

Be conservative. Only flag where the support framing is clear.

Assign confidence per `RULES.md` (High / Low).

### Flagged record schema

```
{ "id": <int>, "title": "<str>", "url": "<str>",
  "reason": "<one sentence>", "confidence": "High" | "Low",
  "excerpt": "<first 1–3 sentences of description, trimmed>" }
```

---

## Step 4 — Present the report

Follow `DISPLAY.md` pagination. Decode HTML entities. Translate non-English
excerpts per `RULES.md`.

```
## ID [id] — "[title]"
Confidence: High / Low
Reason: [one sentence — what makes this look like a support request]

[votes] vote(s) · opened [date]
[url]

Excerpt: "[1–2 sentences from the description that show the support
framing — verbatim, trimmed if long]"
```

End with:
_X open requests scanned · Y likely support requests (Z high confidence, W low confidence)._

If no requests are flagged, report that and stop.

---

## Step 5 — Confirmation menu

```
Which requests should I close as support requests?

  [1] "[short title]" (confidence)
  [2] "[short title]" (confidence)
  ...
  [A] All of the above
  [H] High confidence only      ← omit if no High items (see RULES.md)
  [N] None / skip

Reply with numbers (e.g. "1 3"), A for all, H for high confidence only, or N to skip.
```

Wait for the user's reply before taking any action.

---

## Step 6 — Preview comments

Plain text only (see `RULES.md`).

```
📝 Comment preview — ID [id] — "[title]"

---
[full comment text]
---
```

After all previews, ask: **"Post these comments and close the requests? (Y / N)"**
Wait for confirmation. If N, abort.

---

## Step 7 — Close approved requests

For each approved request, **in this order**:

1. **Post a closing comment** via `wccom-feature-requests-comment`:

   ```
   Hey there! Thank you for getting in touch. This looks like a support question, rather than a feature request. To get help with this, I encourage you to get in touch with our support team at: https://woocommerce.com/my-account/contact-support/.
   ```

2. **Update status** via `wccom-feature-requests-update-status` → `"closed"`.

3. **Write failure handling** — if either call fails, do **not** record this
   FR as actioned. Report the failure in the summary; continue to the next
   FR. If the comment posted but the status update failed, note the
   half-completed state — manual cleanup required.

---

## Step 8 — Confirmation summary

```
Done.

❌ Closed: ID [id] — "[title]" ([votes] vote(s) · opened [date])
   [url]

⚠️  Failed: ID [id] — "[title]" — [error]
   [url]
```

One line per FR, then: _N support requests closed · F failed._

Then follow `PHASE_LOOP.md`.
