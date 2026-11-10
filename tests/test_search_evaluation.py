from scripts.evaluate_search import ranking_metrics


def test_ranking_metrics_reward_relevant_documents_at_the_top():
    metrics = ranking_metrics(
        ["relevant", "partial", "irrelevant"],
        {"relevant": 2, "partial": 1},
        3,
    )

    assert metrics["precision@3"] == 2 / 3
    assert metrics["recall@3"] == 1
    assert metrics["mrr@3"] == 1
    assert metrics["ndcg@3"] == 1


def test_ranking_metrics_are_zero_when_nothing_relevant_is_retrieved():
    metrics = ranking_metrics(["other"], {"relevant": 1}, 5)

    assert metrics == {
        "precision@5": 0,
        "recall@5": 0,
        "mrr@5": 0,
        "ndcg@5": 0,
    }


def test_ranking_metrics_reject_invalid_cutoff_and_empty_judgments():
    import pytest

    with pytest.raises(ValueError, match="k must"):
        ranking_metrics([], {"relevant": 1}, 0)
    with pytest.raises(ValueError, match="judgments"):
        ranking_metrics([], {}, 1)
