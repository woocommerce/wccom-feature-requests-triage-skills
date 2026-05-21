---
name: detect-duplicates
description: Scans all feature requests for a WooCommerce Marketplace product and surfaces duplicates. Use when asked to find or clean up duplicate feature requests on WooCommerce.com.
---

# Detect Duplicate Feature Requests

You are helping a WooCommerce Marketplace team member identify and act on
duplicate feature requests for a specific product.

**Read first:**
- `.claude/skills/shared/RULES.md`
- `.claude/skills/shared/DISPLAY.md`
- `.claude/skills/shared/PHASE_LOOP.md`

---

## Step 1 — Resolve the product

Follow `.claude/skills/shared/RESOLVE_PRODUCT.md`.

---

## Step 2 — Fetch all open feature requests

> **Skip this step if invoked by the orchestrator.** The orchestrator passes
> the FRs in `input_path` (a JSONL file already on disk). Use it directly as
> the input to the detection script in Step 3 and **skip writing
> `/tmp/frs-<id>.jsonl`**.

Call `wccom-feature-requests-list` with `per_page=100` and
`status: "publish"`. Paginate. Collect `id`, `title`, `description`,
`status`, `votes`, `date`, `url`.

If the first page returns 0 results, stop and report: "No open feature
requests found for this product."

---

## Step 2b — Choose comparison depth

> **Skip this step if invoked by the orchestrator.** The orchestrator passes
> `comparison_mode` (`fast` or `in-depth`).

Ask:

```
How thorough should the duplicate scan be?

  [F] Fast       — title-based matching only (script + false-positive pruning).
                   Good for quick cleanup. Misses duplicates with different titles
                   but similar descriptions.
  [D] In-depth   — title + full description comparison. Claude reads every
                   description to catch hidden duplicates.
                   More thorough, takes longer.

Reply F or D.
```

Store as **comparison_mode** (`fast` or `in-depth`). Default to `fast`.

---

## Step 2c — Write FRs to a temp file

> **Skip this step if invoked by the orchestrator.** Use the orchestrator's
> `input_path` directly.

Use `Write` to create `$TMPDIR/frs-<product_id>.jsonl`. One JSON object per
line: `id`, `title`, `description`, `votes`, `date`, `url`.

---

## Step 3 — DETECTION STARTS HERE — Run the duplicate detection script

(Orchestrator subagent: begin reading from this step. Use `<input_path>`
wherever the script command shows `$TMPDIR/frs-<product_id>.jsonl`.)

Choose the command based on **comparison_mode**:

- **fast:** `python3 scripts/detect_duplicates.py $TMPDIR/frs-<product_id>.jsonl --json`
- **in-depth:** `.venv/bin/python3 scripts/detect_duplicates.py $TMPDIR/frs-<product_id>.jsonl --semantic --rerank --json`

The `--semantic --rerank` flags require `sentence-transformers` in `.venv/`.
If import error, fall back to fast and note it.

Parse the JSON output:
```json
{
  "groups": [
    {
      "confidence": "high" | "low",
      "max_similarity": 0.75,
      "primary": {"id": 123, "title": "...", "votes": 5, "date": "...", "url": "..."},
      "duplicates": [{"id": 456, "title": "...", "votes": 2, "date": "...", "url": "..."}]
    }
  ],
  "borderline_pairs": [
    {"similarity": 0.58, "fr_a": {...}, "fr_b": {...}}
  ]
}
```

Normalise script confidence (`high`/`low` lowercase) to `High`/`Low` per
`RULES.md`. Store `groups` as **script groups** and `borderline_pairs` for
Step 3b-ii. If the script fails entirely, fall back to Step 3b and note it.

---

## Step 3b — Claude semantic review

### 3b-i — Review script groups for false positives

For each group, read full titles and descriptions of every member. If a
pair is clearly NOT the same ask (same keyword but different intent), remove
the false-positive member. If a group reduces to one member, discard it.

**Freed FRs go to a `re-evaluation pool`** — they may be true duplicates of
a *different* FR that the script missed.

**Do not discard a group for being support/spam/off-topic.** Duplicates are
duplicates regardless of quality. Surface them here.

Upgrade or downgrade confidence:
- Upgrade to **High** if full text confirms a match beyond title similarity.
- Downgrade to **Low** if the match is only superficial.

### 3b-ii — Semantic review of borderline pairs

**Skip entirely if `comparison_mode = fast`.** Proceed to 3b-iii.

If `in-depth`:

Review two inputs:
1. `borderline_pairs` from the script — pairs near the threshold.
2. `re-evaluation pool` from 3b-i.

For each borderline pair, read both `title` and `description` in full.
Decide: same core ask? If yes, add as a new group. Be conservative.

For pool FRs not covered by any pair, pay attention to vague short titles
("Booking", "Hi :)") — read full descriptions before comparing.

Assign confidence (**High** / **Low**). Primary = most votes, then oldest if
tied. Add as new groups.

### 3b-iii — Merge

Combine script groups (after pruning) with new semantic groups. Sort: High
first, then by primary vote count descending.

---

## Step 4 — Present the report

Pagination — grouped phase, see `DISPLAY.md`. Decode HTML entities.
Translate non-English excerpts per `RULES.md`.

For each group:

```
## Group [N]: [short description of the shared ask]
Confidence: High / Low
Reason: [one sentence — what makes these the same ask]

✅ Keep:  ID [id] — "[title]" ([votes] votes · [status] · [date])
          [url]
          "[description — first 2–3 sentences, trimmed if long]"
❌ Close: ID [id] — "[title]" ([votes] votes · [status] · [date])
          [url]
          "[description — first 2–3 sentences, trimmed if long]"
```

End with:
_X requests scanned · Y duplicate groups · Z requests could be closed._

### Flagged record schema (for orchestrator output JSONL)

One record **per duplicate-to-close**:

```
{ "id": <int>, "title": "<str>", "url": "<str>",
  "reason": "<one sentence>", "confidence": "High" | "Low",
  "excerpt": "<first 1–3 sentences>",
  "votes": <int>, "date": "<YYYY-MM-DD>",
  "group_id": <int>,
  "primary": { "id": <int>, "title": "<str>", "url": "<str>",
               "status": "<str>", "votes": <int>, "date": "<YYYY-MM-DD>",
               "excerpt": "<first 1–3 sentences>" } }
```

---

## Step 5 — Confirmation menu

List every closeable duplicate grouped by group number. Within each group,
sort High → Low. Assign sequential numbers across all groups (stable for
pagination).

```
Which requests should I close?

  Group 1: [short group label]
    [1] ID [id] — "[title]" [High]
    [2] ID [id] — "[title]" [High]
    [3] ID [id] — "[title]" [Low]

  Group 2: [short group label]
    [4] ID [id] — "[title]" [High]
  ...
  [A] All of the above
  [H] High confidence only      ← omit if no High items (see RULES.md)
  [N] None / skip

Reply with numbers (e.g. "1 3"), A for all, H for High only, or N to skip.
```

Wait for the user's reply. Then group approved requests by their comment
template (same primary + same primary status = same template). For each
distinct template, show the preview **once** with the list of FRs:

```
📝 Comment preview — applies to [N] request(s):
  • ID [id] — "[title]"
  • ID [id] — "[title]"

---
[full comment text, with [primary_url] filled in]
---
```

After all previews: **"Post these comments and close the requests? (Y / N)"**
If N, abort.

Then for each approved duplicate, look up its group's primary and process in
this order:

1. **Post closing comment** via `wccom-feature-requests-comment`. Template
   depends on **primary status**:

   **Primary `open` with more votes:**
   ```
   Hi there,

   Thank you for your suggestion!

   We noticed that there is a similar request about this, which currently has more votes: [primary_url]. To better prioritize requests, we aim to keep 1 request open per feature. That's why I will close this one. I encourage you to upvote the above request instead.
   ```

   **Primary `open` with equal votes (kept because older):**
   ```
   Hi there,

   Thank you for your suggestion!

   We noticed that there is a similar request about this that has been open longer: [primary_url]. To better prioritize requests, we aim to keep 1 request open per feature. That's why I will close this one. I encourage you to upvote the above request instead.
   ```

   **Primary `planned` or `in-progress`:**
   ```
   Hi there,

   Thank you for your suggestion!

   We noticed that this feature is already planned and being tracked here: [primary_url]. That's why I will close this duplicate. You can follow progress on that request instead.
   ```

   **Primary `completed`:**
   ```
   Hi there,

   Thank you for your suggestion!

   Great news — this feature has already been implemented! You can find more details here: [primary_url]. That's why I will close this request.
   ```

2. **Update status** via `wccom-feature-requests-update-status` → `"closed"`.

3. **Write failure handling** — on failure, do not record as actioned;
   report in summary; continue. If comment posted but status update failed,
   note the half-completed state.

---

## Step 6 — Extract insights for each primary

After closing approved duplicates, for each group with at least one closure,
compare full descriptions of every closed request against the primary's.
Look for:

- Additional use cases or scenarios not covered by the primary
- Different user workflows or perspectives
- Concrete details, examples, or edge cases
- Explicit requirements/constraints mentioned only in closed requests

If unique insights are found, draft a comment for the **primary**. Plain
text only (see `RULES.md`). Example:

```
Hi there,

We recently consolidated a few related requests into this one. In doing so,
we noticed some additional use cases and perspectives worth capturing here:

- [insight 1]
- [insight 2]
...

We've noted these for the team when reviewing this request.
```

Preview:

```
📝 Draft comment for primary — ID [primary_id] — "[primary_title]"
[primary_url]

---
[full draft comment]
---

Post this comment to the primary request? (Y / N)
```

If Y: call `wccom-feature-requests-comment` on the primary's ID. **Do not
update the primary's status.**

If no unique insights across any closed duplicate:
_"No additional insights found — primary requests are already comprehensive."_
Skip the step.

---

## Step 7 — Confirmation summary

```
Done.
❌ Closed: ID [id] — "[title]"
   [closed_url]
✅ Primary: ID [id] — "[title]" ([status])
   [primary_url]

⚠️  Failed: ID [id] — "[title]" — [error]
```

Then follow `PHASE_LOOP.md`. Additionally, the standalone re-scan prompt
accepts a group-number reference:

```
Need more context on a group? Type the group number (e.g. "Group 3").
```

If the user specifies a group number: show full `title`, `description`,
`votes`, `date`, `url` for every request in that group (primary + all
closeable duplicates), then re-ask the loop question.
