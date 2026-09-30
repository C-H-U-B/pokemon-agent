import pytest
from unittest.mock import patch
from pokemon_rag.structured.query_engine import get_pokemon_types, get_pokedex_identity, get_signature_moves
from pokemon_rag.graph.graph import run_graph
from pokemon_rag.graph import nodes

pytestmark = pytest.mark.real_data


def test_real_pokedex_fields():
    assert get_pokemon_types("Charizard")["rows"][0]["type_2_fr"] == "Vol"
    assert get_pokemon_types("Alolan Exeggutor")["rows"][0]["type_2_fr"] == "Dragon"
    assert get_pokedex_identity("Pikachu")["rows"][0]["national_number"] == 25
    assert get_signature_moves("Pikachu")["rows"][0]["signature_move_fr"] == "Électacle"


def test_new_benchmark_references_match_database():
    import json
    import runpy
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    references = json.loads((root / "benchmarks/data/answer_references.json").read_text(encoding="utf-8"))
    matches = runpy.run_path(str(root / "benchmarks/review_answers.py"))["matches_reference"]
    for case_id, result in [("S05", get_pokemon_types("Dracaufeu")),
                            ("S06", get_pokedex_identity("Pikachu")),
                            ("S07", get_signature_moves("Pikachu"))]:
        assert matches(result, references[case_id]["structured"])


@pytest.mark.parametrize("question, expected", [
    ("Quels sont les types de Dracaufeu ?", "Vol"),
    ("Quel est le numéro national de Pikachu ?", "25"),
    ("Quelle est la capacité signature de Pikachu ?", "Électacle"),
    ("Quels sont les types de Noadkoko d'Alola ?", "Dragon"),
])
def test_real_structured_graph_avoids_generation(question, expected):
    with patch("pokemon_rag.graph.graph.save_trace"), patch.object(nodes.llm_client.chat.completions, "create") as generation:
        result = run_graph({"question": question})
    assert result["execution_status"] == "COMPLETED"
    assert result["grounding_decision"] == "DETERMINISTIC"
    assert expected in result["answer"]
    generation.assert_not_called()
