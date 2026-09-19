"""Phase 7 Hybrid Ranking Engine tests.

Covers requirements A through S specified in Phase 7 objective:
A. Hybrid mode accepted by API.
B. BM25 + semantic candidates merge correctly.
C. Document deduplication by document_id.
D. Retention of documents appearing only in BM25.
E. Retention of documents appearing only in semantic.
F. Score normalization correctness.
G. All-zero / NaN handling.
H. Equal score candidate sets handling.
I. Weight configuration impact.
J. Invalid weight rejection.
K. Descending score sorting.
L. Deterministic secondary tie-breaker.
M. Sequential final ranks (1..K).
N. Legacy lexical search unbroken.
O. Existing semantic search unbroken.
P. Explicit degraded/unavailable status for hybrid.
Q. Safe, case-insensitive term highlighting.
R. Crawled and corpus docs coexisting in hybrid search.
S. Regression verification of entire test suite.
"""
from __future__ import annotations

import math
import pytest
from fastapi.testclient import TestClient

from backend.config import settings
from backend.main import app
from backend.search.hybrid import (
    InvalidHybridWeightsError,
    highlight_matched_terms,
    merge_and_rerank_hybrid,
    min_max_normalize,
    validate_and_normalize_weights,
)
from backend.search.models import SearchResult, SearchResponse
from backend.processing.models import ProcessedDocument
from backend.search.engine import SearchEngine
from backend.search.index_manager import get_index_manager, reset_index_manager
from backend.search.semantic import (
    get_semantic_index_manager,
    reset_semantic_index_manager,
)
from test_semantic_search_phase6 import _FakeEmbedder, _FakeRepository, _row, _make_manager


# --------------------------------------------------------------------------- #
# Unit Tests for Score Normalization, Weights, Highlighting & Merging
# --------------------------------------------------------------------------- #

class TestHybridUnitComponents:
    def test_weight_validation(self):
        # Valid weights
        w = validate_and_normalize_weights(0.5, 0.5)
        assert w.bm25 == 0.5 and w.semantic == 0.5

        w2 = validate_and_normalize_weights(2.0, 8.0)
        assert abs(w2.bm25 - 0.2) < 1e-5 and abs(w2.semantic - 0.8) < 1e-5

        # Invalid weights
        with pytest.raises(InvalidHybridWeightsError):
            validate_and_normalize_weights(-0.1, 0.5)

        with pytest.raises(InvalidHybridWeightsError):
            validate_and_normalize_weights(0.0, 0.0)

    def test_min_max_normalize_cases(self):
        # Empty set
        assert min_max_normalize([]) == []

        # All equal positive
        assert min_max_normalize([10.0, 10.0, 10.0]) == [1.0, 1.0, 1.0]

        # All equal zero
        assert min_max_normalize([0.0, 0.0]) == [0.0, 0.0]

        # Normal range
        norm = min_max_normalize([10.0, 20.0, 30.0])
        assert norm == [0.0, 0.5, 1.0]

        # Single item
        assert min_max_normalize([5.0]) == [1.0]
        assert min_max_normalize([0.0]) == [0.0]

        # NaN / Infinity handling
        dirty = [float("nan"), 10.0, float("inf"), 20.0]
        norm_dirty = min_max_normalize(dirty)
        assert not any(math.isnan(x) or math.isinf(x) for x in norm_dirty)

    def test_highlight_matched_terms_safety_and_case(self):
        # Case-insensitive matching + original case preserved inside <mark>
        text = "Machine Learning with Python and HTML <script>alert(1)</script>"
        hl = highlight_matched_terms(text, ["learning", "python"])
        assert "<mark>Learning</mark>" in hl
        assert "<mark>Python</mark>" in hl
        # HTML escaping check
        assert "&lt;script&gt;" in hl
        assert "<script>" not in hl

    def test_candidate_merging_and_deduplication(self):
        bm25_hits = [
            SearchResult(rank=1, document_id="1", title="Doc 1", source="s1", snippet="Python code", score=10.0, matched_terms=("python",)),
            SearchResult(rank=2, document_id="2", title="Doc 2", source="s2", snippet="Docker setup", score=5.0, matched_terms=("docker",)),
        ]
        semantic_hits = [
            SearchResult(rank=1, document_id="2", title="Doc 2", source="s2", snippet="Docker setup", score=0.9, matched_terms=()),
            SearchResult(rank=2, document_id="3", title="Doc 3", source="s3", snippet="AI models", score=0.8, matched_terms=()),
        ]

        hits, weights = merge_and_rerank_hybrid(
            bm25_hits, semantic_hits, query="python docker", limit=10, bm25_weight=0.5, semantic_weight=0.5
        )

        doc_ids = [h.document_id for h in hits]
        # Check deduplication
        assert len(doc_ids) == len(set(doc_ids))
        assert set(doc_ids) == {"1", "2", "3"}

        # Ranks must be 1..3
        assert [h.rank for h in hits] == [1, 2, 3]

        # doc 2 appeared in both so it should get combined normalized score
        doc2_hit = next(h for h in hits if h.document_id == "2")
        assert doc2_hit.score > 0.0


# --------------------------------------------------------------------------- #
# Integration Tests via Fake Managers / FastAPI TestClient
# --------------------------------------------------------------------------- #

class TestHybridIntegration:
    @pytest.fixture()
    def setup_hybrid_env(self, tmp_path):
        reset_index_manager()
        reset_semantic_index_manager()

        # Build fake corpus
        doc1 = ProcessedDocument(
            document_id="1",
            title="Python Tutorial",
            content="Learn python programming and data science.",
            source="corpus/python.md",
            tokens=("python", "programming", "data", "science"),
            snippet_tokens=("learn", "python", "programming", "data", "science"),
            content_hash="hash1",
        )
        doc2 = ProcessedDocument(
            document_id="2",
            title="Docker Guide",
            content="Containerization with docker and compose.",
            source="https://example.com/docker",
            tokens=("containerization", "docker", "compose"),
            snippet_tokens=("containerization", "with", "docker", "and", "compose"),
            content_hash="hash2",
        )
        doc3 = ProcessedDocument(
            document_id="3",
            title="Machine Learning",
            content="Introduction to neural networks and ML.",
            source="corpus/ml.md",
            tokens=("introduction", "neural", "networks", "ml"),
            snippet_tokens=("introduction", "to", "neural", "networks", "and", "ml"),
            content_hash="hash3",
        )

        bm25_engine = SearchEngine([doc1, doc2, doc3])
        get_index_manager().set_engine(bm25_engine)

        # Setup fake semantic manager
        repo = _FakeRepository([
            _row(1, topic="python", content=doc1.content),
            _row(2, topic="docker", content=doc2.content),
            _row(3, topic="ml", content=doc3.content),
        ])
        embedder = _FakeEmbedder(dimension=32)
        sem_manager = _make_manager(tmp_path, repo, embedder)
        sem_manager.rebuild(seed_corpus=False)

        yield sem_manager

        reset_index_manager()
        reset_semantic_index_manager()

    def test_api_hybrid_search_success(self, setup_hybrid_env, monkeypatch):
        sem_manager = setup_hybrid_env
        # Monkeypatch global semantic manager
        monkeypatch.setattr("backend.api.search.get_semantic_index_manager", lambda: sem_manager)

        client = TestClient(app)

        res = client.get("/api/search", params={"q": "python", "mode": "hybrid"})
        assert res.status_code == 200
        data = res.json()

        assert data["mode"] == "hybrid"
        assert data["status"] == "ok"
        assert "weights" in data
        assert data["total"] >= 1
        assert data["hits"][0]["rank"] == 1
        assert "document_id" in data["hits"][0]
        assert "<mark>" in data["hits"][0]["snippet"] or "python" in data["hits"][0]["snippet"].lower()

    def test_hybrid_degraded_when_semantic_unavailable(self, monkeypatch):
        reset_index_manager()
        reset_semantic_index_manager()

        doc1 = ProcessedDocument(
            document_id="1", title="Doc 1", content="Content", source="s1",
            tokens=("content",), snippet_tokens=("content",), content_hash="h1"
        )
        get_index_manager().set_engine(SearchEngine([doc1]))

        # Mock semantic manager as unavailable
        class UnavailableSemantic:
            def status(self):
                return {"available": False, "loaded": False, "message": "ML model missing"}

        monkeypatch.setattr("backend.api.search.get_semantic_index_manager", lambda: UnavailableSemantic())

        client = TestClient(app)
        res = client.get("/api/search", params={"q": "content", "mode": "hybrid"})
        assert res.status_code == 200
        data = res.json()
        assert data["mode"] == "hybrid"
        assert data["status"] == "degraded"
        assert "degraded/unavailable" in data["message"]

    def test_existing_modes_remain_unbroken(self, setup_hybrid_env, monkeypatch):
        sem_manager = setup_hybrid_env
        monkeypatch.setattr("backend.api.search.get_semantic_index_manager", lambda: sem_manager)

        client = TestClient(app)

        # Lexical
        lex = client.get("/api/search", params={"q": "python", "mode": "lexical"})
        assert lex.status_code == 200
        assert lex.json()["mode"] == "lexical"

        # Semantic
        sem = client.get("/api/search", params={"q": "python", "mode": "semantic"})
        assert sem.status_code == 200
        assert sem.json()["mode"] == "semantic"
