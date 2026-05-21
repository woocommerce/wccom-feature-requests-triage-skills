#!/usr/bin/env python3
"""
detect_duplicates.py — Find duplicate feature requests.

Detection modes (auto-selected):
  1. TF-IDF dual-signal  (requires scikit-learn, default)
     Title-only AND full-text TF-IDF via sparse matmul. Fast even at N=5000.
     Catches same-wording duplicates. Misses pure semantic rewrites.

  2. Sentence-transformer + optional cross-encoder  (--semantic)
     Bi-encoder embeddings for candidate generation; pair extraction via
     numpy triu_indices (no Python loops). Optional cross-encoder reranking
     (--rerank) retrieves top-K neighbors per FR, re-scores with a
     cross-encoder, then clusters via complete-linkage (every pair in a
     group must clear the strict threshold). Near-misses are surfaced as
     borderline_pairs for manual review.

     Embedded text: "{title}. {title}. {description}" — title doubled to
     dominate when description is short/missing; description falls back to
     title when empty so zero-description FRs still encode signal.

Usage:
    python3 detect_duplicates.py <input.jsonl> [options]

    python3 detect_duplicates.py frs.jsonl
    python3 detect_duplicates.py frs.jsonl --threshold 0.45
    python3 detect_duplicates.py frs.jsonl --semantic
    python3 detect_duplicates.py frs.jsonl --semantic --rerank
    python3 detect_duplicates.py frs.jsonl --json

Input:
    JSONL — one FR per line:
    {"id": 123, "title": "...", "description": "...", "votes": 5, "date": "...", "url": "..."}

Output (--json):
    {"groups": [...], "borderline_pairs": [...]}

    groups: duplicate clusters, sorted by confidence then primary vote count.
    borderline_pairs: near-miss pairs below the group threshold for manual review.
      Each pair: {"similarity": 0.58, "fr_a": {...}, "fr_b": {...}}
"""

import argparse
import json
import math
import re
import sys
from collections import defaultdict


# ---------------------------------------------------------------------------
# Stopwords — common English + WooCommerce noise words
# ---------------------------------------------------------------------------
STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "it", "this", "that", "be", "are",
    "was", "were", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "i", "we", "you", "they",
    "he", "she", "my", "our", "your", "their", "not", "no", "so", "as",
    "if", "then", "when", "where", "how", "what", "which", "who", "can",
    "please", "want", "need", "like", "great", "good", "also", "very",
    "just", "really", "currently", "now",
    # WooCommerce noise — appear in nearly every FR, carry no signal
    "woocommerce", "woo", "plugin", "extension",
    "subscription", "subscriptions",
    "product", "products", "store", "shop",
    "option", "feature", "request",
    "add", "allow", "enable", "support", "new", "use", "get", "make",
    "would", "able", "way",
}


# ---------------------------------------------------------------------------
# Union-Find
# ---------------------------------------------------------------------------

class UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, x: int, y: int) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self.rank[rx] < self.rank[ry]:
            rx, ry = ry, rx
        self.parent[ry] = rx
        if self.rank[rx] == self.rank[ry]:
            self.rank[rx] += 1


# ---------------------------------------------------------------------------
# Exact-title duplicate detection
# ---------------------------------------------------------------------------

def find_exact_title_duplicates(frs: list[dict]) -> list[dict]:
    """
    Groups FRs whose normalized titles are identical.
    Always High confidence. Runs before TF-IDF so these pairs are never missed
    even when short titles produce weak TF-IDF vectors after stopword removal.
    """
    def normalize(title: str) -> str:
        t = title.lower().strip()
        t = re.sub(r"[^\w\s]", " ", t)
        return re.sub(r"\s+", " ", t).strip()

    buckets: dict[str, list[int]] = defaultdict(list)
    for i, fr in enumerate(frs):
        key = normalize(fr.get("title", ""))
        if key:
            buckets[key].append(i)

    groups = []
    for indices in buckets.values():
        if len(indices) < 2:
            continue
        sorted_indices = sorted(
            indices,
            key=lambda i: (-frs[i]["votes"], frs[i].get("date", "")),
        )
        primary_idx = sorted_indices[0]
        groups.append({
            "confidence": "high",
            "max_similarity": 1.0,
            "primary": _summary(frs[primary_idx]),
            "duplicates": [_summary(frs[i]) for i in sorted_indices[1:]],
        })
    return groups


def _get_exact_title_seed_pairs(frs: list[dict]) -> list[tuple[int, int, float]]:
    """Return (i, j, 1.0) for every pair of FRs with identical normalized titles.

    Used in semantic mode as forced graph edges so exact-title matches are
    still clustered together even though those FRs are no longer excluded from
    the semantic corpus.
    """
    def normalize(title: str) -> str:
        t = title.lower().strip()
        t = re.sub(r"[^\w\s]", " ", t)
        return re.sub(r"\s+", " ", t).strip()

    buckets: dict[str, list[int]] = defaultdict(list)
    for i, fr in enumerate(frs):
        key = normalize(fr.get("title", ""))
        if key:
            buckets[key].append(i)

    pairs: list[tuple[int, int, float]] = []
    for indices in buckets.values():
        if len(indices) >= 2:
            for a in range(len(indices)):
                for b in range(a + 1, len(indices)):
                    pairs.append((indices[a], indices[b], 1.0))
    return pairs


# ---------------------------------------------------------------------------
# TF-IDF duplicate detection (sklearn sparse matmul)
# ---------------------------------------------------------------------------

def find_duplicates_tfidf(
    frs: list[dict],
    title_threshold: float = 0.50,
    full_threshold: float = 0.45,
    high_threshold: float = 0.65,
) -> tuple[list[dict], list[dict]]:
    """
    Dual-signal TF-IDF via sklearn sparse matmul — fast even at N=5000.
    Title-only and full-text similarity computed separately; pair flagged if
    either exceeds its threshold.
    Returns (groups, []) — TF-IDF mode produces no borderline pairs.
    """
    if not frs:
        return [], []

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from scipy.sparse import triu as sp_triu
    except ImportError:
        print(
            "WARNING: scikit-learn not installed, falling back to stdlib TF-IDF.\n"
            "Run: pip install scikit-learn scipy",
            file=sys.stderr,
        )
        return _find_duplicates_tfidf_stdlib(frs, title_threshold, full_threshold, high_threshold)

    titles = [fr.get("title", "") for fr in frs]
    fulls = [
        f"{fr.get('title','')} {fr.get('title','')} {fr.get('title','')} {fr.get('description','')}"
        for fr in frs
    ]

    vec_t = TfidfVectorizer(
        ngram_range=(1, 2), min_df=1, max_df=0.95,
        sublinear_tf=True, stop_words=list(STOPWORDS),
    )
    vec_f = TfidfVectorizer(
        ngram_range=(1, 2), min_df=1, max_df=0.95,
        sublinear_tf=True, stop_words=list(STOPWORDS),
    )
    T = vec_t.fit_transform(titles)
    F = vec_f.fit_transform(fulls)

    S_title = sp_triu(T @ T.T, k=1).tocoo()
    S_full = sp_triu(F @ F.T, k=1).tocoo()

    pair_scores: dict[tuple[int, int], float] = {}
    for i, j, s in zip(S_title.row, S_title.col, S_title.data):
        if s >= title_threshold:
            pair_scores[(int(i), int(j))] = float(s)
    for i, j, s in zip(S_full.row, S_full.col, S_full.data):
        if s >= full_threshold:
            key = (int(i), int(j))
            pair_scores[key] = max(pair_scores.get(key, 0.0), float(s))

    uf = UnionFind(len(frs))
    for i, j in pair_scores:
        uf.union(i, j)

    return _build_groups(frs, uf, pair_scores, high_threshold), []


def _find_duplicates_tfidf_stdlib(
    frs: list[dict],
    title_threshold: float,
    full_threshold: float,
    high_threshold: float,
) -> tuple[list[dict], list[dict]]:
    """Stdlib fallback for TF-IDF when scikit-learn is unavailable."""

    def tokenize(text: str) -> list[str]:
        text = text.lower()
        text = re.sub(r"[^\w\s]", " ", text)
        return [t for t in text.split() if len(t) > 2 and t not in STOPWORDS]

    def with_bigrams(tokens: list[str]) -> list[str]:
        return tokens + [f"{tokens[i]}_{tokens[i+1]}" for i in range(len(tokens) - 1)]

    def tfidf_vectors(docs):
        n = len(docs)
        df: dict[str, int] = defaultdict(int)
        for doc in docs:
            for term in set(doc):
                df[term] += 1
        idf = {t: math.log((n + 1) / (c + 1)) + 1 for t, c in df.items()}
        vectors = []
        for doc in docs:
            if not doc:
                vectors.append({})
                continue
            tf: dict[str, float] = defaultdict(float)
            for term in doc:
                tf[term] += 1
            length = len(doc)
            vectors.append({t: (c / length) * idf[t] for t, c in tf.items()})
        return vectors

    def cosine(v1, v2):
        if not v1 or not v2:
            return 0.0
        dot = sum(v1.get(k, 0.0) * v for k, v in v2.items())
        n1 = math.sqrt(sum(x * x for x in v1.values()))
        n2 = math.sqrt(sum(x * x for x in v2.values()))
        return dot / (n1 * n2) if n1 and n2 else 0.0

    title_docs = [with_bigrams(tokenize(fr.get("title", ""))) for fr in frs]
    full_docs = [
        with_bigrams(tokenize(fr.get("title", "")) * 3 + tokenize(fr.get("description", "")))
        for fr in frs
    ]
    title_vecs = tfidf_vectors(title_docs)
    full_vecs = tfidf_vectors(full_docs)

    n = len(frs)
    uf = UnionFind(n)
    pair_scores: dict[tuple[int, int], float] = {}
    for i in range(n):
        for j in range(i + 1, n):
            t_sim = cosine(title_vecs[i], title_vecs[j])
            f_sim = cosine(full_vecs[i], full_vecs[j])
            sim = max(t_sim if t_sim >= title_threshold else 0,
                      f_sim if f_sim >= full_threshold else 0)
            if sim > 0:
                uf.union(i, j)
                pair_scores[(i, j)] = sim
    return _build_groups(frs, uf, pair_scores, high_threshold), []


# ---------------------------------------------------------------------------
# Sentence-transformer duplicate detection (semantic)
# ---------------------------------------------------------------------------

def _find_tight_clusters(
    pair_scores: dict[tuple[int, int], float],
    threshold: float,
) -> list[list[int]]:
    """Complete-linkage clustering: groups where ALL pairwise scores >= threshold.

    Processes pairs in descending score order. A new FR is added to an existing
    group only when it meets the threshold with every current member — no
    single-link transitivity chains. This prevents mega-components on
    single-topic products (e.g. all-bookings corpus).
    """
    sorted_pairs = sorted(
        [(i, j, s) for (i, j), s in pair_scores.items() if s >= threshold],
        key=lambda x: -x[2],
    )
    group_of: dict[int, int] = {}
    groups: list[set] = []

    for i, j, _ in sorted_pairs:
        gi = group_of.get(i)
        gj = group_of.get(j)

        if gi is None and gj is None:
            idx = len(groups)
            groups.append({i, j})
            group_of[i] = idx
            group_of[j] = idx
        elif gi is None:
            g = groups[gj]
            if all(pair_scores.get((min(i, m), max(i, m)), 0.0) >= threshold for m in g):
                g.add(i)
                group_of[i] = gj
        elif gj is None:
            g = groups[gi]
            if all(pair_scores.get((min(j, m), max(j, m)), 0.0) >= threshold for m in g):
                g.add(j)
                group_of[j] = gi
        elif gi != gj:
            ga, gb = groups[gi], groups[gj]
            if all(pair_scores.get((min(a, b), max(a, b)), 0.0) >= threshold for a in ga for b in gb):
                for m in list(gb):
                    group_of[m] = gi
                ga.update(gb)
                groups[gj] = set()

    return [list(g) for g in groups if len(g) >= 2]


def _make_group(
    frs: list[dict],
    member_indices: list[int],
    pair_scores: dict[tuple[int, int], float],
    high_threshold: float,
) -> dict:
    max_sim = max(
        (pair_scores.get((min(a, b), max(a, b)), 0.0) for a in member_indices for b in member_indices if a != b),
        default=0.0,
    )
    sorted_members = sorted(
        member_indices,
        key=lambda i: (-frs[i]["votes"], frs[i].get("date", "")),
    )
    return {
        "confidence": "high" if max_sim >= high_threshold else "low",
        "max_similarity": round(max_sim, 3),
        "primary": _summary(frs[sorted_members[0]]),
        "duplicates": [_summary(frs[i]) for i in sorted_members[1:]],
    }


def _build_tight_groups(
    frs: list[dict],
    pair_scores: dict[tuple[int, int], float],
    strict_threshold: float,
    high_threshold: float,
    max_component_size: int = 15,
) -> list[dict]:
    """Complete-linkage clustering at strict_threshold.

    Every candidate group has ALL pairwise scores >= strict_threshold — no
    single-link transitivity chains that cause mega-components on single-topic
    products. Pairs below strict_threshold surface as borderline_pairs for
    manual review instead.
    """
    candidates = _find_tight_clusters(pair_scores, strict_threshold)
    print(
        f"  Tight clusters at {strict_threshold}: {len(candidates)} candidate group(s)",
        file=sys.stderr,
    )

    final_groups: list[dict] = []
    for members in candidates:
        if len(members) < 2:
            continue
        if len(members) > max_component_size:
            print(
                f"  WARNING: {len(members)}-member tight cluster exceeds "
                f"max_component_size={max_component_size}; discarding.",
                file=sys.stderr,
            )
            continue
        final_groups.append(_make_group(frs, members, pair_scores, high_threshold))

    final_groups.sort(key=lambda g: (g["confidence"] != "high", -g["primary"]["votes"]))
    return final_groups


def _embed_text(fr: dict) -> str:
    """Build the string passed to the bi-encoder.

    Title is repeated twice so it dominates over a short/missing description.
    When description is absent, the title fills the body slot too — prevents
    zero-description FRs from embedding as near-zero vectors.
    """
    title = fr.get("title", "")
    desc = fr.get("description", "").strip()
    body = desc[:2000] if desc else title
    return f"{title}. {title}. {body}"


def _cross_encode(
    texts: list[str],
    candidate_pairs: list[tuple[int, int, float]],
) -> list[tuple[int, int, float]]:
    """Re-score candidate pairs with a cross-encoder. Returns updated pairs."""
    try:
        from sentence_transformers import CrossEncoder
    except ImportError:
        print("WARNING: CrossEncoder not available, skipping rerank.", file=sys.stderr)
        return candidate_pairs

    est_secs = len(candidate_pairs) * 0.03
    print(
        f"Cross-encoding {len(candidate_pairs)} pairs (~{est_secs:.0f}s on CPU)...",
        file=sys.stderr,
    )
    ce = CrossEncoder("BAAI/bge-reranker-base")
    pair_texts = [(texts[i], texts[j]) for i, j, _ in candidate_pairs]
    # CrossEncoder.predict() already applies sigmoid for num_labels=1 models
    # (bge-reranker-base included) — do NOT re-apply sigmoid here.
    raw_scores = ce.predict(pair_texts, batch_size=64, show_progress_bar=True)

    return [
        (i, j, float(score))
        for (i, j, _), score in zip(candidate_pairs, raw_scores)
    ]


def find_duplicates_semantic(
    frs: list[dict],
    threshold: float = 0.60,
    high_threshold: float = 0.82,
    borderline_low: float = 0.50,
    rerank: bool = False,
    top_k: int = 10,
    ce_threshold: float = 0.35,        # cross-encoder score to create a group edge
    ce_strict_threshold: float = 0.55, # complete-linkage threshold for grouping
    ce_high_threshold: float = 0.70,   # cross-encoder score for "high" confidence
    ce_borderline_low: float = 0.25,   # cross-encoder lower bound for borderline output
    ce_candidate_min: float = 0.30,    # bi-encoder pre-filter before cross-encoding
    seed_pairs: list[tuple[int, int, float]] | None = None,
    borderline_cap: int = 50,
    save_pairs: str | None = None,     # path to save all_pair_scores JSON (for threshold tuning)
    load_pairs: str | None = None,     # path to load pre-computed pair scores (skip cross-encoding)
) -> tuple[list[dict], list[dict]]:
    """
    Bi-encoder candidate generation + optional cross-encoder reranking.

    Pair extraction uses numpy triu_indices (no Python loops over pairs).
    With --rerank: top_k neighbors per FR (via argpartition) bound the
    cross-encoder input to N*top_k/2 pairs regardless of score distribution.
    Pairs are clustered via complete-linkage at ce_strict_threshold; pairs
    between ce_borderline_low and ce_strict_threshold are returned as
    borderline_pairs for manual review.

    Returns (groups, borderline_pairs).
    """
    try:
        from sentence_transformers import SentenceTransformer
        import numpy as np
    except ImportError:
        print(
            "ERROR: sentence-transformers not installed.\n"
            "Run: pip install sentence-transformers\n"
            "Falling back to TF-IDF mode.",
            file=sys.stderr,
        )
        return find_duplicates_tfidf(frs)

    model = SentenceTransformer("BAAI/bge-small-en-v1.5")
    texts = [_embed_text(fr) for fr in frs]
    print(f"Encoding {len(texts)} FRs...", file=sys.stderr)
    embeddings = model.encode(texts, normalize_embeddings=True, batch_size=64, show_progress_bar=True)

    sim_matrix = np.dot(embeddings, embeddings.T)
    n = len(frs)

    if rerank:
        if load_pairs:
            print(f"Loading pair scores from {load_pairs}...", file=sys.stderr)
            with open(load_pairs) as f:
                raw = json.load(f)
            all_pair_scores: dict[tuple[int, int], float] = {
                (int(k.split(",")[0]), int(k.split(",")[1])): v
                for k, v in raw.items()
            }
            for i, j, score in (seed_pairs or []):
                key = (min(i, j), max(i, j))
                all_pair_scores[key] = max(all_pair_scores.get(key, 0.0), score)
        else:
            # top-K neighbors per FR via argpartition — O(N·K), no full sort needed.
            # argpartition requires kth in [0, n-1]; when top_k+1 >= n we want all neighbors,
            # so fall back to a full sort to avoid the out-of-bounds error.
            if top_k + 1 >= n:
                top_k_idx = np.argsort(-sim_matrix, axis=1)
            else:
                k = top_k + 1
                top_k_idx = np.argpartition(-sim_matrix, k, axis=1)[:, :k]
            candidate_set: set[tuple[int, int]] = set()
            for i in range(n):
                for j in top_k_idx[i]:
                    if i == j:
                        continue
                    a, b = (i, int(j)) if i < int(j) else (int(j), i)
                    if sim_matrix[a, b] >= ce_candidate_min:
                        candidate_set.add((a, b))
            candidate_pairs = [(a, b, float(sim_matrix[a, b])) for a, b in candidate_set]
            candidate_pairs = _cross_encode(texts, candidate_pairs)

            # Merge seed pairs (exact-title matches) with cross-encoder pairs.
            all_pair_scores = {}
            for i, j, score in candidate_pairs:
                key = (min(i, j), max(i, j))
                all_pair_scores[key] = max(all_pair_scores.get(key, 0.0), score)
            for i, j, score in (seed_pairs or []):
                key = (min(i, j), max(i, j))
                all_pair_scores[key] = max(all_pair_scores.get(key, 0.0), score)

            if save_pairs:
                print(f"Saving pair scores to {save_pairs}...", file=sys.stderr)
                with open(save_pairs, "w") as f:
                    json.dump({f"{i},{j}": s for (i, j), s in all_pair_scores.items()}, f)

        # Complete-linkage clustering at strict threshold.
        groups = _build_tight_groups(
            frs, all_pair_scores,
            strict_threshold=ce_strict_threshold,
            high_threshold=ce_high_threshold,
        )

        grouped_ids: set[int] = {g["primary"]["id"] for g in groups}
        grouped_ids |= {d["id"] for g in groups for d in g["duplicates"]}

        borderline_raw: list[dict] = []
        for (i, j), score in all_pair_scores.items():
            if score >= ce_borderline_low and score < ce_strict_threshold:
                if frs[i]["id"] not in grouped_ids and frs[j]["id"] not in grouped_ids:
                    borderline_raw.append({
                        "similarity": round(score, 3),
                        "fr_a": _summary(frs[i]),
                        "fr_b": _summary(frs[j]),
                    })

        borderline_raw.sort(key=lambda p: -p["similarity"])
        return groups, borderline_raw[:borderline_cap]
    else:
        # Vectorized pair extraction via triu_indices — no Python loop over pairs.
        iu, ju = np.triu_indices(n, k=1)
        sims = sim_matrix[iu, ju]
        mask = sims >= borderline_low
        candidate_pairs = list(zip(
            iu[mask].tolist(), ju[mask].tolist(), sims[mask].tolist()
        ))

        uf = UnionFind(n)
        pair_scores: dict[tuple[int, int], float] = {}
        borderline_raw = []

        for i, j, score in candidate_pairs:
            if score >= threshold:
                uf.union(i, j)
                pair_scores[(i, j)] = score
            elif score >= borderline_low:
                borderline_raw.append({
                    "similarity": round(score, 3),
                    "fr_a": _summary(frs[i]),
                    "fr_b": _summary(frs[j]),
                })

        groups = _build_groups(frs, uf, pair_scores, high_threshold)
        borderline_raw.sort(key=lambda p: -p["similarity"])
        return groups, borderline_raw


# ---------------------------------------------------------------------------
# Shared group builder
# ---------------------------------------------------------------------------

def _build_groups(
    frs: list[dict],
    uf: UnionFind,
    pair_scores: dict[tuple[int, int], float],
    high_threshold: float,
) -> list[dict]:
    clusters: dict[int, list[int]] = defaultdict(list)
    for i in range(len(frs)):
        clusters[uf.find(i)].append(i)

    groups = []
    for members in clusters.values():
        if len(members) < 2:
            continue

        max_sim = max(
            pair_scores.get((min(a, b), max(a, b)), 0.0)
            for a in members for b in members if a != b
        )

        sorted_members = sorted(
            members,
            key=lambda i: (-frs[i]["votes"], frs[i].get("date", "")),
        )
        primary_idx = sorted_members[0]

        groups.append({
            "confidence": "high" if max_sim >= high_threshold else "low",
            "max_similarity": round(max_sim, 3),
            "primary": _summary(frs[primary_idx]),
            "duplicates": [_summary(frs[i]) for i in sorted_members[1:]],
        })

    groups.sort(key=lambda g: (g["confidence"] != "high", -g["primary"]["votes"]))
    return groups


def _summary(fr: dict) -> dict:
    return {
        "id": fr["id"],
        "title": fr["title"],
        "votes": fr["votes"],
        "date": fr.get("date", ""),
        "url": fr.get("url", ""),
    }


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def load_jsonl(path: str) -> list[dict]:
    frs = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                frs.append(json.loads(line))
    return frs


def print_human(groups: list[dict], borderline_pairs: list[dict], total: int) -> None:
    closeable = sum(len(g["duplicates"]) for g in groups)
    high_count = sum(1 for g in groups if g["confidence"] == "high")
    low_count = len(groups) - high_count

    print(
        f"\n{total} FRs · {len(groups)} groups · {closeable} closeable "
        f"({high_count} high-confidence, {low_count} low-confidence)"
        f"{f' · {len(borderline_pairs)} borderline pairs' if borderline_pairs else ''}\n"
    )
    for idx, g in enumerate(groups, 1):
        p = g["primary"]
        print(f"Group {idx}  [{g['confidence'].upper()}  sim={g['max_similarity']}]")
        print(f"  ✅ Keep:  ID {p['id']} — \"{p['title'][:65]}\" ({p['votes']}v · {p['date'][:10]})")
        print(f"           {p['url']}")
        for d in g["duplicates"]:
            print(f"  ❌ Close: ID {d['id']} — \"{d['title'][:65]}\" ({d['votes']}v · {d['date'][:10]})")
            print(f"           {d['url']}")
        print()

    if borderline_pairs:
        print(f"\n--- Borderline pairs ({len(borderline_pairs)}) — for manual review ---")
        for p in borderline_pairs:
            print(f"  sim={p['similarity']}  ID {p['fr_a']['id']} \"{p['fr_a']['title'][:50]}\"")
            print(f"              ID {p['fr_b']['id']} \"{p['fr_b']['title'][:50]}\"")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find duplicate WooCommerce feature requests."
    )
    parser.add_argument("input", help="JSONL file of feature requests")
    parser.add_argument(
        "--threshold", type=float, default=0.50,
        help="Title similarity threshold (TF-IDF mode, default: 0.50)",
    )
    parser.add_argument(
        "--full-threshold", type=float, default=0.45,
        help="Full-text similarity threshold (TF-IDF mode, default: 0.45)",
    )
    parser.add_argument(
        "--high-threshold", type=float, default=0.65,
        help="Threshold above which confidence is 'high' (TF-IDF mode, default: 0.65)",
    )
    parser.add_argument(
        "--semantic", action="store_true",
        help="Use sentence-transformer embeddings instead of TF-IDF (requires sentence-transformers)",
    )
    parser.add_argument(
        "--rerank", action="store_true",
        help="Cross-encoder reranking of semantic candidates (requires --semantic; improves precision)",
    )
    parser.add_argument(
        "--top-k", type=int, default=50,
        help="Top-K neighbors per FR passed to cross-encoder (--rerank mode only, default: 50)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help='Output JSON object: {"groups": [...], "borderline_pairs": [...]}',
    )
    parser.add_argument(
        "--strict-threshold", type=float, default=None,
        help="Complete-linkage threshold for grouping (--rerank mode, default: 0.55). "
             "Higher = fewer but more precise groups.",
    )
    parser.add_argument(
        "--save-pairs", type=str, default=None,
        help="Save cross-encoder pair scores to this JSON file (for threshold tuning without re-encoding)",
    )
    parser.add_argument(
        "--load-pairs", type=str, default=None,
        help="Load pre-computed pair scores from this JSON file (skips cross-encoding step)",
    )
    args = parser.parse_args()

    frs = load_jsonl(args.input)
    print(f"Loaded {len(frs)} FRs.", file=sys.stderr)

    if args.semantic:
        # In semantic mode: run on the FULL corpus. Exact-title pairs are
        # injected as forced graph edges (score 1.0) so identical-title FRs
        # are still clustered together, but the FRs themselves remain in the
        # bi-encoder corpus so they can also form edges to other FRs
        # (e.g. "WooBooking" can now reach "Recurring Bookings").
        exact_seed_pairs = _get_exact_title_seed_pairs(frs)
        mode = "bge-small-en-v1.5"
        if args.rerank:
            mode += " + bge-reranker-base"
        print(f"Mode: {mode}", file=sys.stderr)
        kwargs: dict = dict(
            rerank=args.rerank,
            top_k=args.top_k,
            seed_pairs=exact_seed_pairs,
            save_pairs=args.save_pairs,
            load_pairs=args.load_pairs,
        )
        if args.strict_threshold is not None:
            kwargs["ce_strict_threshold"] = args.strict_threshold
        groups, borderline_pairs = find_duplicates_semantic(frs, **kwargs)
    else:
        if args.rerank:
            print("WARNING: --rerank has no effect without --semantic", file=sys.stderr)
        # TF-IDF mode: keep old exact-title-first, filter-remaining behaviour.
        exact_groups = find_exact_title_duplicates(frs)
        exact_ids: set[int] = set()
        for g in exact_groups:
            exact_ids.add(g["primary"]["id"])
            for d in g["duplicates"]:
                exact_ids.add(d["id"])
        remaining = [fr for fr in frs if fr["id"] not in exact_ids]
        print("Mode: exact-title + TF-IDF (sklearn sparse matmul)", file=sys.stderr)
        sim_groups, borderline_pairs = find_duplicates_tfidf(
            remaining,
            title_threshold=args.threshold,
            full_threshold=args.full_threshold,
            high_threshold=args.high_threshold,
        )
        groups = exact_groups + sim_groups
        groups.sort(key=lambda g: (g["confidence"] != "high", -g["primary"]["votes"]))

    if args.json:
        print(json.dumps({"groups": groups, "borderline_pairs": borderline_pairs}, indent=2))
    else:
        print_human(groups, borderline_pairs, len(frs))


if __name__ == "__main__":
    main()
