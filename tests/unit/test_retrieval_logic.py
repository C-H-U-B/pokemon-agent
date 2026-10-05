from __future__ import annotations

from collections import defaultdict
from types import SimpleNamespace

import numpy as np
import pytest
import pokemon_rag.rag.retrieval as retrieval

# Conserver la fonction avant la protection autouse ; ses dépendances lourdes
# sont toutes remplacées dans le test d'initialisation ci-dessous.
initialize_retrieval = retrieval.initialize_retrieval


def test_initialization_keeps_stdout_free_for_mcp(monkeypatch, capsys):
    collection = SimpleNamespace(
        count=lambda: 1,
        get=lambda **kwargs: {
            "ids": ["pika-1"],
            "documents": ["Pikachu est un Pokémon."],
            "metadatas": [{"pokemon": "Pikachu", "source_file": "Pikachu.md",
                           "section_path": "Description", "section_chunk_number": 0}],
        },
    )
    monkeypatch.setattr(retrieval.chromadb, "PersistentClient", lambda **kwargs: SimpleNamespace(
        get_collection=lambda name: collection
    ))
    monkeypatch.setattr(retrieval, "SentenceTransformer", lambda name: SimpleNamespace(device="cpu"))
    monkeypatch.setattr(retrieval, "CrossEncoder", lambda name: SimpleNamespace(device="cpu"))
    monkeypatch.setattr(retrieval, "_RETRIEVAL_INITIALIZED", False)
    for name in ("client", "collection", "embedding_model", "reranker_model", "bm25"):
        monkeypatch.setattr(retrieval, name, None)
    for name in ("CORPUS_IDS", "CORPUS_DOCUMENTS", "CORPUS_METADATAS"):
        monkeypatch.setattr(retrieval, name, [])
    for name in ("POKEMON_TO_INDICES", "SECTION_TO_INDICES"):
        monkeypatch.setattr(retrieval, name, defaultdict(list))

    initialize_retrieval()

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "INITIALISATION RAG" in captured.err
    assert "Chargement corpus" in captured.err
    assert "Construction BM25" in captured.err
    assert "Startup total" in captured.err
    assert retrieval._RETRIEVAL_INITIALIZED
    assert retrieval.CORPUS_IDS == ["pika-1"]

    initialize_retrieval()
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


@pytest.fixture(autouse=True)
def synthetic_retrieval(monkeypatch):
    monkeypatch.setattr(retrieval, '_RETRIEVAL_INITIALIZED', True)


def test_tokenize_normalizes_case_and_preserves_accents() -> None:
    assert retrieval.tokenize("ÉLECTACLE, Pikachu !") == ["électacle", "pikachu"]


def test_normalize_section_tokens_removes_stopwords() -> None:
    tokens = retrieval.normalize_section_tokens(
        "Quelles sont les capacités de Pikachu dans cette section ?"
    )

    assert "capacités" in tokens
    assert "pikachu" in tokens
    assert "les" not in tokens
    assert "de" not in tokens


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ({"section_path": "Capacités > Par niveau"}, "Capacités > Par niveau"),
        ({"section": "Statistiques"}, "Statistiques"),
        ({"section_path": "", "section": "Évolution"}, "Évolution"),
        ({}, ""),
        (None, ""),
    ],
    ids=[
        "section-path",
        "legacy-section",
        "empty-path-fallback",
        "empty-metadata",
        "none-metadata",
    ],
)
def test_metadata_section_path(metadata, expected: str) -> None:
    assert retrieval.metadata_section_path(metadata) == expected


def test_reciprocal_rank_fusion_merges_and_deduplicates() -> None:
    vector_results = [
        {
            "id": "a",
            "document": "A",
            "metadata": {"pokemon": "Pikachu"},
            "vector_rank": 1,
            "vector_distance": 0.1,
        },
        {
            "id": "b",
            "document": "B",
            "metadata": {"pokemon": "Pikachu"},
            "vector_rank": 2,
            "vector_distance": 0.2,
        },
    ]
    bm25_results = [
        {
            "id": "b",
            "document": "B",
            "metadata": {"pokemon": "Pikachu"},
            "bm25_rank": 1,
            "bm25_score": 8.0,
        },
        {
            "id": "c",
            "document": "C",
            "metadata": {"pokemon": "Pikachu"},
            "bm25_rank": 2,
            "bm25_score": 7.0,
        },
    ]

    results = retrieval.reciprocal_rank_fusion(
        vector_results,
        bm25_results,
        n_results=3,
    )

    assert [item["id"] for item in results] == ["b", "a", "c"]
    assert len({item["id"] for item in results}) == 3
    assert results[0]["vector_rank"] == 2
    assert results[0]["bm25_rank"] == 1
    assert results[0]["rrf_rank"] == 1


def test_merge_candidates_keeps_rrf_order_and_adds_unique_sections() -> None:
    rrf = [
        {"id": "a", "document": "A", "metadata": {}, "rrf_rank": 1},
        {"id": "b", "document": "B", "metadata": {}, "rrf_rank": 2},
    ]
    sections = [
        {
            "id": "b",
            "document": "B",
            "metadata": {},
            "section_path": "Évolution",
            "section_structural_score": 4.2,
        },
        {
            "id": "c",
            "document": "C",
            "metadata": {},
            "section_path": "Capacités",
            "section_structural_score": 3.0,
        },
    ]

    results = retrieval.merge_candidates(rrf, sections)

    assert [item["id"] for item in results] == ["a", "b", "c"]
    assert results[1]["section_path"] == "Évolution"
    assert results[1]["section_structural_score"] == 4.2


def test_section_key_requires_source_and_section() -> None:
    assert retrieval.section_key(
        {
            "metadata": {
                "source_file": "Pikachu.md",
                "section_path": "Évolution",
            }
        }
    ) == ("Pikachu.md", "Évolution")

    assert retrieval.section_key({"metadata": {"source_file": "Pikachu.md"}}) is None
    assert retrieval.section_key({"metadata": {"section_path": "Évolution"}}) is None


def test_section_structural_candidates_requires_pokemon() -> None:
    assert retrieval.section_structural_candidates("Évolution", None) == []


def test_section_structural_candidates_stays_inside_scope(monkeypatch) -> None:
    monkeypatch.setattr(
        retrieval,
        "CORPUS_IDS",
        ["pika-1", "pika-2", "rai-1"],
    )
    monkeypatch.setattr(
        retrieval,
        "CORPUS_DOCUMENTS",
        ["P1", "P2", "R1"],
    )
    monkeypatch.setattr(
        retrieval,
        "CORPUS_METADATAS",
        [
            {
                "pokemon": "Pikachu",
                "source_file": "Pikachu.md",
                "section_path": "Capacités > Capacités apprises",
                "chunk_number": 1,
            },
            {
                "pokemon": "Pikachu",
                "source_file": "Pikachu.md",
                "section_path": "Évolution",
                "chunk_number": 2,
            },
            {
                "pokemon": "Raichu",
                "source_file": "Raichu.md",
                "section_path": "Capacités > Capacités apprises",
                "chunk_number": 1,
            },
        ],
    )
    monkeypatch.setattr(
        retrieval,
        "POKEMON_TO_INDICES",
        {"Pikachu": [0, 1], "Raichu": [2]},
    )

    results = retrieval.section_structural_candidates(
        "Quelles capacités Pikachu peut-il apprendre ?",
        pokemon="Pikachu",
    )

    assert results
    assert all(item["metadata"]["pokemon"] == "Pikachu" for item in results)
    assert all(item["id"] != "rai-1" for item in results)


def test_expand_exact_section_uses_section_chunk_order_and_limit(monkeypatch) -> None:
    monkeypatch.setattr(retrieval, "CORPUS_IDS", ["a", "b", "c", "d"])
    monkeypatch.setattr(retrieval, "CORPUS_DOCUMENTS", ["A", "B", "C", "D"])
    monkeypatch.setattr(
        retrieval,
        "CORPUS_METADATAS",
        [
            {
                "source_file": "Pikachu.md",
                "section_path": "Évolution",
                "section_chunk_number": 1,
            },
            {
                "source_file": "Pikachu.md",
                "section_path": "Évolution",
                "section_chunk_number": 2,
            },
            {
                "source_file": "Pikachu.md",
                "section_path": "Évolution",
                "section_chunk_number": 3,
            },
            {
                "source_file": "Pikachu.md",
                "section_path": "Autre",
                "section_chunk_number": 1,
            },
        ],
    )
    monkeypatch.setattr(
        retrieval,
        "SECTION_TO_INDICES",
        {("Pikachu.md", "Évolution"): [0, 1, 2]},
    )

    seed = {
        "id": "b",
        "document": "B",
        "metadata": retrieval.CORPUS_METADATAS[1],
        "reranker_rank": 1,
    }

    results = retrieval.expand_exact_section(seed, max_chunks=2)

    assert [item["id"] for item in results] == ["a", "b"]
    assert all(item["section"] == "Évolution" for item in results)
    assert results[0]["is_section_expansion"] is True
    assert results[1]["is_section_expansion"] is False


def test_rerank_candidates_orders_crossencoder_scores(monkeypatch) -> None:
    class FakeReranker:
        def predict(self, pairs, **kwargs):
            assert len(pairs) == 3
            return np.asarray([0.2, 0.9, -0.1])

    monkeypatch.setattr(retrieval, "reranker_model", FakeReranker())

    candidates = [
        {"id": "a", "document": "A", "metadata": {"section_path": "A"}},
        {"id": "b", "document": "B", "metadata": {"section_path": "B"}},
        {"id": "c", "document": "C", "metadata": {"section_path": "C"}},
    ]

    results, _ = retrieval.rerank_candidates(
        "question",
        candidates,
        n_results=2,
    )

    assert [item["id"] for item in results] == ["b", "a"]
    assert [item["reranker_rank"] for item in results] == [1, 2]
    assert results[0]["reranker_score"] == pytest.approx(0.9)


@pytest.mark.parametrize("asked, indexed", [
    ("reshiram", "Reshiram"), ("RESHIRAM", "Reshiram"), ("Reshiram", "Reshiram"),
    ("mimiqui", "Mimiqui"), ("evoli", "Évoli"), ("m. mime", "M. Mime"),
    ("Reshi", "Reshi"),          # sous-chaîne : jamais rapprochée d'un nom indexé
    ("Fauxkémon", "Fauxkémon"),  # inconnu : inchangé, donc recherche vide et non globale
    (None, None), ("", None),
])
def test_scope_name_matches_the_indexed_name_after_normalization(monkeypatch, asked, indexed):
    # Régression : « reshiram » en minuscules ne trouvait aucun fragment de « Reshiram ».
    monkeypatch.setattr(retrieval, "POKEMON_TO_INDICES", {"Reshiram": [0], "Mimiqui": [1], "Évoli": [2], "M. Mime": [3]})
    assert retrieval.canonical_pokemon(asked) == indexed


def test_retrieve_scopes_every_stage_with_the_indexed_name(monkeypatch):
    monkeypatch.setattr(retrieval, "POKEMON_TO_INDICES", {"Reshiram": [0]})
    scopes = []
    for stage in ("vector_retrieve", "bm25_retrieve", "section_structural_candidates"):
        monkeypatch.setattr(retrieval, stage, lambda question, pokemon=None, _stage=stage: scopes.append((_stage, pokemon)) or [])
    monkeypatch.setattr(retrieval, "expand_best_section", lambda *args, **kwargs: ([], {}))
    assert retrieval.retrieve("à quoi ressemble reshiram ?", pokemon="reshiram") == []
    assert scopes == [("vector_retrieve", "Reshiram"), ("bm25_retrieve", "Reshiram"),
                      ("section_structural_candidates", "Reshiram")]


def test_search_tool_reports_search_steps_and_loading_only_on_the_first_call(monkeypatch):
    from pokemon_rag.mcp import server
    steps = {"vector": 0.05, "bm25": 0.02, "rrf": 0.001, "reranker": 1.1, "total": 1.2}
    passage = {"document": "Mimiqui porte un chiffon.", "metadata": {"pokemon": "Mimiqui"}, "timings": steps}
    startup = {"embedding": 18.2, "reranker": 17.5, "corpus": 17.7, "bm25": 0.8, "total": 54.3}

    def cold_retrieve(**kwargs):
        # Le premier appel charge la base pendant la recherche.
        monkeypatch.setattr(retrieval, "_RETRIEVAL_INITIALIZED", True)
        monkeypatch.setattr(retrieval, "STARTUP_TIMINGS", startup)
        return [dict(passage)]

    monkeypatch.setattr(retrieval, "_RETRIEVAL_INITIALIZED", False)
    monkeypatch.setattr(retrieval, "retrieve", cold_retrieve)
    first = server.pokemon_rag_search("À quoi ressemble Mimiqui ?", "Mimiqui")
    assert first["timings"] == {**steps, "startup": startup}
    assert first["results"][0]["text"] == "Mimiqui porte un chiffon."

    monkeypatch.setattr(retrieval, "retrieve", lambda **kwargs: [dict(passage)])
    assert server.pokemon_rag_search("À quoi ressemble Mimiqui ?", "Mimiqui")["timings"] == steps

    # Recherche vide : pas d'étapes détaillées, mais une durée totale mesurée et aucun chargement.
    monkeypatch.setattr(retrieval, "retrieve", lambda **kwargs: [])
    empty = server.pokemon_rag_search("à quoi ressemble reshiram ?", "Fauxkémon")
    assert empty["results"] == [] and set(empty["timings"]) == {"total"} and empty["timings"]["total"] >= 0


def test_concurrent_first_uses_initialize_the_retrieval_once(monkeypatch):
    # Le préchargement et une première question peuvent demander la base au même moment.
    import threading
    import time

    started = []

    def slow_initialization():
        started.append(threading.current_thread().name)
        time.sleep(0.05)
        monkeypatch.setattr(retrieval, "_RETRIEVAL_INITIALIZED", True)

    monkeypatch.setattr(retrieval, "_RETRIEVAL_INITIALIZED", False)
    monkeypatch.setattr(retrieval, "initialize_retrieval", slow_initialization)
    threads = [threading.Thread(target=retrieval.ensure_retrieval_initialized) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert len(started) == 1 and retrieval._RETRIEVAL_INITIALIZED


def test_server_preload_loads_the_retrieval_in_the_background(monkeypatch):
    from pokemon_rag.mcp import server

    loaded = []
    monkeypatch.setattr(retrieval, "ensure_retrieval_initialized", lambda: loaded.append(True))
    thread = server.start_preload()
    thread.join(timeout=5)
    assert loaded == [True] and thread.daemon


def test_agent_does_not_preload_the_retrieval_unless_asked():
    # Hors conteneur Web et dans les tests, lancer le serveur MCP ne doit charger aucun modèle.
    from pokemon_rag.agent.agent import pokemon_mcp
    assert "--preload" not in pokemon_mcp.connection_params.server_params.args
