# Shared — End-of-Phase Loop

Every detect-* skill ends with the same loop: confirm done → offer more →
offer re-scan. This file is the single source of truth.

> **Orchestrator note:** when a skill is invoked by the triage orchestrator
> (subagent mode), it must **skip** the re-scan offer. The orchestrator
> handles re-scan itself. The subagent prompt template sets
> `mode = orchestrated`. Standalone runs use `mode = standalone` (default)
> and follow this loop in full.

---

## After the per-phase confirmation summary

Ask:

```
Would you like to action more requests from this phase? (Y / N)
```

- **Y**: re-present the confirmation menu with only the remaining un-actioned
  items from this phase, then loop through preview → execute → summary again.
- **N or empty**: continue to the re-scan offer (standalone only — skip in
  orchestrated mode).

## Re-scan offer (standalone mode only)

Substitute `<phase>` with the current phase name (e.g. "completed",
"duplicates"):

```
Run the <phase> detection again in case anything was missed, or are we done
with this phase?
(Another look / Done)
```

- **Another look**: re-run detection on all remaining non-actioned FRs. If
  new findings, loop through confirmation → preview → execute → summary →
  re-scan again.
  - **If the re-scan returns zero new flagged FRs**: print
    `_No new findings._` and end the skill. Do **not** loop back to the
    re-scan prompt again.
- **Done**: end the skill.

## Orchestrated mode

If the subagent prompt indicates `mode = orchestrated`:
- Skip the re-scan offer entirely.
- After the per-phase summary, return control. The orchestrator decides
  whether to re-scan.
