"""Fidélité d'une réponse à une liste entièrement transmise : détection et rendu, sans modèle."""
from types import SimpleNamespace

from google.genai import types

from pokemon_rag.agent.context_budget import BUDGET_ABSTENTION, after_model_abstention
from pokemon_rag.agent.list_fidelity import REPLACEMENT_PREFIX, complete_list, render, unfaithful_names

LEGENDARIES = {"operation": "search_pokemon", "total_count": 9, "returned_count": 9, "results": [
    {"name_fr": name} for name in ("Créhelf", "Créfollet", "Créfadet", "Dialga", "Palkia", "Heatran",
                                   "Regigigas", "Giratina", "Cresselia")]}
# Réponse réelle du 7 octobre (LM Studio), trio des lacs nié malgré le résultat.
DENYING = ("Les Pokémon légendaires introduits en quatrième génération sont : Dialga, Palkia, Heatran, Regigigas, "
           "Giratina, Cresselia.\nNote : Créhelf, Créfollet et Créfadet ne sont pas des Pokémon légendaires.")


def test_only_complete_short_lists_of_list_tools_are_checked():
    assert complete_list("pokemon_search", LEGENDARIES)["names"][0] == "Créhelf"
    assert complete_list("pokemon_types", {"rows": [{"name_fr": "Hexagel"}], "results": [{"name_fr": "Hexagel"}]}) is None
    assert complete_list("pokemon_search", {**LEGENDARIES, "context_truncated": True}) is None
    assert complete_list("pokemon_search", {"results": [], "total_count": 65}) is None  # comptage
    assert complete_list("pokemon_search", {"results": [{"name_fr": str(i)} for i in range(31)]}) is None


def test_omitted_or_denied_rows_are_found_and_faithful_wording_passes():
    listing = complete_list("pokemon_search", LEGENDARIES)
    assert unfaithful_names(listing, DENYING) == ["Créhelf", "Créfollet", "Créfadet"]
    faithful = "Légendaires : **Créhelf**, Créfollet, Créfadet, Dialga, Palkia, Heatran, Regigigas, Giratina et Cresselia."
    assert unfaithful_names(listing, faithful) == []


def test_rendering_keeps_values_ties_and_the_total():
    ranking = {"operation": "search_pokemon", "stat_name_fr": "Vitesse", "total_count": 2,
               "results": [{"name_fr": "Méga-Ténéfix", "Vitesse": 20}, {"name_fr": "Méga-Camérupt", "Vitesse": 20}]}
    assert render(complete_list("pokemon_search", ranking)) == (
        f"{REPLACEMENT_PREFIX}, 2 Pokémon correspondent à la question : "
        "Méga-Ténéfix (Vitesse : 20), Méga-Camérupt (Vitesse : 20).")
    page = {"operation": "search_pokemon", "total_count": 96, "results": [{"name_fr": "Ouistempo"}]}
    assert "96 Pokémon" in render(complete_list("pokemon_search", page)) and "voici les 1 premiers" in render(
        complete_list("pokemon_search", page))


def _answer(text, listing, failed=False):
    context = SimpleNamespace(state={"temp:fidelity_list": listing, "temp:every_tool_call_failed": failed})
    response = SimpleNamespace(partial=False, content=types.Content(role="model", parts=[types.Part(text=text)]))
    return after_model_abstention(context, response)


def test_an_unfaithful_answer_is_replaced_and_others_are_left_alone():
    listing = complete_list("pokemon_search", LEGENDARIES)
    replaced = _answer(DENYING, listing)
    assert replaced.content.parts[0].text.startswith(REPLACEMENT_PREFIX)
    assert _answer(", ".join(listing["names"]), listing) is None
    assert _answer(BUDGET_ABSTENTION, listing) is None
    assert _answer("Hexagel est de type Glace.", None) is None
