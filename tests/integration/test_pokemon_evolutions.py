from __future__ import annotations

import pytest
pytestmark = pytest.mark.real_data

from pokemon_rag.structured.query_engine import get_evolutions


def find_evolution(
    result: dict,
    target_identifier: str,
    version_group: str | None = None,
) -> dict | None:
    for evolution in result["evolutions"]:
        if evolution["to"]["identifier"] != target_identifier:
            continue
        if version_group is not None and evolution["version_group"] != version_group:
            continue
        return evolution
    return None


def test_pikachu_regional_target() -> None:
    result = get_evolutions("Pikachu")

    assert result["operation"] == "get_evolutions"
    assert result["count"] == 2

    normal = find_evolution(result, "raichu", "red-blue")
    alola = find_evolution(result, "raichu", "sun-moon")

    assert normal is not None
    assert alola is not None
    assert normal["conditions"].get("trigger_item", {}).get("fr") == "Pierre Foudre"
    assert alola["to"].get("form", {}).get("form_identifier") == "alola"
    assert alola["conditions"].get("region", {}).get("fr") == "Alola"


def test_dinoclier_level_evolution() -> None:
    result = get_evolutions("Dinoclier")
    evolution = find_evolution(result, "bastiodon")

    assert result["count"] == 1
    assert evolution is not None
    assert evolution["trigger"] == "level-up"
    assert evolution["conditions"].get("minimum_level") == 30


def test_debugant_stat_branches() -> None:
    result = get_evolutions("Debugant")

    kicklee = find_evolution(result, "hitmonlee")
    tygnon = find_evolution(result, "hitmonchan")
    kapoera = find_evolution(result, "hitmontop")

    assert result["count"] == 3
    assert kicklee is not None
    assert tygnon is not None
    assert kapoera is not None

    assert kicklee["conditions"].get("relative_physical_stats") == 1
    assert tygnon["conditions"].get("relative_physical_stats") == -1

    # Dans la représentation actuelle, l'égalité (0) est omise des
    # conditions non nulles plutôt que sérialisée explicitement à 0.
    assert kapoera["conditions"].get("relative_physical_stats") == 0


def test_sepiatop_special_condition() -> None:
    result = get_evolutions("Sepiatop")
    evolution = find_evolution(result, "malamar")

    assert result["count"] == 1
    assert evolution is not None
    assert evolution["conditions"].get("minimum_level") == 30
    assert evolution["conditions"].get("turn_upside_down") == 1


def test_tutafeh_galar_form_isolation() -> None:
    result = get_evolutions("Tutafeh", form="Galar")

    assert result["operation"] == "get_evolutions"
    assert result["form"] == "Galar"
    assert result["count"] == 1

    assert all(
        evolution.get("from", {}).get("form", {}).get("form_identifier") == "galar"
        or evolution["conditions"].get("required_pokemon_form", {}).get("form_identifier") == "galar"
        for evolution in result["evolutions"]
    )


def test_dofin_multiplayer_condition() -> None:
    result = get_evolutions("Dofin")
    evolution = find_evolution(result, "palafin")

    assert result["count"] == 1
    assert evolution is not None
    assert evolution["conditions"].get("needs_multiplayer") == 1


def test_evoli_has_multiple_historical_evolution_rules() -> None:
    result = get_evolutions("Évoli")

    assert result["count"] > 1
    targets = {evolution["to"]["identifier"] for evolution in result["evolutions"]}

    assert "vaporeon" in targets
    assert "jolteon" in targets
    assert "flareon" in targets


def test_version_filter_keeps_the_rules_in_force_in_that_game() -> None:
    # Régression : le filtre ne gardait que les règles introduites dans le jeu demandé, donc 3 évolutions
    # d'Évoli sur 8 dans Épée et Bouclier, et aucune pour Pikachu dans Écarlate et Violet.
    result = get_evolutions("Évoli", version_group="sword-shield")

    assert result["version_group"] == "sword-shield"
    targets = [evolution["to"]["identifier"] for evolution in result["evolutions"]]
    assert sorted(targets) == ["espeon", "flareon", "glaceon", "jolteon", "leafeon", "sylveon", "umbreon", "vaporeon"]
    # Givrali : la Pierre Glace d'Épée et Bouclier remplace le lieu des jeux précédents.
    assert find_evolution(result, "glaceon")["version_group"] == "sword-shield"
    assert find_evolution(result, "vaporeon")["version_group"] == "red-blue"

    assert find_evolution(get_evolutions("Pikachu", version_group="scarlet-violet"), "raichu") is not None


def test_version_filter_excludes_rules_introduced_later() -> None:
    targets = {evolution["to"]["identifier"]
               for evolution in get_evolutions("Évoli", version_group="red-blue")["evolutions"]}
    assert targets == {"vaporeon", "jolteon", "flareon"}


def test_one_rule_per_target_without_version() -> None:
    # Régression : une ligne par jeu d'introduction, 19 lignes pour les 8 évolutions d'Évoli.
    targets = [evolution["to"]["identifier"] for evolution in get_evolutions("Évoli")["evolutions"]]
    assert len(targets) == len(set(targets)) == 8


def test_unknown_version_is_refused_not_read_as_no_evolution() -> None:
    with pytest.raises(ValueError, match="Groupe de versions inconnu"):
        get_evolutions("Pikachu", version_group="version-inexistante")


def test_neutral_form_means_no_form() -> None:
    assert get_evolutions("Pikachu", form="default")["evolutions"] == get_evolutions("Pikachu")["evolutions"]


@pytest.mark.parametrize(
    ("pokemon", "form"),
    [
        ("PokémonQuiNExistePas", None),
        ("Tutafeh", "FormeQuiNExistePas"),
    ],
    ids=[
        "unknown-pokemon",
        "unknown-form",
    ],
)
def test_invalid_inputs_raise_value_error(
    pokemon: str,
    form: str | None,
) -> None:
    with pytest.raises(ValueError):
        get_evolutions(pokemon, form=form)


@pytest.mark.real_data
@pytest.mark.parametrize("pokemon, trigger, trigger_fr, minimum_level", [
    ("Capumain", "level-up", "gain d'un niveau, quel que soit le niveau", None),   # condition : capacité connue
    ("Salamèche", "level-up", "montée de niveau", 16),
    ("Kadabra", "trade", "échange", None),
    ("Évoli", "use-item", "utilisation d'un objet", None),
])
def test_evolution_trigger_is_stated_in_french_and_never_implies_a_level(pokemon, trigger, trigger_fr, minimum_level):
    from pokemon_rag.structured.query_engine import get_evolutions
    evolution = get_evolutions(pokemon)["evolutions"][0]
    assert (evolution["trigger"], evolution["trigger_fr"]) == (trigger, trigger_fr)
    assert evolution["conditions"].get("minimum_level") == minimum_level


@pytest.mark.real_data
def test_every_evolution_trigger_used_in_the_database_has_a_french_label():
    from pokemon_rag.structured import query_engine
    conn = query_engine._connect()
    try:
        used = {row[0] for row in conn.execute(
            "SELECT DISTINCT et.identifier FROM pokemon_evolution pe "
            "JOIN evolution_triggers et ON et.id = pe.evolution_trigger_id")}
    finally:
        conn.close()
    assert used <= set(query_engine.EVOLUTION_TRIGGERS_FR)
    evolution = query_engine.get_evolutions("Tutafeh", form="galar")["evolutions"][0]
    assert evolution["trigger_fr"] == "dégâts subis"
