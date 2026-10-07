from __future__ import annotations

import pytest

import pokemon_rag.rag.retrieval as retrieval


pytestmark = [pytest.mark.long, pytest.mark.real_data, pytest.mark.models]


# La section attendue est rare parmi les passages du Pokémon (2 sur 89 pour Pikachu, 2 sur 51
# pour Bulbizarre) : trois passages pris au hasard la contiendraient moins d'une fois sur huit.
# Un mot courant comme « capacité », présent dans près d'un passage sur deux, ne mesurait rien.
CASES = [
    {
        "question": "Comment Pikachu évolue-t-il ?",
        "pokemon": "Pikachu",
        "expected_section": "Évolution",
    },
    {
        "question": "Quelles capacités Bulbizarre apprend-il par montée en niveau ?",
        "pokemon": "Bulbizarre",
        "expected_section": "Par montée en niveau",
    },
]


@pytest.mark.parametrize(
    "case",
    CASES,
    ids=["pikachu-evolution", "bulbizarre-level-up-moves"],
)
def test_retrieval_quality_cases(case: dict) -> None:
    retrieval.ensure_retrieval_initialized()

    pokemon = case["pokemon"]
    if pokemon not in retrieval.POKEMON_TO_INDICES:
        pytest.skip(f"{pokemon} absent de l'index réel")

    results = retrieval.retrieve(
        case["question"],
        n_results=5,
        rerank=True,
        pokemon=pokemon,
    )

    assert results
    assert all(
        (item.get("metadata") or {}).get("pokemon") == pokemon
        for item in results
    )

    top_sections = [retrieval.metadata_section_path(item.get("metadata")) for item in results[:3]]
    assert any(case["expected_section"] in section for section in top_sections), top_sections
