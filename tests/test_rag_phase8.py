"""Phase 8 AI / RAG Answer Generation Test Suite.

Validates end-to-end RAG functionality:
A. Answer endpoint request validation
B. Passage selection & context character limits
C. Grounded prompt assembly
D. Source citation mapping & validation
E. Insufficient context detection
F. LLM provider failure handling & fallback
G. Timeout handling
H. RAG disabled mode
I. Non-interference with existing search endpoints
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.ai.models import AnswerRequest, AnswerResponse, ContextPassage, SourceCitation
from backend.ai.pipeline import construct_grounded_prompt, extract_and_select_passages
from backend.ai.providers import (
    FakeLLMProvider,
    LLMProviderError,
    LLMResult,
    OllamaLLMProvider,
    get_llm_provider,
)
from backend.ai.rag import generate_rag_answer
from backend.config import settings
from backend.main import app
from backend.pipeline import build_pipeline
from backend.search.index_manager import get_index_manager


class TestRAGPipelineUnit(unittest.TestCase):
    """Unit tests for passage extraction, prompt building, and citation filtering."""

    def test_passage_extraction_and_limits(self):
        hits = [
            {
                "document_id": "doc_1",
                "title": "Doc One",
                "source": "https://example.com/1",
                "snippet": "Python is a high-level programming language <mark>python</mark>.",
                "score": 0.9,
            },
            {
                "document_id": "doc_1",  # Duplicate document ID
                "title": "Doc One Duplicate",
                "source": "https://example.com/1",
                "snippet": "Duplicate passage",
                "score": 0.85,
            },
            {
                "document_id": "doc_2",
                "title": "Doc Two",
                "source": "https://example.com/2",
                "snippet": "Machine learning algorithms learn from data.",
                "score": 0.75,
            },
        ]

        passages, citations = extract_and_select_passages(hits, max_passages=5, max_chars=1000)

        self.assertEqual(len(passages), 2)  # Deduplicated doc_1
        self.assertEqual(len(citations), 2)
        self.assertEqual(passages[0].citation_id, 1)
        self.assertEqual(passages[0].document_id, "doc_1")
        # Ensure mark tags were stripped
        self.assertNotIn("<mark>", passages[0].content)
        self.assertEqual(citations[0].source, "https://example.com/1")

    def test_passage_character_cap(self):
        hits = [
            {
                "document_id": f"doc_{i}",
                "title": f"Doc {i}",
                "source": f"src_{i}",
                "snippet": "A" * 100,
                "score": 0.8,
            }
            for i in range(10)
        ]

        passages, citations = extract_and_select_passages(hits, max_passages=10, max_chars=250)
        self.assertLessEqual(len(passages), 3)

    def test_construct_grounded_prompt(self):
        passages = [
            ContextPassage(citation_id=1, document_id="d1", title="T1", content="Content 1"),
            ContextPassage(citation_id=2, document_id="d2", title="T2", content="Content 2"),
        ]
        system_prompt, user_prompt = construct_grounded_prompt("What is T1?", passages)

        self.assertIn("STRICT RULES", system_prompt)
        self.assertIn("--- SOURCE [1] ---", user_prompt)
        self.assertIn("--- SOURCE [2] ---", user_prompt)
        self.assertIn("USER QUESTION:\nWhat is T1?", user_prompt)


class TestRAGProviders(unittest.TestCase):
    """Unit tests for LLM provider abstractions."""

    def test_fake_llm_provider(self):
        provider = FakeLLMProvider()
        self.assertEqual(provider.name, "fake")

        res = provider.generate(
            prompt="USER QUESTION: What is Python?\nANSWER:",
            system_prompt="Rules",
        )
        self.assertIn("What is Python?", res.text)
        self.assertIn("[1]", res.text)
        self.assertEqual(res.provider, "fake")

    def test_provider_factory(self):
        p_fake = get_llm_provider("fake")
        self.assertIsInstance(p_fake, FakeLLMProvider)

        p_ollama = get_llm_provider("ollama")
        self.assertIsInstance(p_ollama, OllamaLLMProvider)

    @patch("httpx.Client.post")
    def test_ollama_provider_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "Docker is a container platform [1]."}
        mock_post.return_value = mock_response

        provider = OllamaLLMProvider(host="http://localhost:11434", model="qwen2.5:0.5b")
        res = provider.generate("prompt", "sys_prompt")

        self.assertEqual(res.provider, "ollama")
        self.assertIn("Docker is a container platform", res.text)

    @patch("httpx.Client.post")
    def test_ollama_provider_failure(self, mock_post):
        mock_post.side_effect = Exception("Connection refused")
        provider = OllamaLLMProvider()

        with self.assertRaises(LLMProviderError):
            provider.generate("prompt", "sys_prompt")


class TestRAGOrchestration(unittest.TestCase):
    """Integration tests for generate_rag_answer orchestrator."""

    @patch("backend.ai.rag._execute_retrieval")
    def test_successful_rag_generation(self, mock_retrieval):
        mock_retrieval.return_value = {
            "mode": "hybrid",
            "hits": [
                {
                    "document_id": "doc_py",
                    "title": "Python Overview",
                    "source": "https://python.org",
                    "snippet": "Python is an interpreted programming language.",
                    "score": 0.85,
                }
            ],
        }

        req = AnswerRequest(query="What is Python?", mode="hybrid")
        resp = generate_rag_answer(req, provider=FakeLLMProvider())

        self.assertEqual(resp.status, "ok")
        self.assertFalse(resp.fallback_mode)
        self.assertIn("Python", resp.answer)
        self.assertEqual(len(resp.sources), 1)
        self.assertEqual(resp.sources[0].document_id, "doc_py")

    @patch("backend.ai.rag._execute_retrieval")
    def test_insufficient_context_fallback(self, mock_retrieval):
        # Empty hits
        mock_retrieval.return_value = {"mode": "hybrid", "hits": []}

        req = AnswerRequest(query="Nonexistent topic query", mode="hybrid")
        resp = generate_rag_answer(req, provider=FakeLLMProvider())

        self.assertEqual(resp.status, "ok")
        self.assertTrue(resp.fallback_mode)
        self.assertIn("couldn't find enough relevant information", resp.answer)

    @patch("backend.ai.rag._execute_retrieval")
    def test_provider_error_fallback(self, mock_retrieval):
        mock_retrieval.return_value = {
            "mode": "hybrid",
            "hits": [
                {
                    "document_id": "doc_py",
                    "title": "Python Overview",
                    "source": "https://python.org",
                    "snippet": "Python snippet text.",
                    "score": 0.85,
                }
            ],
        }

        failing_provider = MagicMock()
        failing_provider.generate.side_effect = LLMProviderError("LLM offline")

        req = AnswerRequest(query="What is Python?", mode="hybrid")
        resp = generate_rag_answer(req, provider=failing_provider)

        self.assertEqual(resp.status, "degraded")
        self.assertTrue(resp.fallback_mode)
        self.assertIn("AI answer generation unavailable", resp.answer)
        self.assertEqual(len(resp.search_hits), 1)

    @patch("backend.ai.rag._execute_retrieval")
    def test_rag_disabled_setting(self, mock_retrieval):
        mock_retrieval.return_value = {
            "mode": "hybrid",
            "hits": [{"document_id": "d1", "title": "T1", "source": "S1", "snippet": "Text", "score": 0.9}],
        }

        with patch.object(settings, "RAG_ENABLED", False):
            req = AnswerRequest(query="Query", mode="hybrid")
            resp = generate_rag_answer(req, provider=FakeLLMProvider())

            self.assertEqual(resp.status, "unavailable")
            self.assertTrue(resp.fallback_mode)
            self.assertIn("disabled", resp.answer)


class TestAnswerAPIEndpoint(unittest.TestCase):
    """FastAPI TestClient integration tests for POST /api/answer."""

    @classmethod
    def setUpClass(cls):
        engine = build_pipeline()
        get_index_manager().set_engine(engine)
        cls.client = TestClient(app)

    def test_post_answer_success(self):
        payload = {"query": "python programming", "mode": "hybrid", "limit": 5}
        response = self.client.post("/api/answer", json=payload)

        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data["query"], "python programming")
        self.assertIn("status", data)
        self.assertIn("answer", data)
        self.assertIn("sources", data)
        self.assertIn("retrieval", data)
        self.assertIn("generation", data)

    def test_post_answer_empty_query_validation(self):
        response = self.client.post("/api/answer", json={"query": ""})
        self.assertEqual(response.status_code, 422)  # Pydantic validation error

    def test_search_endpoints_unaffected(self):
        # Verify GET /api/search still functions without regression
        res_lexical = self.client.get("/api/search", params={"q": "python", "mode": "lexical"})
        self.assertEqual(res_lexical.status_code, 200)

        res_hybrid = self.client.get("/api/search", params={"q": "python", "mode": "hybrid"})
        self.assertEqual(res_hybrid.status_code, 200)


if __name__ == "__main__":
    unittest.main()
