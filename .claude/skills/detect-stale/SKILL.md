---
name: detect-stale
description: Scans open feature requests for a WooCommerce Marketplace product and flags stale ones (opened more than 3 years ago with 2 or fewer votes). Groups them semantically, proposes tailored closing comments per group (with workarounds/plugins where known), then closes approved ones. Use when asked to find or clean up stale/old/low-vote feature requests on WooCommerce.com.
---

# Detect Stale Feature Requests

A request is **stale** when opened more than **3 years ago** with **2 votes
or fewer**.

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
`status: "publish"`, `per_page: 100`. Paginate. Collect `id`, `title`,
`description`, `status`, `votes`, `date`, `url`.

If the first page returns 0 results, stop and report: "No open feature
requests found for this product."

---

## Step 3 — DETECTION STARTS HERE — Identify stale requests

(Orchestrator subagent: begin reading from this step.)

Compute today's date. A request is **stale** if **both** are true:

1. `date` is more than **3 years** before today.
2. `votes` is **2 or fewer**.

Assign confidence per `RULES.md`:
- **High** — clean stale pattern (no recent comment activity, no signal of
  ongoing interest)
- **Low** — borderline (e.g. recent engagement, comments, or borderline age)

If no requests meet the criteria, report that and stop.

---

## Step 4 — Group stale requests semantically

Cluster the stale FRs into 3–7 named groups by feature area or theme (e.g.
"Checkout & Cart", "Email Notifications", "Reporting", "Shipping",
"Integrations"). Each FR belongs to exactly one group. Outliers go to
**Other**.

Decode HTML entities before showing titles. Translate non-English titles per
`RULES.md`.

Present:

```
## Stale Feature Requests — [Product Name]
[X] open requests scanned · [Y] stale (opened >3 years ago, ≤2 votes) · [N] groups

  [A] [Group name] — N request(s)
  [B] [Group name] — N request(s)
  [C] Other — N request(s)
  ...

Which group would you like to start with? Reply with a letter, or N to skip this phase entirely.
```

### Flagged record schema (for orchestrator output JSONL)

```
{ "id": <int>, "title": "<str>", "url": "<str>",
  "reason": "<one sentence>", "confidence": "High" | "Low",
  "excerpt": "<first 1–3 sentences>",
  "votes": <int>, "date": "<YYYY-MM-DD>",
  "group_label": "<group name>",
  "suggestion_kind": "completed" | "workaround" | "standard",
  "suggestion_text": "<one-sentence rationale>",
  "suggested_comment": "<full plain-text comment to post>" }
```

---

## Step 5 — Work through a group

Repeat 5a–5d per group the user chooses.

### 5a — Show full group details with per-FR suggestions

If a group has >20 FRs, paginate within the group per `DISPLAY.md`.

For each FR, reason about whether a workaround, alternative plugin, or
built-in setting addresses it. Apply these rules strictly:

**Plugins:** Only recommend a plugin if all three are true:
1. Listed on woocommerce.com/products/…
2. Developed by WooCommerce or Automattic (check the "by" line)
3. Not retired or discontinued

**Settings / docs:** Only mention a built-in setting if explicitly described
in official WooCommerce documentation. No inference. When a built-in
already addresses the FR, label the suggestion **"→ mark as completed"** —
these use the completed workflow (completed comment + status `"completed"`).

**Code / customizations / snippets:** Only suggest if spelled out verbatim
in official docs. No improvised solutions.

**Third-party plugins:** Never recommend.

If none of the above applies: "standard close".

Display:

```
## Group [X]: [Group Name] ([N] requests)

[1]. ID [id] — "[title]"
     [votes] vote(s) · opened [date]
     [url]
     "[description — first 2–3 sentences, trimmed if long]"
     💡 Suggestion: [plugin workaround] OR [built-in → mark as completed] OR [standard close]
```

### 5b — Confirmation menu

```
Which requests in this group should I close?

  [1] "[short title]" ([N] votes · opened YYYY-MM-DD)
  [2] "[short title]" ([N] votes · opened YYYY-MM-DD)
  ...
  [A] All of the above
  [H] High confidence only      ← omit if no High items (see RULES.md)
  [N] None / skip group

Reply with numbers (e.g. "1 3"), A for all, H for High only, or N to skip.
```

Wait for the user's reply.

### 5c — Preview and confirm

Plain text only (see `RULES.md`).

Draft each comment using its `💡 Suggestion`:

**Completed variant** (built-in setting / existing feature):
```
Hi there,

Thank you for your suggestion!

Great news! This is already supported by [product_name]. [specific setting or feature description, one sentence].

Therefore, I am marking this request as completed. If you need help setting this up, our support team is happy to assist at https://woocommerce.com/contact-us/
```

**Standard variant:**
```
Hi there,

Thanks so much for taking the time to share this.

After reviewing, we've decided to close this one for now. It's been open for a while without gathering broader demand from other users, and we aim to prioritize the features that will benefit the largest portion of our community.

If you still need this functionality, our support team would be happy to help you explore your options at https://woocommerce.com/contact-us/

If this becomes a more widely-requested feature down the road, we're always open to revisiting it.

Thanks again for your suggestion!
```

**Workaround variant** (plugin recommendation):
```
Hi there,

Thanks so much for taking the time to share this.

After reviewing, we've decided to close this one for now. It's been open for a while without gathering broader demand from other users, and we aim to prioritize the features that will benefit the largest portion of our community.

In the meantime, [specific plugin] may cover what you're looking for. Our support team can also help you find the best approach for your setup at https://woocommerce.com/contact-us/

If this becomes a more widely-requested feature down the road, we're always open to revisiting it.

Thanks again for your suggestion!
```

Render previews:

```
📝 Comment preview — ID [id] — "[title]" [will be marked completed / closed]

---
[full comment text]
---
```

After all previews: **"Post these comments and action the requests? (Y / N)"**
If N, abort.

### 5d — Execute

For each approved request, in order:

1. **Post comment** via `wccom-feature-requests-comment`.
2. **Update status** via `wccom-feature-requests-update-status`:
   - `"completed"` if suggestion was **"→ mark as completed"**
   - `"closed"` otherwise
3. **Write failure handling** — see `RULES.md` pattern: on failure, do not
   record as actioned; report in summary; continue.

Print:
```
✔ ID [id] — "[title]": completed
✔ ID [id] — "[title]": closed
⚠️  ID [id] — "[title]": failed — [error]
```

Group summary:
```
Group [X] done. N completed, M closed, F failed.
```

---

## Step 6 — Navigate to the next group

```
Which group would you like to go to next?

  [B] [Group name] — N request(s)
  [C] Other — N request(s)
  ...
  [S] Skip to next phase

Reply with a letter, or S (or "skip") to move on.
```

Loop to Step 5. When all groups done, proceed to Step 7.

---

## Step 7 — Phase summary

```
Done.

✅ Completed: ID [id] — "[title]" ([votes] vote(s) · opened [date])
   [url]

❌ Closed: ID [id] — "[title]" ([votes] vote(s) · opened [date])
   [url]

⚠️  Failed: ID [id] — "[title]" — [error]
```

One line per actioned FR (completed first, then closed, then failed), then:
_N completed, M closed, F failed._

Then follow `PHASE_LOOP.md`.
