---
name: triage-woo-feature-requests
description: Full triage orchestrator for a WooCommerce Marketplace product's feature requests. Fetches all requests once to disk, then delegates each phase (completed → duplicates → spam → support → stale) to a subagent to keep the main context light. State is persisted under `.triage-state/<product_id>/` so the run is resumable per-FR. Ends with an optional free-form analysis pass. Use when asked to run a full triage or cleanup on a product's feature requests.
---

# Full Feature Request Triage

You are running a full triage of open feature requests for a WooCommerce
Marketplace product. This orchestrator is built for products with **hundreds
of FRs**: the working set lives on disk (not in your context), each phase
runs in a **subagent** that returns a compact flagged list, and progress is
**resumable per FR** so a disconnect or compaction never loses ground.

**Read first:**
- `.claude/skills/shared/RULES.md` — display rules, confidence, plain text
  comments, URL carry-through, HTML entity decoding, translation.
- `.claude/skills/shared/DISPLAY.md` — pagination conventions (flat and
  grouped).
- `.claude/skills/shared/RESOLVE_PRODUCT.md` — product ID resolution.
- `.claude/skills/shared/KNOWLEDGE_BASE.md` — used by the completed phase.

State directory: `.triage-state/<product_id>/` (gitignored). Helper CLI:
`scripts/triage_state.py`. Use it for every read/write of state.

---

## Step 1 — Resume or fresh start

After resolving the product (Step 2), run:

```
python3 scripts/triage_state.py status --product-id <id>
```

If `exists` is `true` and any `phase_status` is `in_progress` or there are
entries in `flagged/` or `actioned.jsonl`, ask:

```
Found prior triage state for [product_name] (id [id]):
  Fetched: [fetched_at humanized, or "never"]
  Working set: [N] FRs cached
  Actioned so far: [M]
  Phase status: completed=[…] duplicates=[…] spam=[…] support=[…] stale=[…]

Resume from where you left off? (Y / start fresh / cancel)
```

- **Y / Enter**: continue. Skip phases already `completed`. Re-enter
  `in_progress` phases mid-flight.
- **start fresh**: run `triage_state.py reset --product-id <id>`, then
  proceed.
- **cancel**: stop.

If no state exists, proceed straight to Step 2.

> Display only the phases the user selected (Step 4). Don't list status for
> phases that were never initialised.

---

## Step 2 — Resolve the product

Follow `.claude/skills/shared/RESOLVE_PRODUCT.md`.

---

## Step 3 — Verify ownership (read-only)

Fetch the first open feature request for this product:

```
wccom-feature-requests-list with product_id: <id>, status: "publish", per_page: 1
```

- If the list is empty, skip this check — nothing to action anyway.
- If at least one FR returned: read the response shape. If the API surfaces
  an `editable` / `can_edit` / `_links.edit` field (or equivalent), use it
  to confirm write access without performing any write.

**Do not perform a no-op write probe** (the previous design wrote a current
status back to the FR — even no-ops may trigger audit logs, webhooks, or
`last_modified` bumps). If you cannot determine write access from the read
response, proceed and let the first real write either succeed or fail; if
the first write returns a permission error, stop and report:

```
⛔ Product [id] does not appear to be owned by the current API credentials.
Write actions are being rejected. Please re-run with credentials that own
this product.
```

Do **not** continue actioning further phases.

---

## Step 4 — Select phases to run

```
Which checks should I run? (default: all)

  [1] Completed   — flag requests fulfilled by a shipped release
  [2] Duplicates  — find and close duplicate requests
  [3] Spam        — silently mark spam requests
  [4] Support     — close misplaced support questions
  [5] Stale       — close old low-vote requests

Reply with numbers (e.g. "2 4"), or press Enter / type A to run all.
```

Map to phase keys: `completed,duplicates,spam,support,stale`. Initialise:

```
python3 scripts/triage_state.py init \
  --product-id <id> \
  --product-name "<product_name>" \
  --phases <comma-separated-keys>
```

`init` is resume-safe — preserves existing `phase_status` and `fetched_at`.

---

## Step 5 — Build the knowledge base (only if Completed is selected)

If Phase 1 (Completed) is selected AND `knowledge_base.json` does NOT exist
under `.triage-state/<id>/`, follow `.claude/skills/shared/KNOWLEDGE_BASE.md`
in full to build the changelog + documentation knowledge base.

Write to `.triage-state/<id>/knowledge_base.json` per the schema in that
file. Subsequent runs reuse it.

If Phase 1 isn't selected, or the file exists, skip.

---

## Step 6 — Fetch ALL open feature requests (to disk)

Check freshness first:

```
python3 scripts/triage_state.py fetched-age --product-id <id>
```

- `fetched: false`: proceed to fetch.
- `fetched: true`: ask:
  ```
  Cached working set is [age humanized] old ([N] FRs).
  Refresh from the API? (y / N — keep cache)
  ```
  - `y`: re-fetch.
  - Enter / `N`: skip fetch, reuse cache.

**To fetch — MUST be done in a subagent.** Do **NOT** call
`wccom-feature-requests-list` from the main (orchestrator) context. MCP
tool results land in the caller's context window; for products with
hundreds of FRs this blows the budget before any phase runs. The fetch
subagent's context holds the raw JSON; the orchestrator only sees a
compact summary.

Spawn a `general-purpose` subagent with the following prompt (substitute
`<id>`, `<product_name>`):

```
You are a fetch-only subagent for the wccom triage orchestrator.

Goal: page through wccom-feature-requests-list and save every open FR to
disk for product <id> (<product_name>).

DO NOT:
- Call any wccom-feature-requests-* write tools.
- Re-fetch beyond what's needed (stop on the first short page).
- Echo FR payloads back to the orchestrator. Return only a compact summary.

DO:
- Call `mcp__wccom-feature-requests-prod__wccom-feature-requests-list` with
  product_id: <id>, status: "publish", per_page: 100, starting at page 1.
- For each page, write the raw JSON response to
  $TMPDIR/triage-page-<page>.txt via the Write tool. If a tool result is
  truncated and saved to a tool-results file by the harness, copy that
  file to $TMPDIR/triage-page-<page>.txt instead — do NOT Read it and
  re-Write it.
- Stop when a page returns fewer than 100 items.
- Merge:
  python3 scripts/save_frs.py $TMPDIR/triage-page-*.txt -o /Users/jasonkytros/wccom-triage-agents/.triage-state/<id>/working_set.jsonl
- Mark fetched:
  python3 scripts/triage_state.py set-fetched --product-id <id>
- Return one-line JSON summary on stdout:
  {"pages": <int>, "total": <int>, "working_set": "<path>"}
- Do NOT include FR titles, ids, or descriptions in the summary.

Working dir: /Users/jasonkytros/wccom-triage-agents
```

After the subagent returns, the orchestrator prints:
```
Fetched [total] open FRs for [product_name] → .triage-state/[id]/working_set.jsonl
```

If `total == 0`: report "No open feature requests found for [product_name]."
and stop.

**Never load the full working set into your own context.** This includes:
- Do NOT call the MCP list tool directly from the orchestrator.
- Do NOT Read working_set.jsonl, page files, or actioned.jsonl in full.
- Do NOT Write FR payloads from the orchestrator (the payload appears in
  tool-call args and is just as costly as a Read).
- Subsequent phases must always go through subagents.

---

## Step 7 — Run each selected phase (subagent dispatch)

For each selected phase not already `completed`:

1. **Skip if done**: `phase_status[<phase>] == "completed"` → skip.
2. **Mark in progress**:
   ```
   python3 scripts/triage_state.py set-phase --product-id <id> \
     --phase <phase> --phase-status in_progress
   ```
3. **Build unactioned input** — drop FRs actioned in prior phases or earlier
   this run:
   ```
   python3 scripts/triage_state.py filter-unactioned --product-id <id> \
     --out .triage-state/<id>/flagged/<phase>.input.jsonl
   ```
4. **For duplicates only — prompt comparison mode** before spawning (subagent
   cannot prompt):
   ```
   Comparison depth: (F)ast keyword/TF-IDF, or (I)n-depth semantic rerank?
   In-depth needs .venv with sentence-transformers installed.
   ```
5. **Spawn a subagent** — detection only, no writes. Use the subagent prompt
   template below. Pass:
   - `subagent_type`: `general-purpose`
   - Skill file: `.claude/skills/detect-<phase>/SKILL.md`
   - Input JSONL: `.triage-state/<id>/flagged/<phase>.input.jsonl`
   - Output JSONL: `.triage-state/<id>/flagged/<phase>.jsonl`
   - Knowledge base path (completed only): `.triage-state/<id>/knowledge_base.json`
   - Comparison mode (duplicates only): `fast` | `in-depth`
   - `mode: orchestrated` (suppresses re-scan in `PHASE_LOOP.md`)
6. **Empty output handling** — if the subagent's output JSONL is empty:
   - Print: `_No <phase> findings._`
   - Mark phase `completed`:
     ```
     python3 scripts/triage_state.py set-phase --product-id <id> \
       --phase <phase> --phase-status completed
     ```
   - Continue to the next phase.
7. **Read flagged output** — main agent reads only what it needs to present.
   Page user prompts in batches of 20 per `DISPLAY.md` (grouped or flat per
   phase). Decode HTML entities. Translate non-English excerpts per
   `RULES.md`.
8. **Execute approved actions in the main agent** (auth + confirmations stay
   here). Per FR the user approves, see the per-phase action table below.
9. **After every successful API write, append to `actioned.jsonl`
   immediately** — that's the resume anchor:
   ```
   python3 scripts/triage_state.py append-actioned --product-id <id> \
     --phase <phase> --fr-id <id> --action <verb> --status <new_status>
   ```
10. **API write failure handling** — if any write call fails:
    - Do **not** append to `actioned.jsonl` (so resume retries it).
    - Print: `⚠️  ID [id] — "[title]": failed — [error]`
    - Continue to the next FR.
    - If a comment posted but the status update failed, log
      `action=comment-only status=publish` to `actioned.jsonl` so we know
      not to re-post the comment. Surface the half-state in the summary.
11. **Skipped FRs**: when the user explicitly passes on a flagged FR (does
    not approve closure), append to `actioned.jsonl` with
    `action=skipped status=publish` so future re-scans don't re-prompt:
    ```
    python3 scripts/triage_state.py append-actioned --product-id <id> \
      --phase <phase> --fr-id <id> --action skipped --status publish
    ```
12. **End-of-phase loop**:
    - Ask: `Would you like to action more requests from this phase? (Y / N)`
      - `Y`: loop back to step 7 with remaining items.
      - `N` / empty: continue.
    - Always ask the re-scan prompt next. Substitute `<phase>` with the
      current phase name (e.g. "completed", "duplicates"):
      ```
      Run the <phase> detection again in case anything was missed, or move
      on to the next phase? (Another look / Move on)
      ```
      - **Another look**: re-run from step 3 (rebuild unactioned input,
        re-spawn subagent). If the subagent returns zero new flagged FRs,
        print `_No new findings._`, mark phase `completed`, and continue.
        Do **not** loop the re-scan prompt again.
      - **Move on**: mark phase `completed`.
13. Print a one-line phase summary, continue.

### Per-phase action table

| Phase | Comment? | Status | actioned.jsonl `action` |
|---|---|---|---|
| completed | yes (changelog or docs template, see skill Step 7) | `completed` | `marked-completed` |
| duplicates | yes (template by primary status, see skill Step 5) | `closed` | `closed-duplicate` |
| spam | **no** | `spam` → fallback `closed` | `marked-spam` or `marked-spam-fallback` |
| support | yes (support-redirect message, see skill Step 7) | `closed` | `closed-support` |
| stale | yes (completed/standard/workaround variant per FR) | `completed` or `closed` | `closed-stale` or `marked-completed` |

**Spam fallback** — when calling
`wccom-feature-requests-update-status` with `status: "spam"` returns a
permission error (403 / "not allowed"), retry with `status: "closed"` and
log `action=marked-spam-fallback status=closed`. Surface fallbacks in the
phase summary.

**Duplicates extras** — after all closures for a primary, optionally run the
"Extract insights for each primary" step from the duplicates skill (Step 6).
Main agent only — it needs to read closed FR descriptions from the working
set on disk.

---

## Subagent prompt template

Use this when spawning the per-phase subagent. Substitute `<…>`.

### Base (every phase)

```
You are a detection-only subagent for the wccom triage orchestrator.

mode: orchestrated

DO NOT:
- Call any wccom-feature-requests-* write tools (no comment, no update-status).
- Re-fetch the FR list.
- Resolve the product (already done).
- Crawl the changelog or docs (already done; knowledge base path provided
  when relevant).
- Run the standalone PHASE_LOOP.md re-scan offer — the orchestrator handles
  it. Return after the phase summary.

DO:
- Read the skill file at <skill_path>. Each detect-* skill marks where the
  subagent should begin with a header line:
  `## Step <N> — DETECTION STARTS HERE — …`
  Skip everything above that header.
- Read the input working set from <input_path> (JSONL, one FR per line,
  fields: id, title, description, votes, date, url, status).
- Process FRs in chunks of 50. After each chunk, append flagged records to
  the output file <output_path>.
- Write flagged records as JSONL using the skill's "Flagged record schema"
  block. Every record must include at minimum:
  { "id": <int>, "title": "<str>", "url": "<str>",
    "reason": "<one sentence>", "confidence": "High" | "Low",
    "excerpt": "<first 1–3 sentences of description, trimmed>" }
  Include phase-specific extras per the skill's schema.
- Decode HTML entities in excerpts. Carry the API `url` field verbatim.
- Return a compact JSON summary to stdout when done:
  { "phase": "<phase>", "scanned": <int>, "flagged": <int>,
    "output": "<output_path>", "notes": "<caveats or empty>" }

Inputs:
  phase:           <phase>
  product_id:      <id>
  product_name:    <product_name>
  skill_path:      <skill_path>
  input_path:      <input_path>
  output_path:     <output_path>
  kb_path:         <kb_path or "n/a">
  comparison_mode: <fast | in-depth | "n/a">
```

### Phase-specific tail — append to the base

**completed:**
```
- Use kb_path to load the knowledge base built by the orchestrator.
- Apply the docs source rule from KNOWLEDGE_BASE.md / detect-completed
  Step 4: docs-sourced matches must cite a URL present in the knowledge
  base; never infer.
```

**duplicates:**
```
- Skip Steps 1, 2, 2b, 2c of the skill — input is already on disk and
  comparison_mode is set.
- Run the detection script directly on <input_path>:
  - fast:     python3 scripts/detect_duplicates.py <input_path> --json
  - in-depth: .venv/bin/python3 scripts/detect_duplicates.py <input_path> --semantic --rerank --json
- Emit one record per duplicate-to-close with shared "group_id" and
  embedded "primary" object per the duplicates schema.
- Add a top-level "groups": <int> field to the stdout summary.
```

**spam / support / stale:** base alone — no extra tail.

---

## Step 8 — Triage summary

After all selected phases are `completed`, read state:

```
python3 scripts/triage_state.py status --product-id <id>
```

Group `actioned.jsonl` by `action`. Print:

```
## Triage Complete — [product_name]

Total open requests fetched: [N]

✅ Marked completed:        [N]
❌ Closed as duplicates:    [N]
🚫 Marked as spam:          [N]
   ↳ closed (spam fallback): [N]
❌ Closed as support:       [N]
❌ Closed as stale:         [N]
⚠️  Failed (need retry):    [N]
📋 Remaining open:          [N − total actioned]
```

---

## Step 9 — Free-form analysis (optional)

Ask:

```
Would you like me to run any further analysis on the remaining [N] open requests?

Examples:
  - Flag requests that appear to be for a different plugin or product
  - Identify requests in a specific language or region
  - Surface requests around a particular feature area or theme
  - Any other custom filter or pattern

Describe what you'd like me to look for, or type N to finish.
```

If declined: print "Triage complete. Thanks!" and stop.

### 9a — Run analysis

Build the unactioned set:
```
python3 scripts/triage_state.py filter-unactioned --product-id <id> \
  --out .triage-state/<id>/flagged/freeform.input.jsonl
```

Spawn a `general-purpose` subagent. Pass the user's stated goal, the input
path, and the output path
`.triage-state/<id>/flagged/freeform.jsonl`. The subagent processes
unactioned FRs in chunks of 50 and writes flagged records:
`{id, title, url, votes, date, reason, excerpt}`.

Present findings paged in batches of 20 per `DISPLAY.md`:

```
## Free-Form Analysis: [user's stated goal]
[N] requests analysed · [Y] flagged (showing 1–20)

[N]. ID [id] — "[title]"
     [votes] vote(s) · opened [date]
     [url]
     Reason: [one sentence]

     Excerpt: "[1–2 verbatim sentences]"
```

### 9b — Action menu

```
Found [Y] requests matching your criteria.

What would you like to do with these?

  1. What comment should I post? (describe or paste the comment text)
  2. What status should I set? (closed / spam / completed / or leave open)

You can also select a subset — reply with numbers to act on specific items
(e.g. "1 3 5"), A for all, or N to skip.
```

### 9c — Execute

Plain text only (see `RULES.md`).

For each approved FR:
1. If a comment was provided: `wccom-feature-requests-comment`.
2. If a status was provided: `wccom-feature-requests-update-status`.
3. On success, append to `actioned.jsonl` with `phase=freeform
   action=<verb> status=<new_status>`. On failure: report, do not append,
   continue.

Per-FR confirmation:
```
✔ ID [id] — "[title]": [action taken]
⚠️  ID [id] — "[title]": failed — [error]
```

### 9d — Loop

```
Anything else you'd like to analyse in the remaining [N] open requests?
(Describe what to look for, or N to finish.)
```

Repeat 9a–9d until done.

---

## Step 10 — General rules

- Bash hygiene: when running inline Python via Bash, **always use a heredoc
  with a single-quoted delimiter** — never `python3 -c "..."`. The `-c`
  form passes the script through the shell, where `!` triggers history
  expansion and `$var` references get expanded or stripped. A single-quoted
  heredoc suppresses all shell expansion:
  ```bash
  python3 << 'PYEOF'
  # safe: !=, $var, and ! all reach Python unmodified
  PYEOF
  ```
- **Never re-fetch the FR list** after Step 6. All analysis uses the cached
  working set on disk.
- **Never load the full working set into your own context.** Always operate
  on flagged outputs from subagents or paged reads.
- **Always skip actioned FRs.** Use `filter-unactioned` before every
  detection.
- **Append to `actioned.jsonl` immediately after every successful write.**
- **Wait for user confirmation** before any write action.
- **Process writes sequentially per FR** (comment first, then status).
- **Always record skips** with `action=skipped status=publish` so skipped
  FRs don't reappear on resume or re-scan.
- **Plain text comments only**, **ID display rules**, **URL carry-through**,
  **HTML entity decoding**, **non-English translation** — see
  `.claude/skills/shared/RULES.md`.
