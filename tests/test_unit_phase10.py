"""Phase 10 - unit coverage for processing, search, AI, DB and crawler internals.

This module is the *complementary* half of the per-phase suites that already
ship in ``tests/``. It does not repeat them: ``test_search_phase2.py`` pins the
end-to-end Phase 2 contract, ``test_search_modes_phase9.py`` pins mode
behaviour, ``test_crawler_phase4.py`` drives a real local HTTP server, and so
on. What follows is the *branch* coverage those suites cannot reach without a
live database, a real crawler run or a model download:

* every documented **degenerate input** of the pure functions (empty corpus,
  unknown term, misaligned token lists, NaN/inf scores, all-equal scores);
* every documented **unavailable/degraded** path (PostgreSQL down, embedding
  stack absent, LLM provider failing, robots.txt unreachable);
* the **crash-proofing** branches the code documents but the happy path never
  reaches (``except SQLAlchemyError``, ``except LLMProviderError``,
  ``except json.JSONDecodeError`` ...).

Everything here is offline and deterministic: no model is downloaded, no
socket leaves the process (the HTTP clients are hand-written stubs) and no test
touches the committed ``indexes/`` tree.
"""
from __future__ import annotations

import asyncio
import json
import math
import pickle
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.exc import SQLAlchemyError

from backend.ai import providers as ai_providers
from backend.ai.models import (
    AnswerRequest,
    AnswerResponse,
    ContextPassage,
    GenerationMetadata,
    RetrievalMetadata,
    SourceCitation,
)
from backend.ai.pipeline import (
    construct_grounded_prompt,
    extract_and_select_passages,
)
from backend.ai.pipeline import _clean_snippet_text
from backend.ai.providers import (
    FakeLLMProvider,
    LLMProviderError,
    OllamaLLMProvider,
    get_llm_provider,
)
from backend.ai.rag import (
    _build_fallback_response,
    _filter_valid_citations,
    generate_rag_answer,
)
from backend.config import Settings, settings
from backend.crawler.extract import chunk_text, extract_text, extract_title, hash_text
from backend.crawler.fetcher import (
    ERR_NON_HTML,
    ERR_REDIRECTS,
    ERR_TIMEOUT,
    ERR_TOO_LARGE,
    ERR_TRANSPORT,
    fetch,
)
from backend.crawler.models import (
    CrawlJob,
    CrawlJobConfig,
    CrawlPage,
    CrawlReport,
    CrawlStatus,
    FailedFetch,
)
from backend.crawler.robots import RobotsTxtPolicy
from backend.crawler.scheduler import _links_from
from backend.crawler.service import CrawlManager, CrawlStore
from backend.crawler.url import (
    UNWANTED_EXTENSIONS,
    canonicalize_url,
    domain_matches,
    has_embedded_credentials,
    has_unwanted_extension,
    hostname_of,
    is_crawlable_url,
    is_dangerous_url,
    is_http_url,
    is_private_host,
    normalize_url,
    resolve_url,
    scope_hosts,
)
from backend.db.models import Document
from backend.db.repository import DocumentRepository, make_document_repository
from backend.db.repository_factory import (
    _attempt_repository,
    create_best_effort_repository,
    create_document_repository_factory,
    create_initialised_document_repository,
)
from backend.pipeline import (
    PipelineReport,
    build_pipeline,
    persist_corpus,
    run_pipeline,
)
from backend.processing import loader as loader_module
from backend.processing.loader import (
    SKIP_FILENAMES,
    DocumentSource,
    load_corpus,
)
from backend.processing.models import ProcessedDocument
from backend.processing.snippets import build_snippet, make_snippet
from backend.processing.tokenizer import (
    STOPWORDS,
    TOKEN_RE,
    count_tokens,
    iter_tokens,
    normalize,
    snippet_tokens,
    tokenize,
)
from backend.search.bm25 import Bm25, Bm25Index
from backend.search.engine import SearchEngine
from backend.search.hybrid import (
    InvalidHybridWeightsError,
    _sort_key_doc_id,
    highlight_matched_terms,
    merge_and_rerank_hybrid,
    min_max_normalize,
    validate_and_normalize_weights,
)
from backend.search.index_store import (
    ARTIFACT_FILE,
    INDEX_FORMAT_VERSION,
    METADATA_FILE,
    IndexMetadata,
    compute_document_signature,
    load_index,
    is_index_present,
    max_document_id,
    read_metadata,
    remove_index,
    save_index,
)
from backend.search.models import SearchResult
from backend.search.query import (
    MAX_QUERY_TOKENS,
    QueryProcessor,
    WeightedQueryToken,
    token_stream,
)

from conftest import FakeRepository, make_document

# --------------------------------------------------------------------------- #
# 1. tokenizer / normaliser - degenerate inputs
# --------------------------------------------------------------------------- #


class TestTokenizerEdges:
    def test_token_regex_only_matches_word_runs(self):
        assert TOKEN_RE.findall("a_b c-d e.f") == ["a", "b", "c", "d", "e", "f"]

    def test_normalize_folds_accents_and_case(self):
        assert normalize("CAFÉ Crème") == "cafe creme"
        assert normalize("") == ""

    def test_tokenize_on_empty_and_punctuation_only(self):
        assert tokenize("") == []
        assert tokenize("   ") == []
        assert tokenize("!!! ??? ...") == []

    def test_tokenize_keeps_technical_vocabulary(self):
        """Corpus jargon must never be stop-worded - BM25 depends on it."""
        tokens = tokenize("Docker and python are the runtime")
        for term in ("docker", "python", "runtime"):
            assert term in tokens
        assert "and" not in tokens and "the" not in tokens

    def test_stopword_set_is_explicit_and_stable(self):
        assert "the" in STOPWORDS and "docker" not in STOPWORDS
        assert isinstance(STOPWORDS, frozenset)

    def test_keep_stopwords_returns_the_full_vocabulary(self):
        assert tokenize("the cat and the hat", keep_stopwords=True).count("the") == 2

    def test_iter_tokens_is_lazy_and_matches_tokenize(self):
        it = iter_tokens("the lazy brown fox")
        assert next(it) == "lazy"
        assert list(it) == ["brown", "fox"]

    def test_count_tokens_matches_tokenize_length(self):
        text = "The quick brown fox jumps over the lazy dog"
        assert count_tokens(text) == len(tokenize(text))
        assert count_tokens(text, keep_stopwords=True) == len(
            tokenize(text, keep_stopwords=True)
        )
        assert count_tokens("") == 0

    def test_query_token_budget_constant_is_positive(self):
        assert MAX_QUERY_TOKENS > 0

    @pytest.mark.parametrize("words,expected", [(0, 0), (3, 3), (5, 5), (999, 9)])
    def test_snippet_tokens_window_bounds(self, words, expected):
        text = "one two three four five six seven eight nine"
        assert len(list(snippet_tokens(text, words=words))) == expected

    def test_snippet_tokens_negative_window_is_empty(self):
        assert list(snippet_tokens("alpha beta gamma", words=-5)) == []

    def test_snippet_tokens_keeps_stopwords_so_snippets_read_naturally(self):
        text = "Use the container to run the image"
        window = list(snippet_tokens(text, words=6))
        assert "the" in window

    def test_snippet_tokens_default_window_is_bounded(self):
        text = " ".join(f"w{i}" for i in range(200))
        assert len(list(snippet_tokens(text))) == 26

    def test_snippet_tokens_is_lazy(self):
        stream = snippet_tokens("alpha beta gamma delta", words=2)
        assert next(iter(stream)) == "alpha"


# --------------------------------------------------------------------------- #
# 2. snippets
# --------------------------------------------------------------------------- #


class TestSnippetEdges:
    def test_empty_content_degenerates_to_empty_string(self):
        assert make_snippet("", ["python"]) == ""
        assert make_snippet("", []) == ""

    def test_no_query_tokens_falls_back_to_the_leading_window(self):
        snippet = make_snippet("alpha beta gamma delta", [])
        assert snippet.startswith("alpha beta")
        assert len(snippet.split()) <= 26

    def test_first_matching_line_wins(self):
        content = "intro line about nothing\n\ndocker compose runs the stack\n\ntail"
        snippet = make_snippet(content, ["docker"])
        assert "docker" in snippet
        assert "intro" not in snippet

    def test_no_matching_token_falls_back_to_the_leading_window(self):
        content = "alpha beta\ngamma delta"
        snippet = make_snippet(content, ["kubernetes"])
        assert snippet == "alpha beta gamma delta"

    def test_words_window_is_respected(self):
        # ``words`` is a radius: the window is centred on the match and holds at
        # most ``2 * (words // 2) + 1`` tokens.
        content = " ".join(f"tok{i}" for i in range(80))
        window = make_snippet(content, ["tok40"], words=10).split()
        assert len(window) <= 11
        assert window[5] == "tok40", "the match should sit in the middle"
        assert window[:2] == ["tok35", "tok36"]

    def test_stopword_free_matching_depends_on_keep_stopwords(self):
        # Two paragraphs: only the second contains the stop-word query token.
        # With stopwords stripped no paragraph matches, so the leading window of
        # the *first* paragraph wins; with them kept the matching paragraph wins.
        content = "alpha beta gamma\nthe model and the data"
        assert make_snippet(content, ["the"], keep_stopwords=False) == (
            "alpha beta gamma the model and the data"
        )
        assert make_snippet(content, ["the"], keep_stopwords=True).startswith(
            "the model and the data"
        )

    def test_building_a_snippet_is_deterministic(self):
        content = "docker compose is a tool for defining containers"
        first = make_snippet(content, ["docker", "container"])
        for _ in range(5):
            assert make_snippet(content, ["docker", "container"]) == first

    def test_build_snippet_is_the_documented_alias(self):
        assert build_snippet is make_snippet


# --------------------------------------------------------------------------- #
# 3. corpus loader
# --------------------------------------------------------------------------- #


def _write(root, name: str, text: str):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class TestCorpusLoaderEdges:
    def test_missing_directory_loads_nothing(self, tmp_path):
        assert load_corpus(tmp_path / "does-not-exist") == []

    def test_empty_directory_loads_nothing(self, tmp_path):
        assert load_corpus(tmp_path) == []

    def test_front_matter_title_wins_over_filename(self, tmp_path):
        _write(tmp_path, "alpha.md", "---\ntitle: Real Title\n---\n\nbody text here")
        docs = load_corpus(tmp_path)
        assert [d.title for d in docs] == ["Real Title"]
        assert [d.document_id for d in docs] == ["alpha"]

    def test_quoted_front_matter_title_is_unquoted(self, tmp_path):
        _write(tmp_path, "beta.md", "---\ntitle: 'Quoted Title'\n---\n\nbody text")
        assert load_corpus(tmp_path)[0].title == "Quoted Title"

    def test_filename_is_the_title_fallback(self, tmp_path):
        _write(tmp_path, "my_long_name.md", "some body text without front matter")
        doc = load_corpus(tmp_path)[0]
        assert doc.title == "My Long Name"
        assert doc.document_id == "my_long_name"

    def test_front_matter_is_stripped_from_the_indexed_content(self, tmp_path):
        _write(tmp_path, "gamma.md", "---\ntitle: T\n---\nsecret front matter\nbody")
        doc = load_corpus(tmp_path)[0]
        assert "title: T" not in doc.content
        assert "body" in doc.content

    def test_unterminated_front_matter_is_kept_as_content(self, tmp_path):
        _write(tmp_path, "delta.md", "---\ntitle: T\nno closing fence")
        docs = load_corpus(tmp_path)
        assert len(docs) == 1
        assert "title" in docs[0].content

    def test_index_like_filenames_are_skipped(self, tmp_path):
        for skipped in sorted(SKIP_FILENAMES):
            _write(tmp_path, skipped, "navigation chrome that must not be indexed")
        _write(tmp_path, "real.md", "actual corpus content")
        docs = load_corpus(tmp_path)
        assert [d.document_id for d in docs] == ["real"]

    def test_files_without_content_are_skipped(self, tmp_path):
        _write(tmp_path, "empty.md", "")
        _write(tmp_path, "front_matter_only.md", "---\ntitle: T\n---\n")
        _write(tmp_path, "whitespace.md", "   \n\n  ")
        assert load_corpus(tmp_path) == []

    def test_stopword_only_files_are_skipped(self, tmp_path):
        _write(tmp_path, "stop.md", "the a an and or but")
        assert load_corpus(tmp_path) == []

    def test_duplicate_content_is_collapsed_by_default(self, tmp_path):
        _write(tmp_path, "a.md", "identical body content for both files")
        _write(tmp_path, "b.md", "identical body content for both files")
        assert len(load_corpus(tmp_path)) == 1

    def test_dedupe_can_be_disabled(self, tmp_path):
        _write(tmp_path, "a.md", "identical body content for both files")
        _write(tmp_path, "b.md", "identical body content for both files")
        assert len(load_corpus(tmp_path, dedupe=False)) == 2

    def test_loading_is_deterministic_and_recursive(self, tmp_path):
        _write(tmp_path, "zeta.md", "last document alphabetically")
        _write(tmp_path, "nested/alpha.md", "first document alphabetically")
        _write(tmp_path, "alpha.md", "top level alpha")
        docs = load_corpus(tmp_path)
        assert [d.document_id for d in docs] == sorted(
            d.document_id for d in docs
        )
        assert {d.document_id for d in docs} == {"alpha", "zeta"}
        # Byte-for-byte reproducible across runs.
        again = load_corpus(tmp_path)
        assert [d.content_hash for d in docs] == [d.content_hash for d in again]

    def test_source_is_the_absolute_resolved_path(self, tmp_path):
        _write(tmp_path, "a.md", "body")
        assert Path(load_corpus(tmp_path)[0].source).is_absolute()

    def test_document_source_records_the_first_heading(self, tmp_path):
        path = _write(tmp_path, "a.md", "# Heading One\n\nbody")
        source = loader_module._read_meta(path)
        assert isinstance(source, DocumentSource)
        assert source.raw_heading == "Heading One"

    def test_content_hash_is_sha256_of_normalised_content(self, tmp_path):
        import hashlib

        _write(tmp_path, "a.md", "Café body")
        doc = load_corpus(tmp_path)[0]
        expected = hashlib.sha256(normalize(doc.content).encode("utf-8")).hexdigest()
        assert doc.content_hash == expected

    def test_tokens_are_stopword_stripped(self, tmp_path):
        _write(tmp_path, "a.md", "the docker container runs")
        doc = load_corpus(tmp_path)[0]
        assert "the" not in doc.tokens
        assert "docker" in doc.tokens


# --------------------------------------------------------------------------- #
# 4. pipeline orchestration
# --------------------------------------------------------------------------- #


class TestPipelineEdges:
    def test_extra_documents_are_filtered_before_indexing(self, monkeypatch):
        monkeypatch.setattr("backend.pipeline.load_corpus", lambda: [])
        good = make_document("good-1", "Good", "indexable body text")
        empty_content = ProcessedDocument(
            document_id="empty-content", title="E", content="", source="", tokens=("x",)
        )
        empty_tokens = ProcessedDocument(
            document_id="empty-tokens", title="E", content="body", source="", tokens=()
        )
        engine = build_pipeline(extra=[good, empty_content, empty_tokens, None])
        assert engine.document_count == 1
        assert engine.get_document("good-1") is not None

    def test_build_pipeline_without_extra_indexes_only_the_corpus(self, monkeypatch):
        monkeypatch.setattr("backend.pipeline.load_corpus", lambda: [])
        assert build_pipeline().document_count == 0

    def test_run_pipeline_reports_counts(self, monkeypatch, sample_documents):
        monkeypatch.setattr("backend.pipeline.load_corpus", lambda: list(sample_documents))
        monkeypatch.setattr("backend.pipeline._persist_best_effort", lambda docs: 0)
        report = run_pipeline()
        assert isinstance(report, PipelineReport)
        assert report.documents_loaded == len(sample_documents)
        assert report.indexed == len(sample_documents)
        assert report.persisted == 0
        assert "indexed 4 documents in-memory" == report.message

    def test_run_pipeline_mentions_persisted_rows(self, monkeypatch, sample_documents):
        monkeypatch.setattr("backend.pipeline.load_corpus", lambda: list(sample_documents))
        monkeypatch.setattr("backend.pipeline._persist_best_effort", lambda docs: 2)
        assert "(+2 persisted)" in run_pipeline().message

    def test_pipeline_report_is_frozen(self):
        report = PipelineReport()
        with pytest.raises(Exception):
            report.documents_loaded = 5  # type: ignore[misc]

    def test_persist_corpus_with_a_degraded_repository_is_a_no_op(
        self, monkeypatch, degraded_repository
    ):
        monkeypatch.setattr("backend.pipeline.load_corpus", lambda: [])
        assert persist_corpus(degraded_repository) == 0

    def test_persist_corpus_never_raises_when_the_factory_explodes(self, monkeypatch):
        def _boom(*_args, **_kwargs):
            raise RuntimeError("no database here")

        monkeypatch.setattr(
            "backend.pipeline.create_initialised_document_repository", _boom
        )
        assert persist_corpus() == 0

    def test_persist_corpus_returns_zero_when_the_factory_is_degraded(self, monkeypatch):
        monkeypatch.setattr(
            "backend.pipeline.create_initialised_document_repository",
            lambda *_a, **_k: make_document_repository(None),
        )
        assert persist_corpus() == 0

    def test_persist_corpus_inserts_new_rows_only(
        self, monkeypatch, sample_documents, fake_repository
    ):
        monkeypatch.setattr("backend.pipeline.load_corpus", lambda: list(sample_documents))
        first = persist_corpus(fake_repository)
        assert first == len(sample_documents)
        # Second call: every content hash is already known.
        assert persist_corpus(fake_repository) == 0

    def test_persist_corpus_swallows_repository_errors(self, monkeypatch, sample_documents):
        class _Exploding(FakeRepository):
            def upsert_many(self, documents):  # type: ignore[override]
                raise RuntimeError("connection reset")

        monkeypatch.setattr("backend.pipeline.load_corpus", lambda: list(sample_documents))
        assert persist_corpus(_Exploding()) == 0

    def test_private_best_effort_helper_returns_zero_when_degraded(self, monkeypatch):
        from backend.pipeline import _persist_best_effort

        monkeypatch.setattr(
            "backend.pipeline.create_initialised_document_repository",
            lambda *_a, **_k: make_document_repository(None),
        )
        assert _persist_best_effort([]) == 0

    def test_private_best_effort_helper_swallows_factory_errors(self, monkeypatch):
        from backend.pipeline import _persist_best_effort

        def _boom(*_a, **_k):
            raise OSError("dns failure")

        monkeypatch.setattr(
            "backend.pipeline.create_initialised_document_repository", _boom
        )
        assert _persist_best_effort([]) == 0

    def test_private_best_effort_helper_counts_inserted_rows(
        self, monkeypatch, sample_documents
    ):
        from backend.pipeline import _persist_best_effort

        repo = FakeRepository()
        monkeypatch.setattr(
            "backend.pipeline.create_initialised_document_repository",
            lambda *_a, **_k: repo,
        )
        assert _persist_best_effort(list(sample_documents)) == len(sample_documents)


# --------------------------------------------------------------------------- #
# 5. query processing
# --------------------------------------------------------------------------- #


class TestQueryProcessing:
    def test_normalize_query_trims_and_folds(self):
        assert QueryProcessor.normalize_query("  Docker  ") == "docker"

    def test_process_weights_repeats(self):
        weights = {t.token: t.weight for t in QueryProcessor().process("python python python docker")}
        assert weights["python"] == 3.0
        assert weights["docker"] == 1.0

    def test_process_preserves_first_seen_order(self):
        tokens = [t.token for t in QueryProcessor().process("zeta alpha zeta")]
        assert tokens == ["zeta", "alpha"]

    def test_process_of_empty_queries(self):
        processor = QueryProcessor()
        assert processor.process("") == []
        assert processor.process("   ") == []
        assert processor.process("***") == []

    def test_process_drops_punctuation_but_keeps_technical_tokens(self):
        tokens = [t.token for t in QueryProcessor().process("c++ & docker-compose")]
        assert "docker" in tokens
        assert "c" in tokens

    def test_weighted_query_token_coerces_weight_to_float(self):
        assert WeightedQueryToken("x", 2).weight == 2.0
        assert "WeightedQueryToken" in repr(WeightedQueryToken("x"))

    def test_query_and_corpus_share_the_token_space(self):
        """Typo/case/spacing differences must still reach the same tokens."""
        assert tokenize("Docker  Compose") == tokenize("docker compose")
        assert list(token_stream("  Docker  Compose  ")) == tokenize(
            "Docker Compose", keep_stopwords=True
        )

    def test_token_stream_of_empty_query(self):
        assert tuple(token_stream("")) == ()


# --------------------------------------------------------------------------- #
# 6. BM25 index
# --------------------------------------------------------------------------- #


class TestBm25IndexEdges:
    # NOTE: ``Bm25Index.score`` is documented to return a ``list[float]`` aligned
    # to ``self.documents`` - the token-less documents are skipped by the BM25
    # corpus but still occupy their slot (score 0.0).

    def test_empty_corpus_never_scores(self):
        index = Bm25Index([])
        assert index.document_count == 0
        assert index.vocabulary_size == 0
        assert index.score(["python"]) == []
        assert index.stats["average_document_length"] == 0.0
        assert index.stats["documents"] == 0

    def test_unknown_terms_score_zero_everywhere(self, sample_documents):
        index = Bm25Index(sample_documents)
        assert index.score(["kubernetes"]) == [0.0] * len(sample_documents)

    def test_empty_query_token_lists_score_zero(self, sample_documents):
        index = Bm25Index(sample_documents)
        assert set(index.score([])) == {0.0}
        assert set(index.score(["", None])) == {0.0}

    def test_scores_stay_aligned_when_a_document_has_no_tokens(self, sample_documents):
        # A token-less document must neither shift the following scores nor
        # shorten the result: every caller's score[i] belongs to documents[i].
        empty = ProcessedDocument(
            document_id="empty", title="Empty", content="", source="", tokens=()
        )
        index = Bm25Index([*sample_documents, empty])
        scores = index.score(["python"])
        assert len(scores) == len(sample_documents) + 1
        assert scores[-1] == 0.0
        assert scores[0] > 0.0, "the first document still owns the Python score"
        assert scores[: len(sample_documents)] == Bm25Index(
            sample_documents
        ).score(["python"])

    def test_documents_without_tokens_are_still_addressable(self, sample_documents):
        empty = ProcessedDocument(
            document_id="empty", title="Empty", content="", source="", tokens=()
        )
        index = Bm25Index([*sample_documents, empty])
        assert index.document(4).document_id == "empty"
        assert index.document(999) is None

    def test_document_lookup_boundaries(self, sample_documents):
        index = Bm25Index(sample_documents)
        assert index.document(0) is sample_documents[0]
        assert index.document(-1) is sample_documents[-1]
        assert index.document(10_000) is None

    def test_vocabulary_counts_distinct_terms(self, doc):
        # ``make_document`` lower-cases whitespace tokens, so "docker" twice is
        # one distinct vocabulary term and "container" the second.
        index = Bm25Index([doc("a", "A", "docker docker container")])
        assert index.vocabulary_size == 2

    def test_term_frequency_profile_is_a_flat_counter(self, doc):
        index = Bm25Index(
            [doc("a", "A", "docker docker container"), doc("b", "B", "docker")]
        )
        profile = index.term_frequency_profile()
        assert profile == {"docker": 3, "container": 1}
        assert all(isinstance(v, int) for v in profile.values())

    def test_stats_reports_the_bm25_parameters(self, sample_documents):
        stats = Bm25Index(sample_documents, k1=1.2, b=0.6).stats
        assert stats["k1"] == 1.2
        assert stats["b"] == 0.6
        assert stats["documents"] == len(sample_documents)
        assert stats["corpus_tokens"] > 0
        assert stats["vocabulary"] > 0

    def test_bm25_alias_is_the_same_class(self):
        assert Bm25 is Bm25Index

    def test_ranking_puts_the_matching_document_first(self, sample_documents):
        index = Bm25Index(sample_documents)
        scores = index.score(["docker"])
        assert scores.index(max(scores)) == 1  # dk-1


# --------------------------------------------------------------------------- #
# 7. search engine
# --------------------------------------------------------------------------- #


class TestSearchEngineEdges:
    def test_limit_is_clamped_into_range(self, sample_documents):
        engine = SearchEngine(sample_documents)
        assert engine.search("docker", limit=0).limit == 1
        assert engine.search("docker", limit=-5).limit == 1
        assert engine.search("docker", limit=10_000).limit == 50

    def test_explicit_max_limit_wins(self, sample_documents):
        engine = SearchEngine(sample_documents)
        assert engine.search("docker", limit=10, max_limit=3).limit == 3
        assert len(engine.search("docker", limit=10, max_limit=3).hits) == 3

    def test_default_and_max_limit_are_hardened_at_construction(self):
        engine = SearchEngine([], default_limit=0, max_limit=-1)
        assert engine.search("python").limit == 1

    def test_empty_and_whitespace_queries_return_no_hits(self, sample_documents):
        engine = SearchEngine(sample_documents)
        for query in ("", "   ", "\n\t", "!!!"):
            response = engine.search(query)
            assert response.hits == ()
            assert response.total == 0
            assert response.message == "ok"

    def test_unmatched_query_still_pads_with_zero_scores(self, sample_documents):
        """BM25 returns the whole index; filtering zero hits is a mode concern."""
        response = SearchEngine(sample_documents).search("kubernetes")
        assert response.total == len(sample_documents)
        assert all(hit.score == 0.0 for hit in response.hits)

    def test_query_is_folded_in_the_response(self, sample_documents):
        assert SearchEngine(sample_documents).search("  Docker  ").query == "docker"

    def test_ranks_are_dense_and_ordered_by_score(self, sample_documents):
        response = SearchEngine(sample_documents).search("python docker machine")
        assert [hit.rank for hit in response.hits] == list(
            range(1, len(response.hits) + 1)
        )
        scores = [hit.score for hit in response.hits]
        assert scores == sorted(scores, reverse=True)

    def test_matched_terms_are_capped_at_eight(self, sample_documents):
        query = " ".join(f"t{i}" for i in range(12))
        response = SearchEngine(sample_documents).search(query)
        assert response.hits
        assert all(len(hit.matched_terms) <= 8 for hit in response.hits)

    def test_snippet_is_keyword_aware(self, sample_documents):
        response = SearchEngine(sample_documents).search("docker")
        assert "docker" in response.hits[0].snippet

    def test_get_document_finds_known_ids_and_returns_none_otherwise(
        self, sample_documents
    ):
        engine = SearchEngine(sample_documents)
        assert engine.get_document("py-1").title == "Python Guide"
        assert engine.get_document(1) is None
        assert engine.get_document("nope") is None
        assert engine.get_document("") is None

    def test_index_documents_rebuilds_and_reports_the_count(self, sample_documents):
        engine = SearchEngine()
        assert engine.document_count == 0
        assert engine.index_documents(sample_documents) == 4
        assert engine.document_count == 4
        assert engine.index_documents(sample_documents[:1]) == 1
        assert engine.document_count == 1

    def test_reindexing_keeps_the_configured_bm25_parameters(self, sample_documents):
        engine = SearchEngine(sample_documents, k1=1.1, b=0.9)
        engine.index_documents(sample_documents)
        assert engine.corpus_stats()["k1"] == 1.1
        assert engine.corpus_stats()["b"] == 0.9

    def test_corpus_stats_is_the_bm25_stats_mapping(self, sample_documents):
        assert SearchEngine(sample_documents).corpus_stats()["documents"] == 4

    def test_response_carries_a_timing_field(self, sample_documents):
        response = SearchEngine(sample_documents).search("docker")
        assert response.took_ms >= 0.0


# --------------------------------------------------------------------------- #
# 8. hybrid ranking
# --------------------------------------------------------------------------- #


class TestScoreNormalisation:
    def test_empty_input(self):
        assert min_max_normalize([]) == []

    def test_single_positive_value_maps_to_one(self):
        assert min_max_normalize([3.5]) == [1.0]

    def test_single_zero_value_maps_to_zero(self):
        assert min_max_normalize([0.0]) == [0.0]

    def test_all_equal_positive_values(self):
        assert min_max_normalize([2.0, 2.0, 2.0]) == [1.0, 1.0, 1.0]

    def test_all_equal_non_positive_values(self):
        assert min_max_normalize([-2.0, -2.0]) == [0.0, 0.0]

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_values_are_sanitised(self, bad):
        out = min_max_normalize([bad, 1.0])
        assert len(out) == 2
        assert all(math.isfinite(v) for v in out)

    def test_min_maps_to_zero_and_max_to_one(self):
        out = min_max_normalize([0.0, 5.0, 10.0])
        assert out[0] == 0.0
        assert out[-1] == 1.0

    def test_output_is_always_within_unit_range(self):
        out = min_max_normalize([-10.0, 0.0, 4.0, 40.0])
        assert all(0.0 <= v <= 1.0 for v in out)

    def test_relative_order_is_preserved(self):
        out = min_max_normalize([1.0, 3.0, 2.0])
        assert out[0] < out[2] < out[1]


class TestWeightValidation:
    def test_explicit_weights_are_normalised_to_sum_one(self):
        weights = validate_and_normalize_weights(3.0, 1.0)
        assert weights.bm25 == pytest.approx(0.75)
        assert weights.semantic == pytest.approx(0.25)

    def test_defaults_come_from_settings(self):
        weights = validate_and_normalize_weights()
        assert weights.bm25 == pytest.approx(
            settings.HYBRID_BM25_WEIGHT
            / (settings.HYBRID_BM25_WEIGHT + settings.HYBRID_SEMANTIC_WEIGHT)
        )

    def test_only_one_weight_supplied_is_completed_from_settings(self):
        weights = validate_and_normalize_weights(1.0, None)
        assert weights.bm25 + weights.semantic == pytest.approx(1.0)

    @pytest.mark.parametrize(
        "bm25,semantic", [(-0.1, 0.5), (0.5, -0.1), (-1.0, -1.0)]
    )
    def test_negative_weights_are_rejected(self, bm25, semantic):
        with pytest.raises(InvalidHybridWeightsError):
            validate_and_normalize_weights(bm25, semantic)

    def test_both_zero_is_rejected(self):
        with pytest.raises(InvalidHybridWeightsError):
            validate_and_normalize_weights(0.0, 0.0)

    def test_zero_and_positive_is_allowed(self):
        weights = validate_and_normalize_weights(0.0, 1.0)
        assert weights.bm25 == 0.0 and weights.semantic == 1.0


class TestHighlighting:
    def test_empty_text_yields_empty_output(self):
        assert highlight_matched_terms("", ["docker"]) == ""

    def test_no_terms_escapes_the_whole_text(self):
        assert highlight_matched_terms("a & b", []) == "a &amp; b"

    def test_blank_terms_are_ignored(self):
        assert highlight_matched_terms("plain", ["", "   "]) == "plain"

    def test_matched_terms_are_wrapped(self):
        out = highlight_matched_terms("Docker runs", ["docker"])
        assert out == "<mark>Docker</mark> runs"

    def test_html_in_the_source_is_escaped_even_when_marked(self):
        out = highlight_matched_terms("<b>docker</b> & more", ["docker"])
        assert "<b>" not in out
        assert "&lt;b&gt;" in out
        assert "&amp;" in out

    def test_longer_terms_win_over_shorter_substrings(self):
        out = highlight_matched_terms("container", ["container", "cont"])
        assert out == "<mark>container</mark>"

    def test_regex_metacharacters_in_terms_are_escaped(self):
        out = highlight_matched_terms("c++ rules", ["c++"])
        assert out == "<mark>c++</mark> rules"
        assert "c++" in out

    def test_highlighting_is_deterministic(self):
        text, terms = "docker docker container", ["docker", "container"]
        first = highlight_matched_terms(text, terms)
        assert all(highlight_matched_terms(text, terms) == first for _ in range(5))


def _hit(document_id, score, *, title="", source="", snippet="", matched=()):
    return SearchResult(
        rank=0,
        document_id=document_id,
        title=title or f"Doc {document_id}",
        source=source or f"https://example.org/{document_id}",
        snippet=snippet or f"snippet for {document_id}",
        score=score,
        matched_terms=tuple(matched),
    )


class TestHybridMerge:
    def test_no_candidates_returns_an_empty_ranking(self):
        hits, weights = merge_and_rerank_hybrid([], [], "python", 5)
        assert hits == []
        assert set(weights) == {"bm25", "semantic"}

    def test_documents_from_both_lists_are_deduplicated(self):
        hits, _ = merge_and_rerank_hybrid(
            [_hit("a", 2.0), _hit("b", 1.0)],
            [_hit("b", 3.0), _hit("c", 1.5)],
            "python",
            10,
        )
        assert sorted(h.document_id for h in hits) == ["a", "b", "c"]

    def test_ranks_are_assigned_after_sorting(self):
        hits, _ = merge_and_rerank_hybrid(
            [_hit("a", 0.1), _hit("b", 5.0), _hit("c", 1.0)], [], "python", 10
        )
        assert [h.rank for h in hits] == [1, 2, 3]
        assert hits[0].document_id == "b"

    def test_limit_truncates_the_ranking(self):
        hits, _ = merge_and_rerank_hybrid(
            [_hit("a", 1.0), _hit("b", 2.0), _hit("c", 3.0)], [], "python", 2
        )
        assert len(hits) == 2

    def test_semantic_only_candidates_are_kept(self):
        hits, _ = merge_and_rerank_hybrid([], [_hit("s1", 0.9)], "python", 5)
        assert [h.document_id for h in hits] == ["s1"]

    def test_weights_shift_the_ranking(self):
        bm25 = [_hit("a", 10.0), _hit("b", 0.1)]
        semantic = [_hit("b", 10.0), _hit("a", 0.1)]
        bm25_first, _ = merge_and_rerank_hybrid(
            bm25, semantic, "python", 5, bm25_weight=1.0, semantic_weight=0.0
        )
        semantic_first, _ = merge_and_rerank_hybrid(
            bm25, semantic, "python", 5, bm25_weight=0.0, semantic_weight=1.0
        )
        assert bm25_first[0].document_id == "a"
        assert semantic_first[0].document_id == "b"

    def test_ties_break_deterministically(self):
        first, _ = merge_and_rerank_hybrid(
            [_hit("a", 1.0), _hit("b", 1.0), _hit("c", 1.0)], [], "python", 5
        )
        second, _ = merge_and_rerank_hybrid(
            [_hit("c", 1.0), _hit("a", 1.0), _hit("b", 1.0)], [], "python", 5
        )
        assert [h.document_id for h in first] == [h.document_id for h in second]

    def test_invalid_weights_are_rejected(self):
        with pytest.raises(InvalidHybridWeightsError):
            merge_and_rerank_hybrid(
                [_hit("a", 1.0)], [], "python", 5, bm25_weight=-1.0
            )

    def test_matched_terms_are_merged_sorted_and_capped(self):
        hits, _ = merge_and_rerank_hybrid(
            [_hit("a", 1.0, matched=["zeta", "alpha"])],
            [_hit("a", 1.0, matched=["mu", "alpha"])],
            "python",
            5,
        )
        assert hits[0].matched_terms == ("alpha", "mu", "zeta")
        long_terms = tuple(f"t{i}" for i in range(20))
        capped, _ = merge_and_rerank_hybrid(
            [_hit("a", 1.0, matched=long_terms)], [], "python", 5
        )
        assert len(capped[0].matched_terms) == 8

    def test_snippets_are_highlighted_against_the_query(self):
        hits, _ = merge_and_rerank_hybrid(
            [_hit("a", 1.0, snippet="docker is great")], [], "docker", 5
        )
        assert "<mark>docker</mark>" in hits[0].snippet

    def test_empty_snippets_fall_back_to_a_non_empty_one(self):
        # Same document seen twice: the BM25 hit has no snippet, the semantic
        # one does. The merged candidate must adopt the non-empty snippet.
        hits, _ = merge_and_rerank_hybrid(
            [_hit("a", 1.0, snippet="real text")],
            [_hit("a", 1.0, snippet="")],
            "python",
            5,
        )
        assert hits[0].snippet == "real text"

    def test_scores_are_rounded_for_the_wire(self):
        hits, _ = merge_and_rerank_hybrid([_hit("a", 1 / 3)], [], "python", 5)
        assert hits[0].score == round(hits[0].score, 4)

    def test_doc_id_tie_breaker_helper(self):
        assert _sort_key_doc_id("7") == -7
        assert _sort_key_doc_id("alpha") == "alpha"
        assert _sort_key_doc_id("") == ""


# --------------------------------------------------------------------------- #
# 9. RAG: models, passage selection, prompt, providers, orchestrator
# --------------------------------------------------------------------------- #


class TestAnswerModels:
    @pytest.mark.parametrize("query", ["", "x" * 501])
    def test_query_length_is_bounded(self, query):
        with pytest.raises(Exception):
            AnswerRequest(query=query)

    @pytest.mark.parametrize("limit", [0, 21])
    def test_limit_bounds(self, limit):
        with pytest.raises(Exception):
            AnswerRequest(query="ok", limit=limit)

    @pytest.mark.parametrize("temperature", [-0.1, 2.1])
    def test_temperature_bounds(self, temperature):
        with pytest.raises(Exception):
            AnswerRequest(query="ok", temperature=temperature)

    def test_defaults(self):
        request = AnswerRequest(query="ok")
        assert request.mode == "hybrid"
        assert request.limit == 5
        assert request.temperature is None

    def test_mode_is_a_closed_enum(self):
        with pytest.raises(Exception):
            AnswerRequest(query="ok", mode="telepathy")

    def test_response_status_is_a_closed_enum(self):
        with pytest.raises(Exception):
            AnswerResponse(
                query="q",
                answer="a",
                status="weird",
                retrieval=RetrievalMetadata(mode="lexical"),
                generation=GenerationMetadata(provider="fake", model="m"),
            )

    def test_response_defaults(self):
        response = AnswerResponse(
            query="q",
            answer="a",
            retrieval=RetrievalMetadata(mode="lexical"),
            generation=GenerationMetadata(provider="fake", model="m"),
        )
        assert response.status == "ok"
        assert response.fallback_mode is False
        assert response.sources == [] and response.search_hits == []


class TestPassageSelection:
    def test_dict_hits_are_accepted(self):
        passages, citations = extract_and_select_passages(
            [{"document_id": "1", "title": "T", "source": "s", "snippet": "body", "score": 1.0}]
        )
        assert len(passages) == 1 and len(citations) == 1
        assert passages[0].citation_id == citations[0].citation_id == 1

    def test_object_hits_are_accepted(self):
        passages, citations = extract_and_select_passages([_hit("1", 1.0, snippet="body")])
        assert passages[0].content == "body"
        assert citations[0].score == 1.0

    def test_duplicate_documents_are_dropped(self):
        hits = [
            {"document_id": "1", "snippet": "a", "score": 1.0},
            {"document_id": "1", "snippet": "b", "score": 0.9},
            {"document_id": "2", "snippet": "c", "score": 0.8},
        ]
        passages, _ = extract_and_select_passages(hits)
        assert [p.document_id for p in passages] == ["1", "2"]

    def test_hits_without_a_document_id_are_skipped(self):
        passages, _ = extract_and_select_passages([{"snippet": "orphan", "score": 1.0}])
        assert passages == []

    def test_empty_snippets_are_skipped(self):
        passages, _ = extract_and_select_passages(
            [{"document_id": "1", "snippet": "   ", "score": 1.0}]
        )
        assert passages == []

    def test_max_passages_is_enforced(self):
        hits = [
            {"document_id": str(i), "snippet": f"body {i}", "score": 1.0} for i in range(10)
        ]
        passages, citations = extract_and_select_passages(hits, max_passages=3)
        assert len(passages) == 3
        assert [c.citation_id for c in citations] == [1, 2, 3]

    def test_max_chars_stops_before_exceeding_the_budget(self):
        hits = [
            {"document_id": "1", "snippet": "x" * 100, "score": 1.0},
            {"document_id": "2", "snippet": "y" * 100, "score": 0.9},
            {"document_id": "3", "snippet": "z" * 100, "score": 0.8},
        ]
        passages, _ = extract_and_select_passages(hits, max_chars=150)
        assert len(passages) == 1

    def test_an_oversized_first_passage_is_still_accepted(self):
        passages, _ = extract_and_select_passages(
            [{"document_id": "1", "snippet": "x" * 500, "score": 1.0}], max_chars=10
        )
        assert len(passages) == 1

    def test_highlight_markup_is_stripped(self):
        passages, _ = extract_and_select_passages(
            [{"document_id": "1", "snippet": "a <mark>docker</mark> b", "score": 1.0}]
        )
        assert passages[0].content == "a docker b"

    def test_clean_snippet_helper(self):
        assert _clean_snippet_text("  <mark>x</mark>  ") == "x"
        assert _clean_snippet_text("") == ""

    def test_no_hits_yields_no_passages(self):
        assert extract_and_select_passages([]) == ([], [])


class TestGroundedPrompt:
    def test_prompt_states_the_grounding_rules(self):
        system, _ = construct_grounded_prompt("q", [])
        assert "STRICT RULES" in system
        assert "ONLY" in system
        assert "[1]" in system

    def test_user_prompt_contains_every_passage_and_the_question(self):
        passages = [
            ContextPassage(citation_id=1, document_id="d1", title="T1", content="C1"),
            ContextPassage(citation_id=2, document_id="d2", title="T2", content="C2"),
        ]
        _, user = construct_grounded_prompt("what is docker?", passages)
        assert "SOURCE [1]" in user and "SOURCE [2]" in user
        assert "C1" in user and "C2" in user
        assert "what is docker?" in user
        assert user.rstrip().endswith("ANSWER:")

    def test_prompt_is_deterministic(self):
        passages = [ContextPassage(citation_id=1, document_id="d", title="t", content="c")]
        first = construct_grounded_prompt("q", passages)
        assert construct_grounded_prompt("q", passages) == first

    def test_empty_context_still_builds_a_prompt(self):
        _, user = construct_grounded_prompt("q", [])
        assert "SOURCES:" in user


def _citation(cid: int, doc_id: str = "") -> SourceCitation:
    return SourceCitation(
        citation_id=cid,
        document_id=doc_id or f"d{cid}",
        title=f"T{cid}",
        source="s",
        rank=cid,
        score=1.0,
    )


class TestCitationFiltering:
    def test_no_citation_tags_returns_the_top_citation(self):
        out = _filter_valid_citations("no tags here", [_citation(1), _citation(2)])
        assert [c.citation_id for c in out] == [1]

    def test_no_citations_at_all(self):
        assert _filter_valid_citations("nothing", []) == []

    def test_only_the_cited_sources_are_returned(self):
        out = _filter_valid_citations("answer [2] and [3]", [_citation(i) for i in (1, 2, 3)])
        assert [c.citation_id for c in out] == [2, 3]

    def test_out_of_range_citations_fall_back_to_the_top_source(self):
        out = _filter_valid_citations("answer [99]", [_citation(1), _citation(2)])
        assert [c.citation_id for c in out] == [1]

    def test_duplicate_and_malformed_tags(self):
        out = _filter_valid_citations("a [1] b [1] c [x]", [_citation(1), _citation(2)])
        assert [c.citation_id for c in out] == [1]

    def test_preserves_citation_order(self):
        out = _filter_valid_citations("see [3] then [1]", [_citation(i) for i in (1, 2, 3)])
        assert [c.citation_id for c in out] == [1, 3]


class TestFakeProvider:
    def test_provider_identity(self):
        provider = FakeLLMProvider()
        assert provider.name == "fake"
        assert provider.model_name == "seek-fake-v1"

    def test_answer_is_deterministic_and_cited(self):
        provider = FakeLLMProvider()
        prompt = "USER QUESTION:\nwhat is docker?\nANSWER:"
        first = provider.generate(prompt=prompt, system_prompt="s")
        second = provider.generate(prompt=prompt, system_prompt="s")
        assert first.text == second.text
        assert "what is docker?" in first.text
        assert "[1]" in first.text
        assert first.provider == "fake"

    def test_prompt_without_a_question_marker(self):
        result = FakeLLMProvider().generate(prompt="no marker", system_prompt="s")
        assert "your query" in result.text


class TestProviderFactory:
    @pytest.mark.parametrize(
        "name,expected", [("ollama", "ollama"), ("OLLAMA", "ollama"), ("transformers", "transformers")]
    )
    def test_named_providers(self, name, expected):
        assert get_llm_provider(name).name == expected

    def test_unknown_provider_falls_back_to_the_fake_one(self):
        assert get_llm_provider("gpt-9").name == "fake"
        assert get_llm_provider(None).name == settings.RAG_LLM_PROVIDER

    def test_ollama_provider_honours_overrides(self):
        provider = OllamaLLMProvider(host="http://ollama:11434/", model="llama3")
        assert provider.model_name == "llama3"
        assert provider.name == "ollama"


class _StubResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text or json.dumps(self._payload)

    def json(self):
        return self._payload


class _StubClient:
    def __init__(self, response=None, error=None, recorder=None):
        self._response = response
        self._error = error
        self._recorder = recorder if recorder is not None else []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, json=None, **kwargs):
        self._recorder.append((url, json))
        if self._error is not None:
            raise self._error
        return self._response


class TestOllamaProvider:
    def test_successful_generation(self, monkeypatch):
        recorder: list = []
        monkeypatch.setattr(
            ai_providers.httpx,
            "Client",
            lambda *a, **k: _StubClient(
                _StubResponse(200, {"response": "  generated text  "}), recorder=recorder
            ),
        )
        result = OllamaLLMProvider().generate(prompt="p", system_prompt="s", temperature=0.7)
        assert result.text == "generated text"
        assert result.model == settings.RAG_OLLAMA_MODEL
        url, payload = recorder[0]
        assert url.endswith("/api/generate")
        assert payload["options"]["temperature"] == 0.7
        assert payload["stream"] is False
        assert payload["system"] == "s"

    def test_http_error_is_typed(self, monkeypatch):
        monkeypatch.setattr(
            ai_providers.httpx,
            "Client",
            lambda *a, **k: _StubClient(_StubResponse(500, {}, text="boom")),
        )
        with pytest.raises(LLMProviderError, match="HTTP 500"):
            OllamaLLMProvider().generate(prompt="p", system_prompt="s")

    def test_empty_response_is_typed(self, monkeypatch):
        monkeypatch.setattr(
            ai_providers.httpx,
            "Client",
            lambda *a, **k: _StubClient(_StubResponse(200, {"response": "   "})),
        )
        with pytest.raises(LLMProviderError, match="empty response"):
            OllamaLLMProvider().generate(prompt="p", system_prompt="s")

    def test_transport_error_is_wrapped(self, monkeypatch):
        monkeypatch.setattr(
            ai_providers.httpx,
            "Client",
            lambda *a, **k: _StubClient(error=httpx.ConnectError("refused")),
        )
        with pytest.raises(LLMProviderError, match="connection error"):
            OllamaLLMProvider().generate(prompt="p", system_prompt="s")

    def test_default_temperature_comes_from_settings(self, monkeypatch):
        recorder: list = []
        monkeypatch.setattr(
            ai_providers.httpx,
            "Client",
            lambda *a, **k: _StubClient(
                _StubResponse(200, {"response": "x"}), recorder=recorder
            ),
        )
        OllamaLLMProvider().generate(prompt="p", system_prompt="s")
        assert recorder[0][1]["options"]["temperature"] == settings.RAG_TEMPERATURE


class _StubProvider:
    def __init__(self, *, text="Answer grounded in [1].", error=None):
        self._text = text
        self._error = error
        self.calls: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return "stub"

    @property
    def model_name(self) -> str:
        return "stub-v1"

    def generate(self, prompt, system_prompt, temperature=None, timeout=None):
        self.calls.append(
            {"prompt": prompt, "system_prompt": system_prompt, "temperature": temperature}
        )
        if self._error is not None:
            raise self._error
        return ai_providers.LLMResult(
            text=self._text, provider="stub", model="stub-v1", took_ms=1.0
        )


def _payload(*scores: float) -> dict[str, object]:
    return {
        "hits": [
            {
                "rank": index,
                "document_id": f"d{index}",
                "title": f"T{index}",
                "source": f"https://example.org/{index}",
                "snippet": f"body of document {index}",
                "score": score,
            }
            for index, score in enumerate(scores, start=1)
        ]
    }


class TestRagOrchestrator:
    def test_successful_answer_with_citations(self, monkeypatch):
        monkeypatch.setattr("backend.ai.rag.settings.RAG_ENABLED", True)
        provider = _StubProvider()
        response = generate_rag_answer(
            AnswerRequest(query=" docker ", limit=3),
            provider=provider,
            retrieval_payload=_payload(4.0, 3.0),
        )
        assert response.status == "ok"
        assert response.fallback_mode is False
        assert response.answer.startswith("Answer grounded")
        assert response.sources and response.sources[0].citation_id == 1
        assert response.retrieval.passages_used == 2
        assert response.retrieval.mode == "hybrid"
        assert response.generation.provider == "stub"
        assert provider.calls, "the provider must actually be invoked"

    def test_rag_disabled_reports_unavailable(self, monkeypatch):
        monkeypatch.setattr("backend.ai.rag.settings.RAG_ENABLED", False)
        response = generate_rag_answer(
            AnswerRequest(query="docker"),
            provider=_StubProvider(),
            retrieval_payload=_payload(9.0),
        )
        assert response.status == "unavailable"
        assert response.fallback_mode is True
        assert response.sources == []
        assert response.answer == response.message
        assert len(response.search_hits) == 1

    def test_no_hits_falls_back_without_calling_the_provider(self, monkeypatch):
        monkeypatch.setattr("backend.ai.rag.settings.RAG_ENABLED", True)
        provider = _StubProvider()
        response = generate_rag_answer(
            AnswerRequest(query="docker"), provider=provider, retrieval_payload={"hits": []}
        )
        assert response.status == "ok"
        assert response.fallback_mode is True
        assert provider.calls == []
        assert "couldn't find enough relevant information" in response.answer

    def test_non_list_hits_are_treated_as_empty(self, monkeypatch):
        monkeypatch.setattr("backend.ai.rag.settings.RAG_ENABLED", True)
        response = generate_rag_answer(
            AnswerRequest(query="d"),
            provider=_StubProvider(),
            retrieval_payload={"hits": "not-a-list"},
        )
        assert response.fallback_mode is True

    def test_low_top_score_falls_back(self, monkeypatch):
        monkeypatch.setattr("backend.ai.rag.settings.RAG_ENABLED", True)
        provider = _StubProvider()
        response = generate_rag_answer(
            AnswerRequest(query="d"),
            provider=provider,
            retrieval_payload=_payload(settings.RAG_MIN_SCORE_THRESHOLD / 2),
        )
        assert response.fallback_mode is True
        assert provider.calls == []

    def test_provider_error_degrades_and_keeps_the_hits(self, monkeypatch):
        monkeypatch.setattr("backend.ai.rag.settings.RAG_ENABLED", True)
        response = generate_rag_answer(
            AnswerRequest(query="d"),
            provider=_StubProvider(error=LLMProviderError("ollama down")),
            retrieval_payload=_payload(4.0),
        )
        assert response.status == "degraded"
        assert response.fallback_mode is True
        assert "ollama down" in response.answer
        assert len(response.search_hits) == 1

    def test_unexpected_provider_error_degrades(self, monkeypatch):
        monkeypatch.setattr("backend.ai.rag.settings.RAG_ENABLED", True)
        response = generate_rag_answer(
            AnswerRequest(query="d"),
            provider=_StubProvider(error=RuntimeError("kaboom")),
            retrieval_payload=_payload(4.0),
        )
        assert response.status == "degraded"
        assert "kaboom" in response.answer

    def test_hits_without_usable_snippets_fall_back(self, monkeypatch):
        monkeypatch.setattr("backend.ai.rag.settings.RAG_ENABLED", True)
        response = generate_rag_answer(
            AnswerRequest(query="d"),
            provider=_StubProvider(),
            retrieval_payload={"hits": [{"document_id": "1", "score": 9.0}]},
        )
        assert response.fallback_mode is True

    def test_fallback_response_reports_the_configured_model(self, monkeypatch):
        monkeypatch.setattr("backend.ai.rag.settings.RAG_ENABLED", True)
        monkeypatch.setattr("backend.ai.rag.settings.RAG_LLM_PROVIDER", "ollama")
        response = _build_fallback_response(
            query="q",
            mode="hybrid",
            ret_payload=_payload(1.0),
            status="degraded",
            message="m",
            start_time=time.perf_counter(),
        )
        assert response.generation.model == settings.RAG_OLLAMA_MODEL
        assert response.generation.took_ms == 0.0

    def test_fallback_response_for_the_transformers_provider(self, monkeypatch):
        monkeypatch.setattr("backend.ai.rag.settings.RAG_LLM_PROVIDER", "transformers")
        response = _build_fallback_response(
            query="q",
            mode="lexical",
            ret_payload={"hits": None},
            status="ok",
            message="m",
            start_time=time.perf_counter(),
        )
        assert response.generation.model == settings.RAG_TRANSFORMERS_MODEL
        assert response.search_hits == []

    def test_retrieval_is_performed_by_default(self, monkeypatch, offline_index):
        monkeypatch.setattr("backend.ai.rag.settings.RAG_ENABLED", True)
        seen: list[str] = []
        monkeypatch.setattr(
            "backend.ai.rag._execute_retrieval",
            lambda q, mode, limit: seen.append(mode) or _payload(5.0),
        )
        generate_rag_answer(
            AnswerRequest(query="docker", mode="semantic"), provider=_StubProvider()
        )
        assert seen == ["semantic"]


# --------------------------------------------------------------------------- #
# 10. repository + factory (degraded / error paths)
# --------------------------------------------------------------------------- #


class _BoomSession:
    """Session double whose every statement fails like an unreachable DB."""

    def execute(self, *_a, **_k):
        raise SQLAlchemyError("connection refused")

    def scalars(self, *_a, **_k):
        raise SQLAlchemyError("connection refused")

    def scalar(self, *_a, **_k):
        raise SQLAlchemyError("connection refused")

    def add(self, *_a, **_k):
        raise SQLAlchemyError("connection refused")

    def flush(self):
        raise SQLAlchemyError("connection refused")

    def commit(self):
        raise SQLAlchemyError("connection refused")

    def rollback(self):
        return None

    def close(self):
        return None


class TestRepositoryDegradation:
    def test_degraded_repository_never_raises(self, degraded_repository):
        assert degraded_repository.is_available() is False
        assert degraded_repository.session is None
        assert degraded_repository.list_all() == []
        assert degraded_repository.count() == 0
        assert degraded_repository.find_by_content_hash("x") is None
        assert degraded_repository.upsert(Document(title="t", content="c")) is False
        assert degraded_repository.upsert_many([]) == 0
        degraded_repository.close()

    def test_availability_probe_swallows_errors(self):
        assert DocumentRepository(_BoomSession()).is_available() is False

    def test_reads_degrade_to_empty_on_sqlalchemy_errors(self):
        repo = DocumentRepository(_BoomSession())
        assert repo.list_all() == []
        assert repo.count() == 0
        assert repo.find_by_content_hash("x") is None

    def test_writes_degrade_to_false_on_sqlalchemy_errors(self):
        repo = DocumentRepository(_BoomSession())
        assert repo.upsert(Document(title="t", content="c", content_hash="h")) is False
        assert repo.upsert_many([Document(title="t", content="c")]) == 0

    def test_list_all_limit_is_hardened(self):
        class _Recording(DocumentRepository):
            def __init__(self):  # noqa: D107 - test double
                super().__init__(object())
                self.limits: list[Any] = []

            def list_all(self, *, limit=None):  # type: ignore[override]
                self.limits.append(limit)
                return []

        repo = _Recording()
        repo.list_all(limit=10)
        assert repo.limits == [10]

    def test_make_document_repository_builds_the_repository(self):
        assert isinstance(make_document_repository(None), DocumentRepository)

    def test_close_on_a_repository_with_a_session(self):
        closed: list[bool] = []
        session = type("S", (), {"close": lambda self: closed.append(True)})()
        DocumentRepository(session).close()
        assert closed == [True]


class TestRepositoryFactory:
    def test_best_effort_returns_a_repository_even_when_unavailable(self, monkeypatch):
        monkeypatch.setattr(
            "backend.db.repository_factory._attempt_repository", lambda *_a, **_k: None
        )
        repo = create_best_effort_repository()
        assert isinstance(repo, DocumentRepository)
        assert repo.is_available() is False

    def test_attempt_repository_never_raises(self, monkeypatch):
        def _boom(*_a, **_k):
            raise RuntimeError("driver missing")

        monkeypatch.setattr("backend.db.repository_factory.Database", _boom)
        from backend.db.repository_factory import _attempt_repository as attempt

        assert attempt() is None

    def test_initialised_repository_falls_back_to_degraded(self, monkeypatch):
        monkeypatch.setattr(
            "backend.db.repository_factory._attempt_repository", lambda *_a, **_k: None
        )
        repo = create_initialised_document_repository(attempts=2, delay_seconds=0.0)
        assert repo is not None and repo.is_available() is False

    def test_initialised_repository_retries_until_available(self, monkeypatch):
        calls: list[int] = []

        def _attempt(*_a, **_k):
            calls.append(1)
            return FakeRepository(available=len(calls) >= 2)

        monkeypatch.setattr("backend.db.repository_factory._attempt_repository", _attempt)
        repo = create_initialised_document_repository(attempts=3, delay_seconds=0.0)
        assert repo.is_available() is True
        assert len(calls) == 2

    def test_initialised_repository_keeps_the_last_degraded_repository(self, monkeypatch):
        sentinel = FakeRepository(available=False)
        monkeypatch.setattr(
            "backend.db.repository_factory._attempt_repository", lambda *_a, **_k: sentinel
        )
        repo = create_initialised_document_repository(attempts=1, delay_seconds=0.0)
        assert repo is sentinel

    def test_factory_callable_returns_a_repository(self, monkeypatch):
        monkeypatch.setattr(
            "backend.db.repository_factory._attempt_repository", lambda *_a, **_k: None
        )
        factory = create_document_repository_factory()
        assert isinstance(factory(), DocumentRepository)


class TestFakeRepositoryDouble:
    """The conftest double itself must behave like the real read surface."""

    def test_list_all_is_sorted_and_limited(self, sample_documents):
        repo = FakeRepository.from_documents(sample_documents)
        assert [r.document_id for r in repo.list_all()] == ["dk-1", "ml-1", "py-1", "rd-1"]
        assert len(repo.list_all(limit=2)) == 2
        assert repo.list_all(limit=0) == []
        assert repo.count() == 4

    def test_find_by_content_hash(self, sample_documents):
        repo = FakeRepository.from_documents(sample_documents)
        assert repo.find_by_content_hash("no-such-hash") is None
        found = repo.find_by_content_hash(sample_documents[0].content_hash)
        assert found is not None and found.document_id == "py-1"

    def test_unavailable_and_failing_variants(self):
        assert FakeRepository(available=False).is_available() is False
        broken = FakeRepository([], fail_with=RuntimeError("down"))
        assert broken.is_available() is False
        assert broken.list_all() == []

    def test_close_is_observable(self):
        repo = FakeRepository()
        repo.close()
        assert repo.closed is True


# --------------------------------------------------------------------------- #
# 11. crawler - pure helpers and offline HTTP doubles
# --------------------------------------------------------------------------- #


class TestUrlNormalisation:
    def test_canonical_form(self):
        assert normalize_url("HTTP://Example.COM:80/Path/") == "http://example.com/Path"

    def test_https_default_port_is_dropped(self):
        assert normalize_url("https://example.com:443/") == "https://example.com/"

    def test_non_default_port_is_kept(self):
        assert normalize_url("http://example.com:8080/") == "http://example.com:8080/"

    def test_fragments_are_removed(self):
        assert "#frag" not in normalize_url("https://example.com/a#frag")

    @pytest.mark.parametrize("param", ["utm_source", "gclid", "ref", "spm"])
    def test_tracking_parameters_are_dropped(self, param):
        out = normalize_url(f"https://example.com/a?{param}=1&keep=2")
        assert param not in out
        assert "keep=2" in out

    def test_tracking_removal_can_be_disabled(self):
        out = normalize_url("https://example.com/a?utm_source=1", drop_tracking=False)
        assert "utm_source" in out

    def test_duplicate_slashes_and_dot_segments(self):
        assert normalize_url("https://example.com//a///b/") == "https://example.com/a/b"

    def test_ipv6_hosts_keep_their_brackets(self):
        assert normalize_url("http://[2001:DB8::1]:8080/x") == "http://[2001:db8::1]:8080/x"

    @pytest.mark.parametrize("raw", ["", "   ", "not-a-url", "///path", "://x"])
    def test_unparsable_input_never_raises(self, raw):
        assert isinstance(normalize_url(raw), str)

    def test_canonicalize_is_the_same_contract(self):
        assert canonicalize_url("HTTP://X.com/a") == normalize_url("HTTP://X.com/a")

    def test_resolve_relative_links(self):
        base = "https://example.com/docs/guide/index.html"
        assert resolve_url(base, "../api") == "https://example.com/docs/api"
        assert resolve_url(base, "https://other.org/x") == "https://other.org/x"
        assert resolve_url(base, "#anchor") == "https://example.com/docs/guide/index.html"

    def test_hostname_extraction(self):
        assert hostname_of("https://Example.COM:8443/p") == "example.com"
        assert hostname_of("http://[::1]:80/") == "::1"
        assert hostname_of("not a url") == ""


class TestUrlSafety:
    def test_private_and_loopback_hosts(self):
        for url in (
            "http://127.0.0.1/",
            "http://localhost/",
            "http://10.0.0.1/",
            "http://192.168.1.1/",
            "http://169.254.169.254/",
            "http://0.0.0.0/",
            "http://[::1]/",
            "http://printer.local/",
        ):
            assert is_private_host(url), url

    def test_public_hosts(self):
        for url in ("https://example.com/", "https://docs.python.org/3/", "http://8.8.8.8/"):
            assert not is_private_host(url), url

    def test_empty_host_counts_as_private(self):
        assert is_private_host("")

    @pytest.mark.parametrize(
        "url", ["", "file:///etc/passwd", "ftp://example.com/x", "javascript:alert(1)"]
    )
    def test_dangerous_urls(self, url):
        assert is_dangerous_url(url)
        assert not is_crawlable_url(url)

    def test_embedded_credentials_are_rejected(self):
        assert has_embedded_credentials("https://user:pw@example.com/")
        assert is_dangerous_url("https://user:pw@example.com/")

    def test_hostless_http_url_is_dangerous(self):
        assert is_dangerous_url("http:///path")

    def test_unwanted_extensions(self):
        assert has_unwanted_extension("https://example.com/a.pdf")
        assert has_unwanted_extension("https://example.com/a.PNG")
        assert not has_unwanted_extension("https://example.com/a.html")
        assert not is_crawlable_url("https://example.com/a.zip")
        assert ".pdf" in UNWANTED_EXTENSIONS

    def test_private_hosts_are_crawlable_only_when_explicitly_allowed(self):
        url = "http://127.0.0.1:8000/page"
        assert not is_crawlable_url(url)
        assert is_crawlable_url(url, allow_private_hosts=True)

    def test_is_http_url(self):
        assert is_http_url("http://x/") and is_http_url("https://x/")
        assert not is_http_url("ftp://x/")

    def test_domain_matching_is_exact_or_subdomain(self):
        allowed = ("example.com",)
        assert domain_matches("example.com", allowed)
        assert domain_matches("docs.example.com", allowed)
        assert not domain_matches("notexample.com", allowed)
        assert not domain_matches("example.com.evil.org", allowed)

    def test_domain_matching_normalises_case_and_dots(self):
        assert domain_matches("Docs.Example.COM.", (".example.com",))
        assert not domain_matches("x", ("", "  "))

    def test_scope_prefers_the_allowlist(self):
        assert scope_hosts(("a.com",), ("https://b.com",)) == ("a.com",)

    def test_scope_falls_back_to_seed_hosts(self):
        assert scope_hosts((), ("https://a.com/x", "https://b.com/y", "https://a.com/z")) == (
            "a.com",
            "b.com",
        )

    def test_scope_ignores_unparsable_seeds(self):
        assert scope_hosts((), ("not-a-url",)) == ()


class TestRobotsPolicy:
    def test_robots_url_matches_scheme_host_and_port(self):
        policy = RobotsTxtPolicy("SEEK-Test")
        assert policy._robots_url("https://example.com:8443/a") == (
            "https://example.com:8443/robots.txt"
        )
        assert policy._robots_url("http://example.com/a") == "http://example.com/robots.txt"
        # SEEK always hands absolute URLs around (``hostname_of`` returns "" for
        # a schemeless one, so the crawl skips it earlier), but pin what a
        # netloc-less input degrades to rather than leaving it undefined.
        assert policy._robots_url("example.com/a") == "http:///robots.txt"

    def test_from_text_allows_by_default(self):
        policy = RobotsTxtPolicy.from_text("SEEK-Test", "", host="example.com")
        assert policy.can_fetch("https://example.com/anything")

    def test_from_text_honours_disallow(self):
        policy = RobotsTxtPolicy.from_text(
            "SEEK-Test", "User-agent: *\nDisallow: /private\n", host="example.com"
        )
        assert not policy.can_fetch("https://example.com/private/x")
        assert policy.can_fetch("https://example.com/public")

    def test_from_text_honours_allow(self):
        # ``urllib.robotparser`` is longest-match-wins within one entry but only
        # when the rules are in the file's own order, so the exception is listed
        # first here to prove the allow-rule is actually applied.
        policy = RobotsTxtPolicy.from_text(
            "SEEK-Test",
            "User-agent: *\nAllow: /docs/\nDisallow: /\n",
            host="example.com",
        )
        assert policy.can_fetch("https://example.com/docs/x")
        assert not policy.can_fetch("https://example.com/other")

    def test_unknown_host_is_allowed(self):
        policy = RobotsTxtPolicy.from_text("SEEK-Test", "Disallow: /", host="a.com")
        assert policy.can_fetch("https://b.com/x")

    def test_crawl_delay(self):
        policy = RobotsTxtPolicy.from_text(
            "SEEK-Test", "User-agent: *\nCrawl-delay: 5\n", host="example.com"
        )
        assert policy.crawl_delay("example.com") == 5.0
        assert policy.crawl_delay("unknown.com") == 0.0

    def test_fractional_crawl_delay_is_ignored(self):
        # Documented limitation: the stdlib ``robotparser`` only accepts integer
        # ``Crawl-delay`` values (``line[1].strip().isdigit()``), so a fractional
        # directive degrades to "no delay configured" instead of raising.
        policy = RobotsTxtPolicy.from_text(
            "SEEK-Test", "User-agent: *\nCrawl-delay: 2.5\n", host="example.com"
        )
        assert policy.crawl_delay("example.com") == 0.0

    def test_crawl_delay_without_directive(self):
        policy = RobotsTxtPolicy.from_text("SEEK-Test", "", host="example.com")
        assert policy.crawl_delay("example.com") == 0.0

    def test_crawl_delay_survives_a_broken_parser(self):
        policy = RobotsTxtPolicy.from_text("SEEK-Test", "", host="example.com")

        class _Broken:
            def crawl_delay(self, _ua):
                raise RuntimeError("broken")

        policy._set_parser("broken.com", _Broken())
        assert policy.crawl_delay("broken.com") == 0.0

    def test_can_fetch_survives_a_broken_parser(self):
        policy = RobotsTxtPolicy.from_text("SEEK-Test", "", host="example.com")

        class _Broken:
            def can_fetch(self, *_a):
                raise RuntimeError("broken")

        policy._set_parser("broken.com", _Broken())
        assert policy.can_fetch("https://broken.com/x") is True

    def test_empty_user_agent_allows_everything(self):
        policy = RobotsTxtPolicy.from_text("", "Disallow: /", host="example.com")
        assert policy.can_fetch("https://example.com/x")

    def test_fetch_robots_status_mapping(self, monkeypatch):
        class _AsyncClient:
            def __init__(self, response=None, error=None):
                self._response = response
                self._error = error
                self.requested: list[str] = []

            async def get(self, url, **kwargs):
                self.requested.append(url)
                if self._error is not None:
                    raise self._error
                return self._response

        policy = RobotsTxtPolicy("SEEK-Test", timeout_seconds=1.0)
        allowed = asyncio.run(
            policy._fetch_robots(_AsyncClient(_StubResponse(200, text="User-agent: *\nAllow: /\n")), "https://example.com/")
        )
        assert "Allow" in allowed

        blocked = asyncio.run(
            policy._fetch_robots(_AsyncClient(_StubResponse(403, text="")), "https://example.com/")
        )
        assert "Disallow: /" in blocked

        missing = asyncio.run(
            policy._fetch_robots(_AsyncClient(_StubResponse(404, text="")), "https://example.com/")
        )
        assert missing == ""

        unreachable = asyncio.run(
            policy._fetch_robots(
                _AsyncClient(error=httpx.ConnectError("nope")), "https://example.com/"
            )
        )
        assert unreachable == ""

    def test_ensure_loaded_is_idempotent(self):
        class _AsyncClient:
            def __init__(self):
                self.calls = 0

            async def get(self, url, **kwargs):
                self.calls += 1
                return _StubResponse(200, text="User-agent: *\nDisallow: /\n")

        policy = RobotsTxtPolicy("SEEK-Test")
        client = _AsyncClient()
        asyncio.run(policy.ensure_loaded(client, "https://example.com/a"))
        asyncio.run(policy.ensure_loaded(client, "https://example.com/b"))
        assert client.calls == 1
        assert not policy.can_fetch("https://example.com/a")

    def test_ensure_loaded_ignores_unparsable_urls(self):
        policy = RobotsTxtPolicy("SEEK-Test")
        asyncio.run(policy.ensure_loaded(object(), "not-a-url"))
        assert policy.can_fetch("not-a-url")


class TestExtraction:
    HTML = (
        "<html><head><title>Main Title</title>"
        "<style>body{color:red}</style><script>alert(1)</script></head>"
        "<body><nav>skip me</nav><h1>Heading</h1>"
        "<p>First    paragraph body.</p><p>Second paragraph.</p>"
        "<footer>footer text</footer></body></html>"
    )

    def test_title_prefers_the_title_tag(self):
        from bs4 import BeautifulSoup

        title, _ = extract_text(self.HTML, url="https://example.com/p")
        assert title == "Main Title"

    def test_title_falls_back_to_h1_then_hostname(self):
        from bs4 import BeautifulSoup

        assert (
            extract_title(BeautifulSoup("<html><h1>H1 Title</h1></html>", "html.parser"), "https://x/")
            == "H1 Title"
        )
        assert (
            extract_title(BeautifulSoup("<html><body>no title</body></html>", "html.parser"), "https://example.com/p")
            == "example.com"
        )

    def test_chrome_is_stripped(self):
        _, text = extract_text(self.HTML, url="https://example.com/p")
        assert "alert(1)" not in text
        assert "color:red" not in text
        assert "skip me" not in text
        assert "footer text" not in text
        assert "First paragraph body." in text

    def test_text_is_whitespace_normalised(self):
        _, text = extract_text(self.HTML, url="https://example.com/")
        assert "  " not in text

    def test_max_chars_truncates(self):
        _, text = extract_text("<p>" + "x" * 500 + "</p>", url="", max_chars=100)
        assert len(text) == 100

    def test_empty_html(self):
        title, text = extract_text("", url="https://example.com/p")
        assert title == "example.com"
        assert text == ""

    def test_hash_is_stable_and_content_addressed(self):
        assert hash_text("abc") == hash_text("abc")
        assert hash_text("abc") != hash_text("abd")
        assert len(hash_text("abc")) == 64

    def test_chunking(self):
        assert chunk_text("") == ()
        assert chunk_text("abcdef", size=64) == ("abcdef",)
        # Sizes below the 64-character floor are clamped, not rejected.
        assert chunk_text("a" * 10, size=4) == ("a" * 10,)
        assert chunk_text("a" * 200, size=64) == ("a" * 64, "a" * 64, "a" * 64, "a" * 8)
        assert len(chunk_text("x" * 5000)) == len(chunk_text("x" * 5000))

    def test_chunking_covers_every_character_exactly_once(self):
        text = "".join(str(i % 10) for i in range(999))
        assert "".join(chunk_text(text, size=64)) == text


class TestLinkExtraction:
    HTML = (
        '<a href="/a">a</a>'
        '<a href="b">b</a>'
        '<a href="#frag">no</a>'
        '<a href="javascript:void(0)">no</a>'
        '<a href="mailto:a@b.c">no</a>'
        '<a href="tel:+1">no</a>'
        '<a href="  ">no</a>'
        '<a>no href</a>'
    )

    def test_only_real_links_are_yielded(self):
        assert list(_links_from(self.HTML)) == ["/a", "b"]

    def test_no_links(self):
        assert list(_links_from("<p>nothing</p>")) == []


class TestFetcher:
    class _Client:
        def __init__(self, response=None, error=None):
            self._response = response
            self._error = error
            self.calls: list[dict[str, Any]] = []

        async def get(self, url, **kwargs):
            self.calls.append({"url": url, **kwargs})
            if self._error is not None:
                raise self._error
            return self._response

    def _response(self, *, body=b"<html></html>", status=200, content_type="text/html; charset=utf-8"):
        return httpx.Response(
            status_code=status,
            headers={"content-type": content_type},
            content=body,
            request=httpx.Request("GET", "https://example.com/p"),
        )

    def test_successful_fetch(self):
        client = self._Client(self._response(body=b"hello"))
        result = asyncio.run(fetch(client, "https://example.com/p"))
        assert result.ok
        assert result.body == b"hello"
        assert result.status_code == 200
        assert result.error_code == ""
        assert result.as_dict()["body_bytes"] == 5
        assert client.calls[0]["headers"]["User-Agent"]

    def test_missing_content_type_is_treated_as_html(self):
        client = self._Client(self._response(content_type=""))
        assert asyncio.run(fetch(client, "https://example.com/p")).ok

    def test_timeout_is_typed(self):
        client = self._Client(error=httpx.TimeoutException("slow"))
        result = asyncio.run(fetch(client, "https://example.com/p"))
        assert result.error_code == ERR_TIMEOUT
        assert not result.ok

    def test_redirect_loop_is_typed(self):
        client = self._Client(error=httpx.TooManyRedirects("loop"))
        assert asyncio.run(fetch(client, "https://x/")).error_code == ERR_REDIRECTS

    def test_transport_error_is_typed(self):
        client = self._Client(error=httpx.ConnectError("refused"))
        assert asyncio.run(fetch(client, "https://x/")).error_code == ERR_TRANSPORT

    def test_non_html_content_is_rejected(self):
        client = self._Client(self._response(content_type="application/pdf"))
        result = asyncio.run(fetch(client, "https://x/f.pdf"))
        assert result.error_code == ERR_NON_HTML
        assert not result.ok

    def test_oversized_bodies_are_rejected(self):
        client = self._Client(self._response(body=b"x" * 100))
        result = asyncio.run(fetch(client, "https://x/", max_bytes=10))
        assert result.error_code == ERR_TOO_LARGE

    def test_empty_body_is_allowed(self):
        client = self._Client(self._response(body=b""))
        result = asyncio.run(fetch(client, "https://x/"))
        assert result.ok and result.body == b""


class TestCrawlModels:
    def test_sanitized_bounds_every_numeric_field(self):
        config = CrawlJobConfig(
            seed_urls=("https://example.com",),
            max_pages=0,
            max_depth=-4,
            delay_seconds=-1.0,
            concurrency=0,
            timeout_seconds=0.0,
            max_redirects=-2,
            max_content_chars=10,
        ).sanitized()
        assert config.max_pages == 1
        assert config.max_depth == 0
        assert config.delay_seconds == 0.0
        assert config.concurrency == 1
        assert config.timeout_seconds == 1.0
        assert config.max_redirects == 0
        assert config.max_content_chars == 1000

    def test_sanitized_caps_upper_bounds(self):
        config = CrawlJobConfig(
            seed_urls=("https://example.com",),
            max_pages=10_000,
            max_depth=99,
            concurrency=99,
            max_redirects=99,
        ).sanitized()
        assert config.max_pages == 1000
        assert config.max_depth == 32
        assert config.concurrency == 32
        assert config.max_redirects == 32

    def test_sanitized_normalises_urls_and_domains(self):
        config = CrawlJobConfig(
            seed_urls=("  https://a.example  ", "   ", ""),
            allowed_domains=("  .Example.COM ", ""),
        ).sanitized()
        assert config.seed_urls == ("https://a.example",)
        assert config.allowed_domains == ("example.com",)

    def test_sanitized_restores_the_default_user_agent(self):
        config = CrawlJobConfig(seed_urls=("https://a",), user_agent="").sanitized()
        assert config.user_agent == "SEEK-Crawler/1.0"

    def test_sanitized_does_not_mutate_the_original(self):
        original = CrawlJobConfig(seed_urls=("https://a",), max_pages=0)
        original.sanitized()
        assert original.max_pages == 0

    def test_job_lifecycle(self):
        job = CrawlJob(job_id="j1", config=CrawlJobConfig(seed_urls=("https://a",)))
        assert job.status is CrawlStatus.PENDING
        job.start()
        assert job.status is CrawlStatus.RUNNING
        assert job.started_at
        job.append_page(
            CrawlPage(
                url="https://a",
                final_url="https://a",
                status_code=200,
                title="T",
                text="body",
                content_hash="h",
            )
        )
        job.append_failure(FailedFetch(url="https://b", status_code=500))
        job.complete(CrawlReport(pages_crawled=1, message="done"))
        assert job.status is CrawlStatus.COMPLETED
        assert job.finished_at

    def test_job_failure_marks_the_status(self):
        job = CrawlJob(job_id="j1", config=CrawlJobConfig(seed_urls=("https://a",)))
        job.complete(CrawlReport(), error="RuntimeError: boom")
        assert job.status is CrawlStatus.FAILED
        assert job.error == "RuntimeError: boom"

    def test_to_dict_is_json_serialisable_and_complete(self):
        job = CrawlJob(job_id="j1", config=CrawlJobConfig(seed_urls=("https://a",), max_pages=7))
        payload = job.to_dict()
        json.dumps(payload)
        assert payload["job_id"] == "j1"
        assert payload["status"] == "pending"
        assert payload["seed_urls"] == ["https://a"]
        assert payload["max_pages"] == 7
        assert payload["pages_crawled"] == 0
        assert payload["report"]["pages_crawled"] == 0
        assert payload["error"] == ""

    def test_to_dict_includes_the_report_when_present(self):
        job = CrawlJob(job_id="j1", config=CrawlJobConfig(seed_urls=("https://a",)))
        job.complete(CrawlReport(pages_crawled=3, pages_failed=1, message="ok"))
        assert job.to_dict()["report"]["pages_crawled"] == 3
        assert job.to_dict()["report"]["message"] == "ok"


def _page(url="https://example.com/a", text="some crawlable body text", title="T"):
    return CrawlPage(
        url=url,
        final_url=url,
        status_code=200,
        title=title,
        text=text,
        content_hash=hash_text(text),
        chunks=chunk_text(text),
        fetched_at="2026-01-01T00:00:00Z",
    )


class TestCrawlStore:
    def test_recording_and_deduplication(self):
        store = CrawlStore()
        assert store.record(_page()) is True
        assert store.record(_page(url="https://example.com/b")) is False
        assert store.count() == 1

    def test_visited_tracking(self):
        store = CrawlStore()
        assert not store.is_visited("u")
        store.mark_visited("u")
        assert store.is_visited("u")
        assert store.mark_visited("u") is None

    def test_hash_tracking(self):
        store = CrawlStore()
        page = _page()
        store.record(page)
        assert store.has_hash(page.content_hash)
        assert not store.has_hash("other")

    def test_to_processed_documents(self):
        store = CrawlStore()
        store.record(_page())
        docs = store.to_processed_documents()
        assert len(docs) == 1
        assert docs[0].document_id.startswith("crawl-")
        assert docs[0].source == "https://example.com/a"
        assert docs[0].tokens

    def test_pages_without_tokens_are_skipped(self):
        store = CrawlStore()
        store.record(_page(text="the a an and"))
        assert store.to_processed_documents() == []

    def test_title_falls_back_to_the_url(self):
        store = CrawlStore()
        store.record(_page(title=""))
        assert store.to_processed_documents()[0].title == "https://example.com/a"

    def test_persistence_is_best_effort_without_a_database(self, monkeypatch):
        import backend.crawler.service as service_module

        monkeypatch.setattr(service_module, "_PERSIST_REPO", None)
        monkeypatch.setattr(
            "backend.db.repository_factory.create_initialised_document_repository",
            lambda *_a, **_k: make_document_repository(None),
        )
        assert service_module._persist_best_effort(_page()) == 0

    def test_persistence_swallows_errors(self, monkeypatch):
        import backend.crawler.service as service_module

        def _boom(*_a, **_k):
            raise OSError("no db driver")

        monkeypatch.setattr(service_module, "_PERSIST_REPO", None)
        monkeypatch.setattr(
            "backend.db.repository_factory.create_initialised_document_repository", _boom
        )
        assert service_module._persist_best_effort(_page()) == 0


class TestCrawlManager:
    def test_seedless_jobs_are_rejected(self):
        manager = CrawlManager()
        with pytest.raises(ValueError):
            manager.start_job(CrawlJobConfig(seed_urls=("   ", "")))

    def test_job_registry_and_lifecycle(self, monkeypatch):
        monkeypatch.setattr("backend.crawler.service._persist_best_effort", lambda _p: 0)

        async def _execute(self, job):
            page = _page()
            # The real ``_execute`` hands pages to ``a_crawl``, which is what
            # records them in the shared store; mirror that contract here.
            self.store.record(page)
            job.append_page(page)
            job.complete(CrawlReport(pages_crawled=1, message="done"))

        monkeypatch.setattr(CrawlManager, "_execute", _execute)
        manager = CrawlManager()
        job = manager.start_job(CrawlJobConfig(seed_urls=("https://example.com",)))
        assert job.job_id.startswith("crawl_")
        assert manager.get_job(job.job_id) is job
        assert manager.get_job("missing") is None
        assert [j.job_id for j in manager.list_jobs()] == [job.job_id]

        deadline = time.time() + 5.0
        while job.status is not CrawlStatus.COMPLETED and time.time() < deadline:
            time.sleep(0.01)
        assert job.status is CrawlStatus.COMPLETED
        assert len(job.pages) == 1
        assert manager.store.count() == 1
        assert manager.store.to_processed_documents()[0].document_id.startswith("crawl-")

    def test_job_failures_never_escape_the_thread(self, monkeypatch):
        async def _execute(self, job):
            raise RuntimeError("network exploded")

        monkeypatch.setattr(CrawlManager, "_execute", _execute)
        manager = CrawlManager()
        job = manager.start_job(CrawlJobConfig(seed_urls=("https://example.com",)))
        deadline = time.time() + 5.0
        while job.status is CrawlStatus.PENDING and time.time() < deadline:
            time.sleep(0.01)
        while job.status is not CrawlStatus.FAILED and time.time() < deadline:
            time.sleep(0.01)
        assert job.status is CrawlStatus.FAILED
        assert "RuntimeError" in job.error

    def test_manager_shares_the_injected_store(self):
        store = CrawlStore()
        assert CrawlManager(store=store).store is store


# --------------------------------------------------------------------------- #
# 12. index + faiss artifact stores
# --------------------------------------------------------------------------- #


def _metadata(documents, **overrides) -> IndexMetadata:
    payload = {
        "document_count": len(documents),
        "max_document_id": max_document_id(documents),
        "corpus_hash": compute_document_signature(documents),
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "documents": tuple(
            {"document_id": d.document_id, "content_hash": d.content_hash} for d in documents
        ),
    }
    payload.update(overrides)
    return IndexMetadata(**payload)


class TestIndexMetadata:
    def test_round_trip(self, sample_documents):
        metadata = _metadata(sample_documents)
        assert IndexMetadata.from_dict(metadata.to_dict()) == metadata

    def test_defaults_tolerate_missing_keys(self):
        metadata = IndexMetadata.from_dict({})
        assert metadata.format_version == INDEX_FORMAT_VERSION
        assert metadata.index_version == 1
        assert metadata.document_count == 0
        assert metadata.documents == ()

    def test_non_object_metadata_is_rejected(self):
        for bad in (None, [], "meta", 3):
            with pytest.raises(ValueError):
                IndexMetadata.from_dict(bad)

    def test_document_signature_is_order_independent(self, sample_documents):
        forward = compute_document_signature(sample_documents)
        backward = compute_document_signature(list(reversed(sample_documents)))
        assert forward == backward

    def test_document_signature_changes_with_content(self, sample_documents, doc):
        before = compute_document_signature(sample_documents)
        after = compute_document_signature([*sample_documents, doc("new", "N", "new body")])
        assert before != after

    def test_signature_of_nothing_is_stable(self):
        assert compute_document_signature([]) == compute_document_signature([])

    def test_max_document_id_skips_non_numeric_ids(self, sample_documents, doc):
        assert max_document_id(sample_documents) == 0
        assert max_document_id([doc("10", "A", "a"), doc("2", "B", "b")]) == 10
        assert max_document_id([]) == 0


class TestIndexArtifactLifecycle:
    def _save(self, root, documents, **meta_overrides):
        save_index(
            root,
            documents,
            _metadata(documents, **meta_overrides),
            k1=1.5,
            b=0.75,
            epsilon=0.25,
            default_limit=10,
            max_limit=50,
        )

    def test_valid_artifact_round_trips(self, tmp_path, sample_documents):
        self._save(tmp_path, sample_documents)
        result = load_index(tmp_path)
        assert result.valid, result.reason
        assert result.payload is not None
        assert len(result.payload.documents) == len(sample_documents)
        assert result.payload.k1 == 1.5
        assert result.payload.max_limit == 50
        assert [d.document_id for d in result.payload.documents] == [
            d.document_id for d in sample_documents
        ]

    def test_presence_detection(self, tmp_path, sample_documents):
        assert not is_index_present(tmp_path)
        self._save(tmp_path, sample_documents)
        assert is_index_present(tmp_path)
        assert (tmp_path / ARTIFACT_FILE).is_file()
        assert (tmp_path / METADATA_FILE).is_file()

    def test_presence_requires_both_files(self, tmp_path, sample_documents):
        self._save(tmp_path, sample_documents)
        (tmp_path / METADATA_FILE).unlink()
        assert not is_index_present(tmp_path)

    def test_missing_artifact(self, tmp_path):
        result = load_index(tmp_path)
        assert not result.valid
        assert "artifact missing" in result.reason
        assert result.payload is None and result.metadata is None

    def test_corrupt_artifact(self, tmp_path, sample_documents):
        self._save(tmp_path, sample_documents)
        (tmp_path / ARTIFACT_FILE).write_bytes(b"not a pickle at all")
        result = load_index(tmp_path)
        assert not result.valid
        assert "corrupt index artifact" in result.reason

    def test_truncated_artifact(self, tmp_path, sample_documents):
        self._save(tmp_path, sample_documents)
        blob = (tmp_path / ARTIFACT_FILE).read_bytes()
        (tmp_path / ARTIFACT_FILE).write_bytes(blob[: len(blob) // 2])
        assert not load_index(tmp_path).valid

    def test_unsupported_kind(self, tmp_path):
        (tmp_path / METADATA_FILE).write_text(
            json.dumps({"format_version": INDEX_FORMAT_VERSION, "document_count": 0, "documents": [], "corpus_hash": compute_document_signature([])}),
            encoding="utf-8",
        )
        (tmp_path / ARTIFACT_FILE).write_bytes(
            pickle.dumps({"kind": "not-bm25", "format_version": INDEX_FORMAT_VERSION})
        )
        assert "unsupported index artifact kind" in load_index(tmp_path).reason

    def test_unsupported_format_version(self, tmp_path):
        (tmp_path / METADATA_FILE).write_text(
            json.dumps({"format_version": 99, "document_count": 0, "documents": [], "corpus_hash": compute_document_signature([])}),
            encoding="utf-8",
        )
        (tmp_path / ARTIFACT_FILE).write_bytes(
            pickle.dumps({"kind": "bm25", "format_version": 99})
        )
        result = load_index(tmp_path)
        assert not result.valid
        assert "unsupported index format version" in result.reason

    def test_missing_metadata(self, tmp_path, sample_documents):
        self._save(tmp_path, sample_documents)
        (tmp_path / METADATA_FILE).unlink()
        result = load_index(tmp_path)
        assert not result.valid
        assert "metadata missing" in result.reason

    def test_corrupt_metadata_json(self, tmp_path, sample_documents):
        self._save(tmp_path, sample_documents)
        (tmp_path / METADATA_FILE).write_text("{not json", encoding="utf-8")
        assert not load_index(tmp_path).valid
        assert read_metadata(tmp_path) is None

    def test_document_count_mismatch(self, tmp_path, sample_documents):
        self._save(tmp_path, sample_documents, document_count=99)
        result = load_index(tmp_path)
        assert not result.valid
        assert "document count mismatch" in result.reason

    def test_content_signature_mismatch_is_a_stale_artifact(self, tmp_path, sample_documents):
        self._save(tmp_path, sample_documents, corpus_hash="deadbeef")
        result = load_index(tmp_path)
        assert not result.valid
        assert "content signature mismatch" in result.reason

    def test_unreadable_document_payload_is_rejected(self, tmp_path):
        (tmp_path / METADATA_FILE).write_text(
            json.dumps(
                {
                    "format_version": INDEX_FORMAT_VERSION,
                    "document_count": 0,
                    "documents": [],
                    "corpus_hash": compute_document_signature([]),
                }
            ),
            encoding="utf-8",
        )
        # A documents list holding a non-mapping blows up document_from_dict.
        (tmp_path / ARTIFACT_FILE).write_bytes(
            pickle.dumps(
                {
                    "kind": "bm25",
                    "format_version": INDEX_FORMAT_VERSION,
                    "documents": "not-a-list-of-dicts",
                }
            )
        )
        result = load_index(tmp_path)
        assert not result.valid
        assert "invalid document data" in result.reason

    def test_saving_leaves_no_temporary_files(self, tmp_path, sample_documents):
        self._save(tmp_path, sample_documents)
        assert list(tmp_path.glob("*.tmp")) == []

    def test_a_failed_write_keeps_the_previous_artifact(self, tmp_path, sample_documents, monkeypatch):
        import backend.search.index_store as store

        self._save(tmp_path, sample_documents)
        before = (tmp_path / ARTIFACT_FILE).read_bytes()

        def _boom(_path, _data):
            raise OSError("disk full")

        monkeypatch.setattr(store, "_atomic_write", _boom)
        with pytest.raises(OSError):
            self._save(tmp_path, sample_documents)
        assert (tmp_path / ARTIFACT_FILE).read_bytes() == before

    def test_metadata_written_before_the_artifact_is_rejected(self, tmp_path, sample_documents):
        self._save(tmp_path, sample_documents)
        # Metadata alone is not a usable index.
        (tmp_path / ARTIFACT_FILE).unlink()
        assert not load_index(tmp_path).valid

    def test_remove_index_is_idempotent(self, tmp_path, sample_documents):
        self._save(tmp_path, sample_documents)
        remove_index(tmp_path)
        assert not is_index_present(tmp_path)
        remove_index(tmp_path)

    def test_index_version_increments_across_builds(self, tmp_path, sample_documents):
        self._save(tmp_path, sample_documents, index_version=1)
        assert load_index(tmp_path).metadata.index_version == 1
        self._save(tmp_path, sample_documents, index_version=2)
        assert load_index(tmp_path).metadata.index_version == 2


class TestFaissMetadata:
    def test_round_trip(self, sample_documents):
        from backend.search.faiss_store import FaissIndexMetadata, build_faiss_metadata

        class _Vectors:
            shape = (len(sample_documents), 8)

        metadata = build_faiss_metadata(
            documents=sample_documents,
            vectors=_Vectors(),
            model="test-model",
        )
        assert metadata.dimension == 8
        assert metadata.document_count == len(sample_documents)
        assert metadata.corpus_hash == compute_document_signature(sample_documents)
        assert FaissIndexMetadata.from_dict(metadata.to_dict()) == metadata

    def test_index_version_is_incremented(self, sample_documents):
        from backend.search.faiss_store import build_faiss_metadata

        class _Vectors:
            shape = (len(sample_documents), 4)

        first = build_faiss_metadata(documents=sample_documents, vectors=_Vectors(), model="m")
        second = build_faiss_metadata(
            documents=sample_documents, vectors=_Vectors(), model="m", previous=first
        )
        assert second.index_version == first.index_version + 1
        assert second.created_at == first.created_at

    def test_non_object_metadata_is_rejected(self):
        from backend.search.faiss_store import FaissIndexMetadata

        with pytest.raises(ValueError):
            FaissIndexMetadata.from_dict(["not", "a", "dict"])

    def test_presence_and_removal(self, tmp_path):
        from backend.search.faiss_store import (
            FAISS_INDEX_FILE,
            FAISS_METADATA_FILE,
            is_faiss_present,
            remove_faiss_index,
        )

        assert not is_faiss_present(tmp_path)
        remove_faiss_index(tmp_path)
        (tmp_path / FAISS_INDEX_FILE).write_bytes(b"x")
        (tmp_path / FAISS_METADATA_FILE).write_text("{}", encoding="utf-8")
        assert is_faiss_present(tmp_path)
        remove_faiss_index(tmp_path)
        assert not is_faiss_present(tmp_path)

    def test_load_reports_a_missing_index_file(self, tmp_path):
        from backend.search.faiss_store import load_faiss_index

        result = load_faiss_index(tmp_path)
        assert not result.valid
        assert "index file missing" in result.reason

    def test_load_reports_missing_metadata(self, tmp_path):
        from backend.search.faiss_store import FAISS_INDEX_FILE, load_faiss_index

        (tmp_path / FAISS_INDEX_FILE).write_bytes(b"x")
        result = load_faiss_index(tmp_path)
        assert not result.valid
        assert "metadata missing" in result.reason

    def test_load_reports_unreadable_metadata(self, tmp_path):
        from backend.search.faiss_store import (
            FAISS_INDEX_FILE,
            FAISS_METADATA_FILE,
            load_faiss_index,
            read_faiss_metadata,
        )

        (tmp_path / FAISS_INDEX_FILE).write_bytes(b"x")
        (tmp_path / FAISS_METADATA_FILE).write_text("{oops", encoding="utf-8")
        assert read_faiss_metadata(tmp_path) is None
        assert "metadata missing" in load_faiss_index(tmp_path).reason

    def test_load_rejects_an_unsupported_format_version(self, tmp_path):
        from backend.search.faiss_store import (
            FAISS_INDEX_FILE,
            FAISS_METADATA_FILE,
            load_faiss_index,
        )

        (tmp_path / FAISS_INDEX_FILE).write_bytes(b"x")
        (tmp_path / FAISS_METADATA_FILE).write_text(
            json.dumps({"format_version": 42, "model": "m", "dimension": 4, "document_count": 0, "documents": []}),
            encoding="utf-8",
        )
        result = load_faiss_index(tmp_path)
        assert not result.valid
        assert "unsupported faiss format version" in result.reason

    def test_load_requires_model_and_dimension(self, tmp_path):
        from backend.search.faiss_store import (
            FAISS_INDEX_FILE,
            FAISS_METADATA_FILE,
            load_faiss_index,
        )

        (tmp_path / FAISS_INDEX_FILE).write_bytes(b"x")
        (tmp_path / FAISS_METADATA_FILE).write_text(
            json.dumps({"format_version": 1, "model": "", "dimension": 0, "document_count": 0, "documents": []}),
            encoding="utf-8",
        )
        assert "model/dimension" in load_faiss_index(tmp_path).reason


# --------------------------------------------------------------------------- #
# 13. settings
# --------------------------------------------------------------------------- #


class TestSettings:
    def test_cors_origins_are_split_and_trimmed(self):
        local = Settings(CORS_ORIGINS=" http://a , ,http://b ")
        assert local.cors_origins_list == ["http://a", "http://b"]

    def test_empty_cors_origins(self):
        assert Settings(CORS_ORIGINS="  ").cors_origins_list == []

    def test_index_paths(self):
        local = Settings(STORAGE_INDEX_PATH="artifacts", INDEX_SUBDIR="bm25")
        assert local.index_dir.replace("\\", "/") == "artifacts/bm25"

    def test_semantic_paths(self):
        local = Settings(
            SEMANTIC_INDEX_PATH="artifacts",
            FAISS_INDEX_FILE="idx.bin",
            FAISS_METADATA_FILE="idx.json",
        )
        assert local.semantic_index_dir.replace("\\", "/") == "artifacts"
        assert local.faiss_index_path.replace("\\", "/") == "artifacts/idx.bin"
        assert local.faiss_metadata_path.replace("\\", "/") == "artifacts/idx.json"

    def test_defaults_match_the_api_contract(self):
        assert settings.SEARCH_DEFAULT_LIMIT == 10
        assert settings.SEARCH_MAX_LIMIT == 50
        assert settings.MODE_MAX_LIMIT == 50
        assert settings.BM25_K1 == 1.5
        assert settings.BM25_B == 0.75

    def test_unknown_env_keys_are_ignored(self):
        assert Settings(SOME_TOTALLY_UNKNOWN_KEY="x").APP_NAME


# --------------------------------------------------------------------------- #
# 14. light performance smoke tests (generous bounds, no flaky timing)
# --------------------------------------------------------------------------- #


class TestPerformanceSmoke:
    @staticmethod
    def _corpus(size: int = 1500) -> list[ProcessedDocument]:
        vocabulary = [
            "python", "docker", "container", "index", "search", "bm25", "vector",
            "embedding", "semantic", "crawler", "postgres", "fastapi", "query",
            "document", "token", "rank", "snippet", "artifact", "persist", "refresh",
        ]
        documents: list[ProcessedDocument] = []
        for i in range(size):
            words = " ".join(
                vocabulary[(i + j) % len(vocabulary)] for j in range(40)
            )
            documents.append(make_document(f"perf-{i:05d}", f"Doc {i}", words))
        return documents

    def test_tokenisation_throughput(self):
        corpus = self._corpus(500)
        started = time.perf_counter()
        for document in corpus:
            tokenize(document.content)
        elapsed = time.perf_counter() - started
        assert elapsed < 10.0, f"tokenising 500 documents took {elapsed:.2f}s"

    def test_index_build_and_query_latency(self):
        documents = self._corpus()
        engine = SearchEngine(documents)
        started = time.perf_counter()
        for i in range(20):
            engine.search(f"python vector {i}")
        elapsed = time.perf_counter() - started
        assert elapsed < 20.0, f"20 queries over 1500 documents took {elapsed:.2f}s"

    def test_snippet_rendering_does_not_dominate(self):
        documents = self._corpus(300)
        engine = SearchEngine(documents)
        started = time.perf_counter()
        response = engine.search("docker container", limit=50)
        elapsed = time.perf_counter() - started
        assert response.hits
        assert elapsed < 10.0, f"50 snippets took {elapsed:.2f}s"

    def test_artifact_round_trip_scales(self, tmp_path):
        documents = self._corpus(1000)
        metadata = _metadata(documents)
        started = time.perf_counter()
        save_index(
            tmp_path,
            documents,
            metadata,
            k1=1.5,
            b=0.75,
            epsilon=0.25,
            default_limit=10,
            max_limit=50,
        )
        result = load_index(tmp_path)
        elapsed = time.perf_counter() - started
        assert result.valid
        assert elapsed < 20.0, f"persisting 1000 documents took {elapsed:.2f}s"
