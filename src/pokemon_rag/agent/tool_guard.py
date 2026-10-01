from __future__ import annotations

from typing import Any

from pokemon_rag.constraints.query_constraints import extract_explicit_constraints


def _extract_user_text(user_content: Any) -> str:
    """Extrait le texte du message utilisateur courant fourni par ADK."""
    if user_content is None:
        return ""

    parts = getattr(user_content, "parts", None)
    if not parts:
        return ""

    texts: list[str] = []

    for part in parts:
        text = getattr(part, "text", None)
        if text:
            texts.append(str(text))

    return "\n".join(texts).strip()


def before_tool_guard(
    tool: Any,
    args: dict[str, Any],
    tool_context: Any,
) -> dict[str, Any] | None:
    """Valide les contraintes explicites avant l'exécution d'un outil ADK.

    Cette première version protège uniquement les contraintes de niveaux.

    Le callback retourne :
    - None pour laisser ADK exécuter l'outil ;
    - un dictionnaire pour court-circuiter l'exécution du tool.
    """
    question = _extract_user_text(
        getattr(tool_context, "user_content", None)
    )

    if not question:
        return None

    try:
        constraints = extract_explicit_constraints(question)
    except ValueError as exc:
        return {
            "error": "invalid_explicit_constraints",
            "message": str(exc),
        }

    if not constraints.level_explicit:
        return None

    if constraints.level_bounds is None:
        return {
            "error": "ambiguous_level_constraints",
            "message": (
                "La question contient une contrainte explicite de niveau, "
                "mais elle ne peut pas être interprétée sans ambiguïté."
            ),
        }

    minimum, maximum = constraints.level_bounds

    tool_name = getattr(tool, "name", "")

    if tool_name != "pokemon_level_up_moves":
        return {
            "error": "unsupported_level_constraints",
            "message": (
                "La question contient une contrainte explicite de niveau, "
                "mais l'outil sélectionné ne permet pas de la respecter."
            ),
            "selected_tool": tool_name,
        }

    if minimum is not None:
        args["min_level"] = minimum

    if maximum is not None:
        args["max_level"] = maximum

    return None