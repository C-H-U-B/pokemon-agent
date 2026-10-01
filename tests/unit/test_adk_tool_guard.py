from types import SimpleNamespace

from pokemon_rag.agent.tool_guard import before_tool_guard


def _tool(name: str) -> SimpleNamespace:
    """Crée un faux tool ADK minimal."""
    return SimpleNamespace(name=name)


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