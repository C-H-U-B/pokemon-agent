from types import SimpleNamespace

import pytest

from pokemon_rag.agent.tool_guard import before_tool_guard


@pytest.mark.parametrize("name", ["pokemon_moves", "pokemon_search"])
def test_new_tools_preserve_all_filters_and_explicit_constraints(name):
    args = {"move_type": "Glace", "damage_class": "special", "min_level": 2, "max_level": 99}
    result = before_tool_guard(_tool(name), args, _context(
        "Quelles attaques Feunard d'Alola apprend-il entre les niveaux 10 et 20 dans Pokémon Soleil ?"))
    assert result is None
    assert args == {"move_type": "Glace", "damage_class": "special", "min_level": 10,
                    "max_level": 20, "learning_method": "level-up", "form": "alola",
                    "version_group": "sun-moon"}


def _tool(name: str) -> SimpleNamespace:
    """Crée un faux tool ADK minimal."""
    return SimpleNamespace(name=name)


def test_guard_preserves_stat_ranking_and_mega_category_arguments():
    args = {"types":["Feu"], "generation":1, "legendary":False, "sort_by":"attack",
            "sort_order":"desc", "best_only":True, "form_category":"mega", "limit":5}
    original = dict(args)
    assert before_tool_guard(_tool("pokemon_search"), args, _context(
        "Quels sont les 5 Pokémon Méga Feu avec le plus d'Attaque ?")) is None
    assert args == original


def test_number_lookup_blocks_identity_of_guessed_pokemon():
    args = {"pokemon": "Lopunny"}
    result = before_tool_guard(_tool("pokemon_pokedex_identity"), args, _context(
        "Quel est le Pokémon numéro 369 du Pokédex national ?"))
    assert result["error"] == "unsupported_pokedex_number_constraint"
    assert result["required_tool"] == "pokemon_search"
    assert result["required_arguments"] == {"pokedex_number": 369}
    assert args == {"pokemon": "Lopunny"}


def test_number_lookup_restores_number_without_losing_form():
    args = {"pokedex_number": 428, "form": "alola"}
    assert before_tool_guard(_tool("pokemon_search"), args, _context(
        "Quel est le Pokémon n° 369 du Pokédex national ?")) is None
    assert args == {"pokedex_number": 369, "form": "alola"}


def test_identity_of_named_pokemon_remains_allowed():
    args = {"pokemon": "Lockpin"}
    assert before_tool_guard(_tool("pokemon_pokedex_identity"), args, _context(
        "Quel est le numéro national de Lockpin ?")) is None


def _context(question: str) -> SimpleNamespace:
    """Crée un faux ToolContext contenant le message utilisateur courant."""
    return SimpleNamespace(
        user_content=SimpleNamespace(
            parts=[
                SimpleNamespace(text=question),
            ]
        )
    )


def test_restores_explicit_level_range() -> None:
    args = {
        "pokemon": "Pikachu",
    }

    result = before_tool_guard(
        tool=_tool("pokemon_level_up_moves"),
        args=args,
        tool_context=_context(
            "Quelles attaques Pikachu apprend-il entre les niveaux 10 et 20 ?"
        ),
    )

    assert result is None
    assert args["pokemon"] == "Pikachu"
    assert args["min_level"] == 10
    assert args["max_level"] == 20


def test_overrides_incorrect_level_range_proposed_by_model() -> None:
    args = {
        "pokemon": "Pikachu",
        "min_level": 5,
        "max_level": 50,
    }

    result = before_tool_guard(
        tool=_tool("pokemon_level_up_moves"),
        args=args,
        tool_context=_context(
            "Quelles attaques Pikachu apprend-il entre les niveaux 10 et 20 ?"
        ),
    )

    assert result is None
    assert args["min_level"] == 10
    assert args["max_level"] == 20


def test_preserves_args_when_no_level_constraint_is_explicit() -> None:
    args = {
        "pokemon": "Pikachu",
    }

    original_args = args.copy()

    result = before_tool_guard(
        tool=_tool("pokemon_level_up_moves"),
        args=args,
        tool_context=_context(
            "Quelles attaques Pikachu apprend-il en montant de niveau ?"
        ),
    )

    assert result is None
    assert args == original_args


def test_blocks_tool_that_cannot_preserve_level_constraint() -> None:
    args = {
        "pokemon": "Pikachu",
    }

    result = before_tool_guard(
        tool=_tool("pokemon_types"),
        args=args,
        tool_context=_context(
            "Quels sont les types de Pikachu entre les niveaux 10 et 20 ?"
        ),
    )

    assert result is not None
    assert result["error"] == "unsupported_level_constraints"
    assert result["selected_tool"] == "pokemon_types"

    # Le guard ne doit pas inventer des arguments incompatibles
    # avec le schéma du tool sélectionné.
    assert args == {
        "pokemon": "Pikachu",
    }


def test_blocks_ambiguous_explicit_level_constraint() -> None:
    args = {
        "pokemon": "Pikachu",
    }

    result = before_tool_guard(
        tool=_tool("pokemon_level_up_moves"),
        args=args,
        tool_context=_context(
            "Quelles attaques Pikachu apprend-il au niveau 10 ou 20 ?"
        ),
    )

    assert result is not None
    assert result["error"] == "ambiguous_level_constraints"

    assert args == {
        "pokemon": "Pikachu",
    }


def test_allows_tool_when_user_content_is_missing() -> None:
    args = {
        "pokemon": "Pikachu",
    }

    context = SimpleNamespace(user_content=None)

    result = before_tool_guard(
        tool=_tool("pokemon_level_up_moves"),
        args=args,
        tool_context=context,
    )

    assert result is None
    assert args == {
        "pokemon": "Pikachu",
    }


def test_restores_explicit_version_group() -> None:
    args = {
        "pokemon": "Pikachu",
    }

    result = before_tool_guard(
        tool=_tool("pokemon_machine_moves"),
        args=args,
        tool_context=_context(
            "Quelles CT Pikachu peut-il apprendre dans Pokémon Écarlate ?"
        ),
    )

    assert result is None
    assert args["pokemon"] == "Pikachu"
    assert args["version_group"] == "scarlet-violet"


def test_overrides_incorrect_version_group_proposed_by_model() -> None:
    args = {
        "pokemon": "Pikachu",
        "version_group": "sword-shield",
    }

    result = before_tool_guard(
        tool=_tool("pokemon_machine_moves"),
        args=args,
        tool_context=_context(
            "Quelles CT Pikachu peut-il apprendre dans Pokémon Écarlate ?"
        ),
    )

    assert result is None
    assert args["version_group"] == "scarlet-violet"


def test_blocks_tool_that_cannot_preserve_version_constraint() -> None:
    args = {
        "pokemon": "Pikachu",
    }

    result = before_tool_guard(
        tool=_tool("pokemon_types"),
        args=args,
        tool_context=_context(
            "Quels sont les types de Pikachu dans Pokémon Écarlate ?"
        ),
    )

    assert result is not None
    assert result["error"] == "unsupported_version_constraint"
    assert result["selected_tool"] == "pokemon_types"

    assert args == {
        "pokemon": "Pikachu",
    }


def test_blocks_unresolved_or_ambiguous_explicit_version_constraint() -> None:
    args = {
        "pokemon": "Pikachu",
    }

    result = before_tool_guard(
        tool=_tool("pokemon_machine_moves"),
        args=args,
        tool_context=_context(
            "Quelles CT Pikachu peut-il apprendre dans le jeu Pokémon inconnu ?"
        ),
    )

    assert result is not None
    assert result["error"] in {
        "ambiguous_version_constraint",
        "unresolved_version_constraint",
    }

    assert args == {
        "pokemon": "Pikachu",
    }


def test_restores_version_and_level_constraints_together() -> None:
    args = {
        "pokemon": "Pikachu",
    }

    result = before_tool_guard(
        tool=_tool("pokemon_level_up_moves"),
        args=args,
        tool_context=_context(
            "Quelles attaques Pikachu apprend-il entre les niveaux 10 et 20 "
            "dans Pokémon Écarlate ?"
        ),
    )

    assert result is None

    assert args == {
        "pokemon": "Pikachu",
        "version_group": "scarlet-violet",
        "min_level": 10,
        "max_level": 20,
    }


def test_restores_explicit_form() -> None:
    args = {
        "pokemon": "Raichu",
    }

    result = before_tool_guard(
        tool=_tool("pokemon_types"),
        args=args,
        tool_context=_context(
            "Quels sont les types de Raichu d'Alola ?"
        ),
    )

    assert result is None
    assert args["form"] == "alola"


def test_overrides_incorrect_form_proposed_by_model() -> None:
    args = {
        "pokemon": "Raichu",
        "form": "galar",
    }

    result = before_tool_guard(
        tool=_tool("pokemon_types"),
        args=args,
        tool_context=_context(
            "Quels sont les types de Raichu d'Alola ?"
        ),
    )

    assert result is None
    assert args["form"] == "alola"


def test_blocks_tool_that_cannot_preserve_form_constraint() -> None:
    args = {
        "question": "Parle-moi de Raichu d'Alola.",
        "pokemon": "Raichu",
    }

    result = before_tool_guard(
        tool=_tool("pokemon_rag_search"),
        args=args,
        tool_context=_context(
            "Parle-moi de Raichu d'Alola."
        ),
    )

    assert result is not None
    assert result["error"] == "unsupported_form_constraint"
    assert result["selected_tool"] == "pokemon_rag_search"

    assert args == {
        "question": "Parle-moi de Raichu d'Alola.",
        "pokemon": "Raichu",
    }
