"""Evaluate lexical search against a small, hand-judged corpus query set."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.processing.loader import load_corpus
from backend.search.engine import SearchEngine

DEFAULT_QUERIES = ROOT / "tests" / "data" / "search_relevance.json"


def ranking_metrics(
    ranked_ids: list[str], relevance: dict[str, int], k: int
) -> dict[str, float]:
    """Return precision, recall, reciprocal rank and nDCG for one query."""
    if k < 1:
        raise ValueError("k must be at least 1")
    if not relevance or any(grade < 0 for grade in relevance.values()):
        raise ValueError("relevance judgments must contain non-negative grades")

    top = ranked_ids[:k]
    relevant_found = sum(relevance.get(document_id, 0) > 0 for document_id in top)
    reciprocal_rank = next(
        (1.0 / rank for rank, document_id in enumerate(top, start=1)
         if relevance.get(document_id, 0) > 0),
        0.0,
    )

    def dcg(grades: list[int]) -> float:
        return sum((2**grade - 1) / math.log2(rank + 1) for rank, grade in enumerate(grades, start=1))

    actual = [relevance.get(document_id, 0) for document_id in top]
    ideal = sorted(relevance.values(), reverse=True)[:k]
    ideal_dcg = dcg(ideal)
    return {
        f"precision@{k}": relevant_found / k,
        f"recall@{k}": relevant_found / sum(grade > 0 for grade in relevance.values()),
        f"mrr@{k}": reciprocal_rank,
        f"ndcg@{k}": dcg(actual) / ideal_dcg if ideal_dcg else 0.0,
    }


def evaluate(
    engine: SearchEngine, cases: list[dict[str, Any]], k: int
) -> list[dict[str, Any]]:
    """Run each judged query through the engine and compute per-query metrics."""
    results = []
    for case in cases:
        query = case["query"]
        relevance = case["relevance"]
        response = engine.search(query, limit=k)
        metrics = ranking_metrics(
            [hit.document_id for hit in response.hits], relevance, k
        )
        results.append({"query": query, "metrics": metrics})
    return results


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError(f"{path} must contain a non-empty list of query judgments")
    for case in cases:
        if (
            not isinstance(case, dict)
            or not isinstance(case.get("query"), str)
            or not case["query"].strip()
            or not isinstance(case.get("relevance"), dict)
            or not case["relevance"]
            or any(not isinstance(grade, int) or grade < 0 for grade in case["relevance"].values())
        ):
            raise ValueError(f"invalid query judgment in {path}: {case!r}")
    return cases


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k", type=int, default=5, help="ranking cutoff (default: 5)")
    parser.add_argument(
        "--queries", type=Path, default=DEFAULT_QUERIES, help="JSON relevance judgments"
    )
    args = parser.parse_args()
    if args.k < 1:
        parser.error("--k must be at least 1")

    engine = SearchEngine(load_corpus())
    rows = evaluate(engine, load_cases(args.queries), args.k)
    metric_names = list(rows[0]["metrics"])
    averages = {
        name: sum(row["metrics"][name] for row in rows) / len(rows)
        for name in metric_names
    }

    print(f"BM25 relevance evaluation: {len(rows)} queries, k={args.k}")
    print(f"{'Query':48} " + " ".join(f"{name:>12}" for name in metric_names))
    for row in rows:
        print(
            f"{row['query'][:48]:48} "
            + " ".join(f"{row['metrics'][name]:12.3f}" for name in metric_names)
        )
    print(f"{'MACRO AVERAGE':48} " + " ".join(f"{averages[name]:12.3f}" for name in metric_names))


if __name__ == "__main__":
    main()
