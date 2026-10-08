from types import SimpleNamespace

import pytest

from pokemon_rag.agent.tool_guard import before_tool_guard


@pytest.fixture(autouse=True)
def isolate_name_catalogue(monkeypatch):
    monkeypatch.setattr("pokemon_rag.agent.tool_guard.pokemon_name_catalogue", lambda: [])


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
    # legendary=False n'est pas demandé par la question : filtre inventé, retiré.
    del original["legendary"]
    assert args == {**original, "types":["fire"], "type_match":"all", "best_only":False, "offset":0}


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


NAMES = [("Méga-Dardargnan", "Dardargnan", "beedrill-mega"), ("Dardargnan", "Dardargnan", None),
         ("Dracolosse", "Dracolosse", None), ("Carabaffe", "Carabaffe", None)]


@pytest.fixture
def catalogue(monkeypatch):
    monkeypatch.setattr("pokemon_rag.agent.tool_guard.pokemon_name_catalogue", lambda: NAMES)


@pytest.mark.parametrize("question", [
    "Quelle est la défense spéciale de Méga-Dardargnan ?",
    "Quelles sont les statistiques de Méga-Dardargnan ?",
    "Combien de PV a Méga-Dardargnan ?",
])
def test_stat_of_a_named_pokemon_is_sent_to_the_stats_tool_not_left_without_issue(catalogue, question):
    # Régression : la recherche était refusée sans outil désigné ; le modèle répondait de mémoire.
    args = {"form_category": "mega", "sort_by": "special-defense"}
    refusal = before_tool_guard(_tool("pokemon_search"), args, _context(question))
    assert refusal["error"] == "unsupported_named_pokemon_constraint"
    assert refusal["required_tool"] == "pokemon_base_stats"
    assert refusal["required_arguments"] == {"pokemon": "Dardargnan", "form": "beedrill-mega"}
    assert args == {"form_category": "mega", "sort_by": "special-defense"}


@pytest.mark.parametrize("tool", ["pokemon_base_stats", "pokemon_particularities"])
@pytest.mark.parametrize("proposed", [{"pokemon": "Beedrill"}, {"pokemon": "Dardargnan"}, {}])
def test_named_tools_receive_the_pokemon_and_form_of_the_question(catalogue, tool, proposed):
    args = dict(proposed)
    assert before_tool_guard(_tool(tool), args, _context("Quelles sont les statistiques de Méga-Dardargnan ?")) is None
    assert args == {"pokemon": "Dardargnan", "form": "beedrill-mega"}


def test_stats_tool_is_refused_for_a_ranking_without_named_pokemon(catalogue):
    args = {"pokemon": "Regieleki"}
    refusal = before_tool_guard(_tool("pokemon_base_stats"), args, _context("Quel est le Pokémon le plus rapide ?"))
    assert refusal["error"] == "unsupported_search_constraints" and args == {"pokemon": "Regieleki"}


def test_move_question_naming_a_stat_word_does_not_point_to_the_stats_tool(catalogue):
    # « attaque » désigne ici une capacité : aucune réorientation vers les statistiques.
    refusal = before_tool_guard(_tool("pokemon_search"), {"move_type": "water"},
                                _context("Quelle attaque de type Eau Carabaffe apprend-il ?"))
    assert refusal.get("required_tool") != "pokemon_base_stats"


@pytest.mark.parametrize("question", [
    "Décris Dracolosse", "À quoi ressemble Dracolosse ?", "Quel est l'habitat de Dracolosse ?",
    "Quelle est l'origine de Dracolosse ?", "décris-moi le comportement de dracolosse",
])
@pytest.mark.parametrize("tool", ["pokemon_types", "pokemon_pokedex_identity", "pokemon_particularities", "pokemon_search"])
def test_description_question_refuses_every_tool_but_the_document_search(catalogue, question, tool):
    # Régression : « décris Tutafeh » recevait les types, puis une description rédigée de mémoire.
    args = {"pokemon": "Dracolosse"}
    refusal = before_tool_guard(_tool(tool), args, _context(question))
    assert refusal["error"] == "documentary_question_requires_search"
    assert refusal["required_tool"] == "pokemon_rag_search"
    assert refusal["required_arguments"] == {"question": question, "pokemon": "Dracolosse"}
    assert args == {"pokemon": "Dracolosse"}


def test_description_question_lets_the_document_search_through_unchanged(catalogue):
    args = {"question": "Décris Dracolosse", "pokemon": "Dracolosse"}
    assert before_tool_guard(_tool("pokemon_rag_search"), args, _context("Décris Dracolosse")) is None
    assert args == {"question": "Décris Dracolosse", "pokemon": "Dracolosse"}


@pytest.mark.parametrize("question, tool", [
    ("Décris Dracolosse et donne ses types", "pokemon_types"),          # demande composée
    ("Quels sont les types de Dracolosse ?", "pokemon_types"),          # aucune demande de description
    ("Quelle est l'origine du talent de Dracolosse ?", "pokemon_particularities"),
])
def test_structured_part_of_a_question_keeps_its_tools(catalogue, question, tool):
    refusal = before_tool_guard(_tool(tool), {"pokemon": "Dracolosse"}, _context(question))
    assert refusal is None or refusal["error"] != "documentary_question_requires_search"


def test_description_without_a_recognised_name_still_points_to_the_search(catalogue):
    refusal = before_tool_guard(_tool("pokemon_types"), {"pokemon": "Fauxkémon"}, _context("Décris Fauxkémon"))
    assert refusal["required_arguments"] == {"question": "Décris Fauxkémon"}


@pytest.mark.parametrize("proposed", [
    {"sort_by": "speed", "sort_order": "desc", "best_only": True},                # sous-groupe oublié
    {"subgroup": "Starter", "sort_by": "speed", "sort_order": "desc", "best_only": True},   # mauvais sous-groupe
    {"subgroup": "Fossile", "legendary": True, "sort_by": "attack"},              # filtre et tri inventés
])
def test_named_subgroup_is_restored_in_a_ranking_without_the_word_pokemon(catalogue, proposed):
    args = dict(proposed)
    assert before_tool_guard(_tool("pokemon_search"), args, _context("Quel est le fossile le plus rapide ?")) is None
    assert args["subgroup"] == "Fossile" and "legendary" not in args
    assert (args["sort_by"], args["sort_order"], args["best_only"]) == ("speed", "desc", True)


def test_pseudo_legendaries_are_listed_without_the_legendary_filter(catalogue):
    args = {"legendary": True}
    assert before_tool_guard(_tool("pokemon_search"), args, _context("Quels sont les pseudo-légendaires ?")) is None
    assert args.get("subgroup") == "Pseudo-légendaire" and "legendary" not in args


def test_subgroup_question_cannot_be_sent_to_a_tool_that_has_no_such_filter(catalogue):
    refusal = before_tool_guard(_tool("pokemon_types"), {"pokemon": "Ptéra"}, _context("Quel est le fossile le plus rapide ?"))
    assert refusal["error"] == "unsupported_search_constraints"
    assert refusal["required_arguments"]["subgroup"] == "Fossile"


CATEGORY_QUESTIONS = [
    ("Dracolosse est-il un pseudo-légendaire ?", "Dracolosse"),
    ("Dracolosse est-il un légendaire ?", "Dracolosse"),
    ("Carabaffe est-il un starter ?", "Carabaffe"),
]


@pytest.mark.parametrize("question, pokemon", CATEGORY_QUESTIONS)
@pytest.mark.parametrize("proposed", [{}, {"pokemon": "Mewtwo"}])
def test_category_of_a_named_pokemon_is_answered_by_its_particularities(catalogue, question, pokemon, proposed):
    # Régression : le mot de catégorie était exigé comme filtre de liste, donc refusé par tous les outils.
    # La fiche renvoie le sous-groupe : la catégorie reste dans le résultat, sans devenir un argument.
    args = dict(proposed)
    assert before_tool_guard(_tool("pokemon_particularities"), args, _context(question)) is None
    assert args == {"pokemon": pokemon}


@pytest.mark.parametrize("question, pokemon", CATEGORY_QUESTIONS)
@pytest.mark.parametrize("tool", ["pokemon_types", "pokemon_base_stats", "pokemon_pokedex_identity", "pokemon_search"])
def test_category_of_a_named_pokemon_points_other_tools_to_its_particularities(catalogue, question, pokemon, tool):
    args = {"pokemon": pokemon} if tool != "pokemon_search" else {}
    original = dict(args)
    refusal = before_tool_guard(_tool(tool), args, _context(question))
    assert refusal["required_tool"] == "pokemon_particularities"
    assert refusal["required_arguments"] == {"pokemon": pokemon}
    assert args == original


@pytest.mark.parametrize("question", [
    "Quels sont les starters de la 4e génération ?",                 # liste : aucun Pokémon nommé
    "Quels sont les légendaires de type Dragon ?",
    "Quel est le légendaire le plus rapide après Dracolosse ?",     # Pokémon nommé, mais un classement reste exigé
])
def test_particularities_stay_refused_when_a_list_is_requested(catalogue, question):
    args = {"pokemon": "Dracolosse"}
    refusal = before_tool_guard(_tool("pokemon_particularities"), args, _context(question))
    assert refusal["error"] == "unsupported_search_constraints"
    assert refusal.get("required_tool") != "pokemon_particularities"
    assert args == {"pokemon": "Dracolosse"}


def test_type_asked_about_a_named_pokemon_is_not_a_list_filter(catalogue):
    # Régression : « de type Dragon » était exigé comme filtre de liste, et tout outil refusé sans issue.
    args = {"pokemon": "Dracolosse"}
    question = "Dracolosse a-t-il toujours été de type Dragon ?"
    assert before_tool_guard(_tool("pokemon_particularities"), args, _context(question)) is None
    assert args == {"pokemon": "Dracolosse"}


@pytest.mark.parametrize("tool", ["pokemon_types", "pokemon_search", "pokemon_rag_search", "pokemon_base_stats"])
def test_type_asked_about_a_named_pokemon_points_other_tools_to_its_particularities(catalogue, tool):
    # pokemon_types compris : il ignore l'ancien type, et le modèle inventait l'historique à partir des types actuels.
    refusal = before_tool_guard(_tool(tool), {"types": ["Dragon"]}, _context("Dracolosse est-il de type Dragon et Vol ?"))
    assert refusal["error"] == "unsupported_named_pokemon_constraint"
    assert (refusal["required_tool"], refusal["required_arguments"]) == ("pokemon_particularities", {"pokemon": "Dracolosse"})


def test_type_and_category_asked_together_are_read_in_the_particularities(catalogue):
    question = "Dracolosse est-il un pseudo-légendaire de type Dragon ?"
    assert before_tool_guard(_tool("pokemon_particularities"), {"pokemon": "Dracolosse"}, _context(question)) is None
    refusal = before_tool_guard(_tool("pokemon_types"), {"pokemon": "Dracolosse"}, _context(question))
    assert refusal["required_tool"] == "pokemon_particularities"


@pytest.mark.parametrize("question", [
    "Quel est le Pokémon de type Dragon le plus rapide ?",              # aucun Pokémon nommé : le filtre reste exigé
    "Quel Pokémon de type Dragon est le plus rapide après Dracolosse ?",  # nommé, mais un classement reste exigé
])
def test_type_filter_of_a_list_is_still_required(catalogue, question):
    refusal = before_tool_guard(_tool("pokemon_types"), {"pokemon": "Dracolosse"}, _context(question))
    assert refusal["error"] == "unsupported_search_constraints"


@pytest.mark.parametrize("question", [
    "Dracolosse craint-il les attaques de type Glace ?",
    "Dracolosse est-il faible aux attaques Roche ?",
    "Dracolosse résiste-t-il aux capacités de type Plante ?",
    "Dracolosse est-il immunisé contre les attaques de type Sol ?",
])
def test_attack_type_asked_about_a_named_pokemon_is_read_in_the_particularities(catalogue, question):
    # Régression : le type d'attaque était exigé comme filtre de capacités, et la fiche refusée.
    args = {"pokemon": "Dracolosse"}
    assert before_tool_guard(_tool("pokemon_particularities"), args, _context(question)) is None
    assert args == {"pokemon": "Dracolosse"}
    refusal = before_tool_guard(_tool("pokemon_moves"), {"pokemon": "Dracolosse"}, _context(question))
    assert (refusal["required_tool"], refusal["required_arguments"]) == ("pokemon_particularities", {"pokemon": "Dracolosse"})


@pytest.mark.parametrize("question", [
    "Quelles attaques de type Feu Dracolosse apprend-il ?",                  # aucun mot de sensibilité
    "Quelle est la capacité de type Dragon la plus faible de Dracolosse ?",  # « faible » parle de puissance
    "Dracolosse craint-il les attaques spéciales de type Glace ?",           # la catégorie reste un filtre
    "Quels Pokémon craignent les attaques de type Glace ?",                  # aucun Pokémon nommé
])
def test_attack_type_filter_is_still_required_without_a_matchup_about_a_named_pokemon(catalogue, question):
    refusal = before_tool_guard(_tool("pokemon_particularities"), {"pokemon": "Dracolosse"}, _context(question))
    assert refusal["error"] == "unsupported_move_constraints"


@pytest.mark.parametrize("question", [
    "Dans quelle version pouvait-on obtenir Dracolosse à sa sortie ?",
    "Dans quel jeu obtient-on Dracolosse ?",
    "Quelles versions permettent d'obtenir Dracolosse ?",
])
def test_asking_which_game_does_not_name_a_game(catalogue, question):
    # Régression : le mot « version » sans jeu nommé valait « jeu inconnu », et tout outil était refusé.
    args = {"pokemon": "Dracolosse"}
    assert before_tool_guard(_tool("pokemon_particularities"), args, _context(question)) is None


@pytest.mark.parametrize("question", [
    "Combien de CT Dracolosse apprend-il dans chaque version ?",          # un détail par jeu n'est pas représentable
    "Quelles CT Dracolosse apprend-il dans le jeu Pokémon inconnu ?",     # jeu nommé mais inconnu
])
def test_an_unnamed_or_unknown_game_is_still_refused(catalogue, question):
    refusal = before_tool_guard(_tool("pokemon_machine_moves"), {"pokemon": "Dracolosse"}, _context(question))
    assert refusal["error"] == "ambiguous_version_constraint"


def test_a_zero_pokedex_number_is_a_placeholder_not_a_filter():
    # Régression : la question d'ouverture de l'interface échouait 2 fois sur 3 (numéro 0 refusé par le moteur).
    args = {"pokedex_number": 0}
    assert before_tool_guard(_tool("pokemon_search"), args, _context("Combien de Pokémon existe-t-il ?")) is None
    assert "pokedex_number" not in args
    kept = {"pokedex_number": 25}
    assert before_tool_guard(_tool("pokemon_search"), kept, _context("Quel Pokémon porte le numéro 25 ?")) is None
    assert kept["pokedex_number"] == 25
