from __future__ import annotations

from types import SimpleNamespace

import pytest

from pokemon_rag.client.mcp_client import ConstraintResolutionError, reconcile_tool_call
from pokemon_rag.constraints.query_constraints import extract_explicit_constraints


def tool(name: str, *properties: str):
    return SimpleNamespace(
        name=name,
        input_schema={
            "type": "object",
            "properties": {key: {} for key in properties},
        },
    )


LEVEL_TOOL = tool(
    "pokemon_level_up_moves",
    "pokemon",
    "form",
    "version_group",
    "min_level",
    "max_level",
)
TYPES_TOOL = tool("pokemon_types", "pokemon", "form")


def test_restores_game_and_max_level_before_execution() -> None:
    name, arguments = reconcile_tool_call(
        "Quelles capacités Pikachu apprend-il jusqu'au niveau 30 dans Pokémon Rouge ?",
        "pokemon_level_up_moves",
        {"pokemon": "Pikachu", "min_level": None, "max_level": None},
        [LEVEL_TOOL],
    )

    assert name == "pokemon_level_up_moves"
    assert arguments == {
        "pokemon": "Pikachu",
        "min_level": None,
        "max_level": 30,
        "version_group": "red-blue",
    }


def test_switches_to_level_tool_instead_of_dropping_level_constraint() -> None:
    name, arguments = reconcile_tool_call(
        "Quelles capacités Pikachu apprend-il jusqu'au niveau 30 ?",
        "pokemon_types",
        {"pokemon": "Pikachu"},
        [TYPES_TOOL, LEVEL_TOOL],
    )

    assert name == "pokemon_level_up_moves"
    assert arguments["pokemon"] == "Pikachu"
    assert arguments["max_level"] == 30


def test_restores_explicit_form() -> None:
    name, arguments = reconcile_tool_call(
        "Quels sont les types de Noadkoko d'Alola ?",
        "pokemon_types",
        {"pokemon": "Noadkoko", "form": None},
        [TYPES_TOOL],
    )

    assert name == "pokemon_types"
    assert arguments["form"] == "alola"


def test_blocks_unresolved_game_before_execution() -> None:
    with pytest.raises(ConstraintResolutionError, match="jeu demandé"):
        reconcile_tool_call(
            "Quelles capacités Pikachu apprend-il dans Pokémon version inconnue ?",
            "pokemon_level_up_moves",
            {"pokemon": "Pikachu"},
            [LEVEL_TOOL],
        )


def test_blocks_tool_that_cannot_honor_explicit_game() -> None:
    with pytest.raises(ConstraintResolutionError, match="pas filtrable"):
        reconcile_tool_call(
            "Quels sont les types de Pikachu dans Pokémon Rouge ?",
            "pokemon_types",
            {"pokemon": "Pikachu"},
            [TYPES_TOOL],
        )


def test_blocks_missing_pokemon_instead_of_simplifying_request() -> None:
    with pytest.raises(ConstraintResolutionError, match="Pokémon"):
        reconcile_tool_call(
            "Quelles capacités Pikachu apprend-il jusqu'au niveau 30 ?",
            "pokemon_level_up_moves",
            {"max_level": 30},
            [LEVEL_TOOL],
        )

def test_extract_level_range_between_levels() -> None:
    constraints = extract_explicit_constraints(
        "Quelles capacités Pikachu apprend-il par niveau "
        "entre les niveaux 10 et 20 dans Pokémon Rouge et Bleu ?"
    )

    assert constraints.level_explicit is True
    assert constraints.level_bounds == (10, 20)
    assert constraints.explicit_game is True
    assert constraints.version_ambiguous is False
    assert constraints.version_group == "red-blue"