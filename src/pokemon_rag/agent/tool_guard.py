from __future__ import annotations

from typing import Any

from pokemon_rag.constraints.query_constraints import extract_explicit_constraints, extract_national_pokedex_number


VERSION_GROUP_TOOLS = {
    "pokemon_moves",
    "pokemon_search",
    "pokemon_evolutions",
    "pokemon_level_up_moves",
    "pokemon_move_learning_methods",
    "pokemon_machine_moves",
}

FORM_TOOLS = {
    "pokemon_moves",
    "pokemon_search",
    "pokemon_evolutions",
    "pokemon_level_up_moves",
    "pokemon_move_learning_methods",
    "pokemon_machine_moves",
    "pokemon_types",
    "pokemon_pokedex_identity",
    "pokemon_signature_moves",
}


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

    Protège actuellement :
    - les contraintes explicites de niveaux ;
    - les contraintes explicites de jeu/version ;
    - les formes régionales reconnues par l'extracteur commun.

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
        national_number = extract_national_pokedex_number(question)
    except ValueError as exc:
        return {
            "error": "invalid_explicit_constraints",
            "message": str(exc),
        }

    tool_name = getattr(tool, "name", "")
    if national_number is not None:
        if tool_name != "pokemon_search":
            return {
                "error": "unsupported_pokedex_number_constraint",
                "message": "Recherchez ce numéro avec pokemon_search, sans deviner un nom de Pokémon.",
                "selected_tool": tool_name,
                "required_tool": "pokemon_search",
                "required_arguments": {"pokedex_number": national_number},
            }
        args["pokedex_number"] = national_number

    # ------------------------------------------------------------------
    # Contraintes de jeu / version
    # ------------------------------------------------------------------

    if constraints.version_ambiguous:
        return {
            "error": "ambiguous_version_constraint",
            "message": (
                "La question contient une contrainte explicite de jeu/version, "
                "mais elle ne peut pas être interprétée sans ambiguïté."
            ),
        }

    if constraints.explicit_game:
        if constraints.version_group is None:
            return {
                "error": "unresolved_version_constraint",
                "message": (
                    "La question contient une contrainte explicite de jeu/version, "
                    "mais aucune version connue n'a pu être déterminée."
                ),
            }

        if tool_name not in VERSION_GROUP_TOOLS:
            return {
                "error": "unsupported_version_constraint",
                "message": (
                    "La question contient une contrainte explicite de jeu/version, "
                    "mais l'outil sélectionné ne permet pas de la respecter."
                ),
                "selected_tool": tool_name,
            }

        args["version_group"] = constraints.version_group

    # ------------------------------------------------------------------
    # Contraintes de forme
    # ------------------------------------------------------------------

    if constraints.form is not None:
        if tool_name not in FORM_TOOLS:
            return {
                "error": "unsupported_form_constraint",
                "message": (
                    "La question contient une contrainte explicite de forme, "
                    "mais l'outil sélectionné ne permet pas de la respecter."
                ),
                "selected_tool": tool_name,
            }

        args["form"] = constraints.form

    # ------------------------------------------------------------------
    # Contraintes de niveaux
    # ------------------------------------------------------------------

    if constraints.level_explicit:
        if constraints.level_bounds is None:
            return {
                "error": "ambiguous_level_constraints",
                "message": (
                    "La question contient une contrainte explicite de niveau, "
                    "mais elle ne peut pas être interprétée sans ambiguïté."
                ),
            }

        if tool_name not in {"pokemon_level_up_moves", "pokemon_moves", "pokemon_search"}:
            return {
                "error": "unsupported_level_constraints",
                "message": (
                    "La question contient une contrainte explicite de niveau, "
                    "mais l'outil sélectionné ne permet pas de la respecter."
                ),
                "selected_tool": tool_name,
            }

        minimum, maximum = constraints.level_bounds

        if tool_name in {"pokemon_moves", "pokemon_search"}:
            if args.get("learning_method") not in (None, "level-up"):
                return {"error": "incompatible_learning_method",
                        "message": "Les bornes de niveau exigent la montée de niveau."}
            args["learning_method"] = "level-up"
            args["min_level"], args["max_level"] = minimum, maximum
            return None

        if minimum is not None:
            args["min_level"] = minimum

        if maximum is not None:
            args["max_level"] = maximum

    return None
