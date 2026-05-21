# WooCommerce.com Feature Requests Triage Skills

AI-powered skills for triaging Feature Requests on the WooCommerce.com Marketplace, built for [Claude Code](https://claude.ai/code).

---

## What this does

Feature requests pile up. After a product ships, some requests are already fulfilled. Others are duplicates of each other. Some are really support questions in disguise. A few are years old with almost no interest. Sorting through hundreds of open requests by hand takes hours.

This toolkit gives Claude a set of skills to do that work for you. You point it at a product, tell it what to check, and it reads every open feature request, reasons about each one, and presents findings for your review — before touching anything. You approve (or decline) each action. Nothing is changed without your say-so.

---

## Skills

### Orchestrator (recommended starting point)

**`/triage-woo-feature-requests`** — Runs a full end-to-end triage session for a product. Fetches all open feature requests once, then walks through each check in sequence, pausing for your approval at every step. At the end, it offers a free-form analysis pass where you can ask anything ("find all requests about mobile", "flag anything in Spanish", etc.).

**Use this when you want to run a complete cleanup in one sitting.**

### Individual checks

Run these on their own when you only need one specific pass:

| Skill | What it finds |
|---|---|
| `/detect-completed` | Requests already fulfilled by a shipped release or documented feature |
| `/detect-duplicates` | Requests that cover the same ground as another open request |
| `/detect-spam` | Promotional links, gibberish, off-topic |
| `/detect-support-requests` | Troubleshooting questions and bug reports filed as feature requests |
| `/detect-stale` | Requests older than 3 years with 2 or fewer votes |

All skills work the same way: they read live data, present a numbered report, and wait for your explicit approval before making any changes. You can always reply `N` to skip an action entirely.

---

## Built for hundreds of requests

The orchestrator is designed to triage products with hundreds of open feature requests without exhausting Claude's context window:

- **Disk-backed working set.** After the one-time fetch, every request is written to `.triage-state/<product_id>/working_set.jsonl` (gitignored). Phases read from disk — the full list is never loaded into Claude's chat context.
- **Per-phase subagents.** Each detection pass (completed, duplicates, spam, support, stale) runs in an isolated subagent. The subagent reads the working set from disk, chunks it internally, and returns only a compact flagged list. The main thread stays light.
- **Resumable per FR.** Every successful write is appended to `actioned.jsonl` immediately. If a run is interrupted (disconnect, compaction, machine crash), starting the orchestrator again on the same product detects the prior state, asks whether to resume, and picks up exactly where it left off — actioned FRs are skipped automatically. Explicitly skipped FRs (ones you pass on during review) are also recorded with `action=skipped`, so they never resurface on subsequent runs.
- **Cached fetch.** A second run reuses the cached working set by default and asks before re-fetching from the API.
- **State CLI.** `scripts/triage_state.py` manages `init`, `status`, `append-actioned`, `filter-unactioned`, `reset`, etc. The orchestrator drives it; you do not need to call it directly.

State layout under `.triage-state/<product_id>/`:

```
state.json            Run metadata: product, phases selected, phase_status, fetched_at
working_set.jsonl     Source of truth — every fetched FR, one per line
actioned.jsonl        Append-only log of every successful write (id, phase, action, status, ts)
knowledge_base.json   Cached changelog + docs crawl (For the Completed detection phase only)
flagged/<phase>.jsonl Per-phase detection output, before user approval
```

To start completely fresh on a product, the orchestrator offers a "start fresh" option at the resume prompt, or you can delete the product's directory under `.triage-state/`.

---

## How the orchestrator works (behind the scenes)

When you run `/triage-woo-feature-requests` with a product URL or ID, here is what happens:

1. **Product lookup** — Claude resolves the product ID from the URL and fetches the product name. A read-only request confirms the product has open feature requests; the first real write action will surface a permission error if your credentials do not own the product, and the orchestrator stops.

2. **Phase selection** — Claude shows a menu of the five checks and asks which ones to run. Press Enter to run all five.

3. **Knowledge base** (if "Completed" is selected) — Claude fetches the product's full changelog from the WooCommerce API, then crawls the product's documentation pages (up to 20 sub-pages) to build a picture of what is currently supported. This is used later to match against open requests.

4. **Single fetch** — Claude fetches every open feature request for the product in one go, paginating through the API until it has the full list. This list is reused across all phases — the API is not called again.

5. **Sequential phases** — Claude runs each selected check against the cached list. Each phase presents findings, waits for your approval, executes approved actions, then summarises what was done before moving to the next phase. Requests already actioned in a prior phase are automatically skipped.

6. **Triage summary** — After all phases, Claude prints a count of everything that was actioned across the session.

7. **Free-form analysis** — Claude offers to run any custom analysis you describe against the remaining open requests. You can ask multiple questions in sequence before finishing.

---

## Getting started

### What you need

- **Claude Code** — [Install instructions](https://docs.anthropic.com/claude-code)
- **Access to WooCommerce.com (admin or vendor)** 
- **WooCommerce REST API keys** with Read/Write permissions for the product you want to triage
- **Python 3**

### 0. Clone this repository

In the terminal, run:

```
git clone https://github.com/woocommerce/wccom-feature-requests-triage-skills.git
cd wccom-feature-requests-triage-skills
```

### 1. Generate API keys

**WooCommerce → Settings → Advanced → REST API → Add Key**

Set permissions to `Read/Write`, save, and copy the consumer key and consumer secret.

### 2. Add the MCP server to Claude Code

Open (or create) your Claude Code MCP configuration file (`~/.claude/mcp.json` or the project-level `.claude/mcp.json`) and add an entry:

```json
"wccom-feature-requests": {
  "url": "https://woocommerce.com/wp-json/woocommerce/mcp",
  "headers": {
    "X-MCP-API-Key": "ck_xxxx:cs_xxxx"
  }
}
```

Replace `ck_xxxx:cs_xxxx` with the keys from step 1 in the format `consumer_key:consumer_secret`.


### 3. Restart Claude Code

Restart Claude Code (or reload the MCP servers) so it picks up the new server configuration.

### 4. (Optional): Set up Python dependencies for in-depth duplicate requests detection

In the terminal, run:

```
python3 -m venv .venv
.venv/bin/pip install scikit-learn scipy sentence-transformers
```

### 5. Run the orchestrator

In Claude Code, type:

```
/triage-woo-feature-requests https://woocommerce.com/products/your-product/
```

You can also pass the numeric product ID directly if you know it:

```
/triage-woo-feature-requests 12345
```

Claude will confirm the product, ask which phases to run, and walk you through the rest.

---

## Python dependency

The `/detect-duplicates` skill (and the Duplicates phase of the orchestrator) runs `scripts/detect_duplicates.py` automatically as part of its analysis. **Python 3 must be available on your machine.**

### How duplicate detection works

1. Claude writes all fetched feature requests to a temp JSONL file.
2. It runs `scripts/detect_duplicates.py` to get an initial set of duplicate groups.
   - **Fast mode:** TF-IDF similarity (title-level and full-text). No extra dependencies.
   - **In-depth mode:** `--semantic --rerank` — bi-encoder embeddings (`BAAI/bge-small-en-v1.5`) for candidate generation, then cross-encoder reranking (`BAAI/bge-reranker-base`) for precision.
3. Claude reviews those groups — pruning false positives and adjudicating borderline pairs.
4. The merged result is presented for your review.

**Fast mode** requires `scikit-learn` and `scipy` (falls back to a slower stdlib implementation if unavailable). **In-depth mode** additionally requires `sentence-transformers`. A `.venv` is included in the repo with all dependencies pre-installed:

```
# One-time setup
python3 -m venv .venv
.venv/bin/pip install scikit-learn scipy sentence-transformers
```

Models for in-depth mode are downloaded automatically on first run (~90 MB for the bi-encoder, ~1 GB for the cross-encoder).

If `python3` is not found or the script fails, the skill falls back to Claude's own reasoning for duplicate detection and notes the fallback in its output.

### `scripts/save_frs.py`

A utility for merging paged API result files into a single JSONL file. The orchestrator's fetch subagent calls it after paging through the feature requests API to build `working_set.jsonl`. Also usable standalone for offline workflows.

```
python3 scripts/save_frs.py page1.txt page2.txt -o frs.jsonl
```

---

## Notes

- **Non-English requests** — the orchestrator and all skills detect the language of each request. Non-English titles and excerpts are displayed with an inline translation so you can review them without switching tools.
- **Write safety** — every write action (posting a comment, updating a status) requires explicit approval. The orchestrator verifies API write access before starting, and will stop with a clear error if your credentials do not own the product.
- **Re-scan option** — after each phase completes, Claude offers to take another look in case anything was missed before moving on.
