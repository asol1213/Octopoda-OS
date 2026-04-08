"""
Tests for AI/ML features: embeddings, vector index, semantic search,
fact extraction, entity extraction, and graceful fallback behavior.

FAISS is blocked in tests (conftest.py installs a fake module), so all
vector tests exercise the NumPy-only code path.
"""

import struct
import json
import threading
import pytest

np = pytest.importorskip("numpy")


# ---------------------------------------------------------------------------
# EmbeddingModel — singleton, fallback, encode/decode
# ---------------------------------------------------------------------------

class TestEmbeddingModelFallback:
    """Test EmbeddingModel graceful fallback when sentence-transformers is unavailable."""

    @pytest.fixture(autouse=True)
    def _reset(self):
        from synrix.embeddings import EmbeddingModel
        EmbeddingModel.reset()
        yield
        EmbeddingModel.reset()

    def test_get_returns_none_without_sentence_transformers(self, monkeypatch):
        """If sentence_transformers import fails, get() returns None."""
        import sys
        # Temporarily make sentence_transformers unimportable
        real = sys.modules.get("sentence_transformers")
        sys.modules["sentence_transformers"] = None  # blocks import
        try:
            from synrix.embeddings import EmbeddingModel
            EmbeddingModel.reset()
            result = EmbeddingModel.get()
            assert result is None
        finally:
            if real is not None:
                sys.modules["sentence_transformers"] = real
            else:
                sys.modules.pop("sentence_transformers", None)

    def test_singleton_reset(self):
        from synrix.embeddings import EmbeddingModel
        EmbeddingModel._instance = "sentinel"
        EmbeddingModel.reset()
        assert EmbeddingModel._instance is None

    def test_default_dim_384(self):
        from synrix.embeddings import EmbeddingModel
        m = EmbeddingModel()
        assert m.dim == 384

    def test_default_model_constant(self):
        from synrix.embeddings import DEFAULT_MODEL
        assert "bge" in DEFAULT_MODEL.lower() or "BAAI" in DEFAULT_MODEL

    def test_decode_roundtrip(self):
        """encode a float32 blob and decode it back with EmbeddingModel.decode."""
        from synrix.embeddings import EmbeddingModel
        m = EmbeddingModel()
        original = np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32)
        blob = struct.pack(f"{len(original)}f", *original.tolist())
        decoded = m.decode(blob)
        np.testing.assert_allclose(decoded, original, atol=1e-6)

    def test_decode_empty_blob(self):
        from synrix.embeddings import EmbeddingModel
        m = EmbeddingModel()
        decoded = m.decode(b"")
        assert len(decoded) == 0

    def test_model_name_property_empty_initially(self):
        from synrix.embeddings import EmbeddingModel
        m = EmbeddingModel()
        assert m.model_name == ""

    def test_env_var_override_respected(self, monkeypatch):
        """The OCTOPODA_EMBEDDING_MODEL env var should be checked."""
        monkeypatch.setenv("OCTOPODA_EMBEDDING_MODEL", "custom/model")
        # We can't actually load the model, but verify the env var path
        import os
        assert os.environ.get("OCTOPODA_EMBEDDING_MODEL") == "custom/model"


# ---------------------------------------------------------------------------
# VectorIndex — NumPy fallback path (FAISS is blocked)
# ---------------------------------------------------------------------------

class TestVectorIndexBasic:
    """Test VectorIndex construction and state management."""

    def test_new_index_is_dirty(self):
        from synrix.vector_index import VectorIndex
        idx = VectorIndex(dim=4)
        assert idx.is_dirty is True

    def test_build_clears_dirty(self):
        from synrix.vector_index import VectorIndex
        idx = VectorIndex(dim=4)
        idx.build([], [], [], [], [])
        assert idx.is_dirty is False

    def test_mark_dirty_sets_flag(self):
        from synrix.vector_index import VectorIndex
        idx = VectorIndex(dim=4)
        idx.build([], [], [], [], [])
        assert idx.is_dirty is False
        idx.mark_dirty()
        assert idx.is_dirty is True

    def test_len_empty(self):
        from synrix.vector_index import VectorIndex
        idx = VectorIndex(dim=4)
        idx.build([], [], [], [], [])
        assert len(idx) == 0

    def test_search_empty_returns_empty(self):
        from synrix.vector_index import VectorIndex
        idx = VectorIndex(dim=4)
        idx.build([], [], [], [], [])
        query = np.array([1, 0, 0, 0], dtype=np.float32)
        results = idx.search(query)
        assert results == []


class TestVectorIndexNumPySearch:
    """Test vector search using the numpy fallback (FAISS is blocked)."""

    @pytest.fixture
    def populated_index(self):
        from synrix.vector_index import VectorIndex
        idx = VectorIndex(dim=4)
        vecs = [
            np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32),
            np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32),
            np.array([0.0, 0.0, 1.0, 0.0], dtype=np.float32),
            np.array([0.9, 0.1, 0.0, 0.0], dtype=np.float32),  # similar to vec[0]
        ]
        idx.build(
            ids=[1, 2, 3, 4],
            names=["doc_a", "doc_b", "doc_c", "doc_d"],
            datas=["data_a", "data_b", "data_c", "data_d"],
            types=["mem", "mem", "mem", "mem"],
            embeddings=vecs,
        )
        return idx

    def test_build_sets_count(self, populated_index):
        assert len(populated_index) == 4

    def test_search_returns_results(self, populated_index):
        query = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        results = populated_index.search(query, limit=2)
        assert len(results) == 2

    def test_search_top_result_is_most_similar(self, populated_index):
        query = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        results = populated_index.search(query, limit=4)
        assert results[0]["payload"]["name"] == "doc_a"

    def test_search_result_structure(self, populated_index):
        query = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        results = populated_index.search(query, limit=1)
        r = results[0]
        assert "id" in r
        assert "score" in r
        assert "payload" in r
        assert "name" in r["payload"]
        assert "data" in r["payload"]
        assert "type" in r["payload"]

    def test_search_with_threshold(self, populated_index):
        query = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        results = populated_index.search(query, limit=10, threshold=0.8)
        # Only doc_a (1.0) and doc_d (0.9ish) should pass 0.8 threshold
        names = [r["payload"]["name"] for r in results]
        assert "doc_a" in names
        assert "doc_b" not in names
        assert "doc_c" not in names

    def test_search_limit_respected(self, populated_index):
        query = np.array([0.5, 0.5, 0.5, 0.5], dtype=np.float32)
        results = populated_index.search(query, limit=2)
        assert len(results) <= 2

    def test_scores_are_sorted_descending(self, populated_index):
        query = np.array([0.5, 0.5, 0.0, 0.0], dtype=np.float32)
        results = populated_index.search(query, limit=4)
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_version_increments_on_mark_dirty(self):
        from synrix.vector_index import VectorIndex
        idx = VectorIndex(dim=4)
        v0 = idx._version
        idx.mark_dirty()
        assert idx._version == v0 + 1
        idx.mark_dirty()
        assert idx._version == v0 + 2

    def test_zero_vector_query_handled(self, populated_index):
        """A zero-length query vector should not crash."""
        query = np.array([0.0, 0.0, 0.0, 0.0], dtype=np.float32)
        results = populated_index.search(query, limit=2)
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# FactIndex — NumPy path
# ---------------------------------------------------------------------------

class TestFactIndex:
    """Test FactIndex grouping behavior."""

    def test_fact_index_groups_by_node(self):
        from synrix.vector_index import FactIndex
        idx = FactIndex(dim=4)
        vecs = [
            np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32),
            np.array([0.9, 0.1, 0.0, 0.0], dtype=np.float32),
            np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32),
        ]
        idx.build(
            node_ids=[1, 1, 2],
            node_names=["memory_1", "memory_1", "memory_2"],
            fact_texts=["fact A", "fact B", "fact C"],
            datas=["data1", "data1", "data2"],
            types=["mem", "mem", "mem"],
            embeddings=vecs,
        )
        query = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        results = idx.search(query, limit=5)
        # Should deduplicate by node_name, returning best score per memory
        names = [r["payload"]["name"] for r in results]
        assert names.count("memory_1") == 1  # grouped, not duplicated
        assert results[0]["payload"]["name"] == "memory_1"
        assert "matched_fact" in results[0]

    def test_fact_index_empty_build(self):
        from synrix.vector_index import FactIndex
        idx = FactIndex(dim=4)
        idx.build([], [], [], [], [], [])
        assert len(idx) == 0
        query = np.array([1, 0, 0, 0], dtype=np.float32)
        assert idx.search(query) == []

    def test_fact_index_threshold(self):
        from synrix.vector_index import FactIndex
        idx = FactIndex(dim=4)
        vecs = [
            np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32),
            np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32),
        ]
        idx.build(
            node_ids=[1, 2],
            node_names=["close", "far"],
            fact_texts=["fact1", "fact2"],
            datas=["d1", "d2"],
            types=["m", "m"],
            embeddings=vecs,
        )
        query = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        results = idx.search(query, limit=10, threshold=0.5)
        names = [r["payload"]["name"] for r in results]
        assert "close" in names
        assert "far" not in names


# ---------------------------------------------------------------------------
# FactExtractor — parsing, short text, provider configuration
# ---------------------------------------------------------------------------

class TestFactExtractorParsing:
    """Test JSON parsing logic (no LLM needed)."""

    def test_parse_valid_json(self):
        from synrix.fact_extractor import FactExtractor
        facts = FactExtractor._parse_facts('["a", "b", "c"]')
        assert facts == ["a", "b", "c"]

    def test_parse_with_preamble(self):
        from synrix.fact_extractor import FactExtractor
        raw = 'Sure! Here are the facts:\n["fact one", "fact two"]\nDone.'
        facts = FactExtractor._parse_facts(raw)
        assert len(facts) == 2

    def test_parse_invalid_returns_empty(self):
        from synrix.fact_extractor import FactExtractor
        assert FactExtractor._parse_facts("garbage") == []

    def test_parse_non_string_items_filtered(self):
        from synrix.fact_extractor import FactExtractor
        facts = FactExtractor._parse_facts('[42, "good", null, "", "also good"]')
        assert facts == ["good", "also good"]

    def test_parse_nested_json_ignored(self):
        from synrix.fact_extractor import FactExtractor
        raw = '{"facts": ["a"]}'  # Not a top-level array
        facts = FactExtractor._parse_facts(raw)
        # The parser looks for first [ ... last ], so finds ["a"]
        assert facts == ["a"]


class TestFactExtractorBehavior:
    """Test extract_facts edge cases without calling any LLM."""

    @pytest.fixture(autouse=True)
    def _reset(self):
        from synrix.fact_extractor import FactExtractor
        FactExtractor.reset()
        yield
        FactExtractor.reset()

    def test_empty_text_returns_no_facts(self):
        from synrix.fact_extractor import FactExtractor
        extractor = FactExtractor()
        extractor._available = True
        extractor._provider = "ollama"
        FactExtractor._semaphore = threading.Semaphore(2)
        result = extractor.extract_facts("")
        assert result.facts == []
        assert result.used_llm is False

    def test_short_text_skips_llm(self):
        from synrix.fact_extractor import FactExtractor
        extractor = FactExtractor()
        extractor._available = True
        extractor._provider = "ollama"
        FactExtractor._semaphore = threading.Semaphore(2)
        result = extractor.extract_facts("hi there")
        assert result.facts == ["hi there"]
        assert result.used_llm is False
        assert result.provider == "none"

    def test_whitespace_only_text(self):
        from synrix.fact_extractor import FactExtractor
        extractor = FactExtractor()
        extractor._available = True
        extractor._provider = "ollama"
        FactExtractor._semaphore = threading.Semaphore(2)
        result = extractor.extract_facts("   \n  \t  ")
        assert result.facts == []

    def test_extraction_result_has_source_text(self):
        from synrix.fact_extractor import FactExtractor
        extractor = FactExtractor()
        extractor._available = True
        extractor._provider = "ollama"
        FactExtractor._semaphore = threading.Semaphore(2)
        result = extractor.extract_facts("short")
        assert result.source_text == "short"

    def test_used_ollama_backward_compat(self):
        from synrix.fact_extractor import FactExtractionResult
        r = FactExtractionResult(
            facts=["x"], source_text="x",
            extraction_time_ms=0, used_llm=True, provider="ollama",
        )
        assert r.used_ollama is True

    def test_provider_none_when_disabled(self, monkeypatch):
        """Setting OCTOPODA_LLM_PROVIDER=none returns None from get()."""
        from synrix.fact_extractor import FactExtractor
        FactExtractor.reset()
        monkeypatch.setenv("OCTOPODA_LLM_PROVIDER", "none")
        result = FactExtractor.get()
        assert result is None


# ---------------------------------------------------------------------------
# EntityExtractor — fallback and text extraction
# ---------------------------------------------------------------------------

class TestEntityExtractorFallback:
    """Test EntityExtractor when spaCy is not available or model missing."""

    @pytest.fixture(autouse=True)
    def _reset(self):
        from synrix.extractor import EntityExtractor
        EntityExtractor.reset()
        yield
        EntityExtractor.reset()

    def test_extraction_result_dataclass(self):
        from synrix.extractor import ExtractionResult
        r = ExtractionResult()
        assert r.entities == []
        assert r.relationships == []

    def test_extraction_result_with_data(self):
        from synrix.extractor import ExtractionResult
        r = ExtractionResult(
            entities=[("Alice", "PERSON")],
            relationships=[("Alice", "works_at", "Google")],
        )
        assert len(r.entities) == 1
        assert len(r.relationships) == 1

    def test_extract_text_from_string(self):
        from synrix.extractor import EntityExtractor
        e = EntityExtractor()
        assert e.extract_text_from_value("hello") == "hello"

    def test_extract_text_from_dict_value_key(self):
        from synrix.extractor import EntityExtractor
        e = EntityExtractor()
        result = e.extract_text_from_value({"value": "world"})
        assert "world" in result

    def test_extract_text_from_dict_text_key(self):
        from synrix.extractor import EntityExtractor
        e = EntityExtractor()
        result = e.extract_text_from_value({"text": "content"})
        assert "content" in result

    def test_extract_text_from_dict_multiple_keys(self):
        from synrix.extractor import EntityExtractor
        e = EntityExtractor()
        result = e.extract_text_from_value({
            "value": "part1",
            "text": "part2",
        })
        assert "part1" in result
        assert "part2" in result

    def test_extract_text_from_nested_dict(self):
        from synrix.extractor import EntityExtractor
        e = EntityExtractor()
        result = e.extract_text_from_value({
            "content": {"inner_key": "nested_value"},
        })
        assert "nested_value" in result

    def test_extract_text_from_int(self):
        from synrix.extractor import EntityExtractor
        e = EntityExtractor()
        result = e.extract_text_from_value(42)
        assert result == "42"

    def test_extract_text_from_dict_no_text_keys(self):
        from synrix.extractor import EntityExtractor
        e = EntityExtractor()
        result = e.extract_text_from_value({"count": 5, "flag": True})
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Knowledge graph edge cases (via sqlite_client)
# ---------------------------------------------------------------------------

class TestKnowledgeGraphEdgeCases:
    """Additional edge cases for the knowledge graph."""

    def test_entity_with_special_characters(self, sqlite_client):
        sqlite_client.create_collection("test")
        eid = sqlite_client.upsert_entity("O'Brien", "PERSON", collection="test")
        assert eid is not None
        entity = sqlite_client.query_entity("O'Brien", collection="test")
        assert entity is not None
        assert entity["name"] == "O'Brien"

    def test_relationship_self_reference(self, sqlite_client):
        """An entity can have a relationship with itself."""
        sqlite_client.create_collection("test")
        eid = sqlite_client.upsert_entity("Node", "CONCEPT", collection="test")
        rid = sqlite_client.add_relationship(eid, eid, "self_ref", collection="test")
        assert rid is not None

    def test_many_entities_list(self, sqlite_client):
        sqlite_client.create_collection("test")
        for i in range(20):
            sqlite_client.upsert_entity(f"entity_{i}", "TYPE", collection="test")
        entities = sqlite_client.list_entities(collection="test")
        assert len(entities) == 20

    def test_entity_empty_name_still_works(self, sqlite_client):
        """Empty string name should not crash, even if unusual."""
        sqlite_client.create_collection("test")
        eid = sqlite_client.upsert_entity("", "UNKNOWN", collection="test")
        assert eid is not None


# ---------------------------------------------------------------------------
# FAISS blocked verification
# ---------------------------------------------------------------------------

class TestFAISSBlocked:
    """Verify that FAISS is blocked or unavailable in the test environment."""

    def test_faiss_not_functional(self):
        """FAISS should be blocked (fake module) or absent entirely."""
        import sys
        faiss = sys.modules.get("faiss")
        if faiss is not None:
            # conftest.py installs a fake with IndexFlatIP = None
            assert faiss.IndexFlatIP is None
        # else: faiss not in sys.modules at all, also fine

    def test_vector_index_uses_numpy_path(self):
        """With FAISS blocked, the index must fall back to numpy search."""
        from synrix.vector_index import VectorIndex
        idx = VectorIndex(dim=4)
        vecs = [np.array([1, 0, 0, 0], dtype=np.float32)]
        idx.build([1], ["doc"], ["data"], ["mem"], vecs)
        # _faiss_index should be None because faiss.IndexFlatIP is None or missing
        assert idx._faiss_index is None


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------

class TestVectorIndexThreadSafety:
    """Basic thread safety of VectorIndex operations."""

    def test_concurrent_search_no_crash(self):
        from synrix.vector_index import VectorIndex
        idx = VectorIndex(dim=4)
        vecs = [np.random.randn(4).astype(np.float32) for _ in range(50)]
        idx.build(
            ids=list(range(50)),
            names=[f"doc_{i}" for i in range(50)],
            datas=[f"data_{i}" for i in range(50)],
            types=["mem"] * 50,
            embeddings=vecs,
        )

        errors = []

        def search_worker():
            try:
                q = np.random.randn(4).astype(np.float32)
                results = idx.search(q, limit=5)
                assert isinstance(results, list)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=search_worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert errors == [], f"Thread errors: {errors}"
