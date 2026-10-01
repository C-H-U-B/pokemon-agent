"""Real MCP E2E: local data, retrieval models and Qwen are required.

Execution belongs to the user. Passing these scenarios does not establish
factual correctness of generated answers; review the recorded results.
"""
from __future__ import annotations

import asyncio
import json
from functools import partial

import pytest

from pokemon_rag.client import mcp_client as client


QUESTION = "Quels sont les types de Pikachu ?"


LIVE_CASES = [
    ("Quelles sont les évolutions de Pikachu ?", "pokemon_evolutions", {"pokemon": "pikachu"}),
    ("Quelles capacités Pikachu apprend-il par niveau entre les niveaux 10 et 20 dans Pokémon Rouge et Bleu ?",
     "pokemon_level_up_moves", {"pokemon": "pikachu", "min_level": 10, "max_level": 20, "version_group": "red-blue"}),
    ("Quelles CT ou CS Pikachu peut-il apprendre dans Pokémon Rouge et Bleu ?",
     "pokemon_machine_moves", {"pokemon": "pikachu", "version_group": "red-blue"}),
    ("Par quelles méthodes Pikachu apprend-il Tonnerre dans Pokémon Rouge et Bleu ?",
     "pokemon_move_learning_methods", {"pokemon": "pikachu", "version_group": "red-blue"}),
    (QUESTION, "pokemon_types", {"pokemon": "pikachu"}),
    ("Quels sont le numéro national et la génération d'introduction de Pikachu ?",
     "pokemon_pokedex_identity", {"pokemon": "pikachu"}),
    ("Quelles sont les capacités signature et pseudo-signature de Pikachu ?",
     "pokemon_signature_moves", {"pokemon": "pikachu"}),
    ("Décris le comportement de Pikachu dans la nature.", "pokemon_rag_search", {"pokemon": "pikachu"}),
    ("Comment fonctionne la reproduction des Pokémon ?", "pokemon_rag_search", {}),
    ("Quels sont les types de Noadkoko d'Alola ?", "pokemon_types", {}),
]


@pytest.mark.llm
@pytest.mark.real_data
@pytest.mark.models
@pytest.mark.long
@pytest.mark.parametrize("question, expected_tool, expected_arguments", LIVE_CASES,
                         ids=[f"{case[1]}-{i}" for i, case in enumerate(LIVE_CASES)])
def test_live_question_to_answer(question, expected_tool, expected_arguments, monkeypatch, record_property):
    """Vrai sous-processus MCP, vrais outils et vrai LLM ; aucun résultat simulé."""
    selected = []
    results = []
    original_choose = client.choose_tool
    original_extract = client.extract_result
    original_transport = client.stdio_client
    original_llm_factory = client.create_llm_client

    # Les modèles doivent déjà être en cache : aucun téléchargement pendant le test.
    # Le SDK stdio ne transmet pas toutes les variables du processus parent.
    def local_transport(parameters):
        parameters.env = {**(parameters.env or {}), "HF_HUB_OFFLINE": "1"}
        return original_transport(parameters)

    monkeypatch.setattr(client, "stdio_client", local_transport)
    monkeypatch.setattr(client, "ClientSession", partial(client.ClientSession, read_timeout_seconds=120))
    monkeypatch.setattr(client, "create_llm_client", lambda: original_llm_factory().with_options(
        timeout=90, max_retries=0
    ))

    def observe_choice(*args, **kwargs):
        choice = original_choose(*args, **kwargs)
        selected.append(choice)
        return choice

    def observe_result(result):
        extracted = original_extract(result)
        results.append(extracted)
        return extracted

    monkeypatch.setattr(client, "choose_tool", observe_choice)
    monkeypatch.setattr(client, "extract_result", observe_result)
    try:
        answer = asyncio.run(client.ask(question))
    finally:
        record_property("question", question)
        record_property("selection", json.dumps(selected, ensure_ascii=False))
        record_property("tool_result", json.dumps(results, ensure_ascii=False))
    record_property("answer", answer)
    assert len(selected) == 1
    assert len(results) == 1 and isinstance(results[0], dict)
    assert not results[0].get("error"), results[0]
    tool, arguments = selected[0]
    assert tool == expected_tool
    for key, expected in expected_arguments.items():
        actual = arguments.get(key)
        assert (actual.casefold() if isinstance(actual, str) else actual) == expected
    if expected_tool == "pokemon_move_learning_methods":
        assert arguments.get("move", "").casefold() in {"tonnerre", "thunderbolt"}
    if expected_tool == "pokemon_rag_search":
        assert arguments.get("question", "").strip()
        if not expected_arguments:
            assert arguments.get("pokemon") in (None, "")
        assert results[0]["results"], "La recherche réelle n'a retourné aucun passage"
        assert all(item["text"].strip() and item["source_file"] for item in results[0]["results"])
    else:
        collection = {
            "pokemon_evolutions": "evolutions",
            "pokemon_level_up_moves": "moves",
            "pokemon_machine_moves": "moves",
            "pokemon_move_learning_methods": "methods",
        }.get(expected_tool, "rows")
        rows = results[0][collection]
        assert results[0]["count"] == len(rows)
        assert rows, "Aucune donnée pour ce cas de référence"
    if "Alola" in question:
        assert "alola" in results[0]["pokemon"].casefold()
        row = results[0]["rows"][0]
        assert {row["type_1_fr"], row["type_2_fr"]} == {"Plante", "Dragon"}
    if expected_tool == "pokemon_pokedex_identity":
        assert results[0]["rows"][0]["national_number"] == 25
    assert answer.strip()
