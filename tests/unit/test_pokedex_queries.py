import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from pokemon_rag.structured import query_engine as engine, query_parser as parser
from pokemon_rag.graph.nodes import format_structured_answer, _structured_result_to_context


@pytest.fixture(autouse=True)
def catalog(monkeypatch):
    def connect():
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript('''
            CREATE TABLE custom_pokedex(
              species_id INTEGER, is_default INTEGER, name_fr TEXT, name_en TEXT,
              pokemon_identifier TEXT, form_identifier TEXT, form_fr TEXT, form_en TEXT,
              type_1_fr TEXT, type_2_fr TEXT, national_number INTEGER,
              introduction_generation_fr TEXT, signature_move_fr TEXT, pseudo_signature_move_fr TEXT);
            INSERT INTO custom_pokedex VALUES
              (25,1,'Pikachu','Pikachu','pikachu','pikachu',NULL,NULL,'Électrik',NULL,25,'G1','Électacle','Tonnerre (G1)'),
              (103,1,'Noadkoko','Exeggutor','exeggutor','exeggutor',NULL,NULL,'Plante','Psy',103,'G1',NULL,NULL),
              (103,0,'Noadkoko d’Alola','Alolan Exeggutor','exeggutor-alola','exeggutor-alola','Forme d’Alola','Alolan Form','Plante','Dragon',103,'G7','Draco-Marteau (G7)',NULL);
        ''')
        return conn
    monkeypatch.setattr(engine, "_connect", connect)


@pytest.mark.parametrize("question, operation", [
    ("Quels sont les types de Pikachu ?", "get_pokemon_types"),
    ("Quel est le numéro national de Pikachu ?", "get_pokedex_identity"),
    ("Quelle est la génération d'introduction de Pikachu ?", "get_pokedex_identity"),
    ("Quelle est la capacité signature de Pikachu ?", "get_signature_moves"),
    ("Quels sont les types de Noadkoko d'Alola ?", "get_pokemon_types"),
])
def test_simple_questions_execute_without_llm(question, operation):
    with patch.object(parser.llm_client.chat.completions, "create") as llm:
        result = parser.query_structured_data(question)
    assert result["error"] is None
    assert result["operation"] == operation
    llm.assert_not_called()
    assert result["rows"]
    assert "ENTRÉE STRUCTURÉE" in _structured_result_to_context(result)


def test_forms_are_isolated_and_english_names_supported():
    base = engine.get_pokemon_types("Exeggutor")
    regional = engine.get_pokemon_types("Alolan Exeggutor")
    assert base["rows"][0]["type_2_fr"] == "Psy"
    assert regional["rows"][0]["type_2_fr"] == "Dragon"
    assert engine.get_pokemon_types("Noadkoko", "alola")["rows"] == regional["rows"]


@pytest.mark.parametrize("default_form_id, expected", [(10132, "Mode Paisible"), (716, "Mode Déchaîné"), (None, None)])
def test_species_sharing_one_pokemon_resolves_to_its_default_form(monkeypatch, default_form_id, expected):
    # Deux modes, un seul pokemon_id : les deux lignes portent is_default=1.
    def connect():
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript('''
            CREATE TABLE custom_pokedex(species_id INTEGER, is_default INTEGER, pokemon_form_id INTEGER,
              name_fr TEXT, name_en TEXT, pokemon_identifier TEXT, form_identifier TEXT, form_fr TEXT,
              form_en TEXT, type_1_fr TEXT, type_2_fr TEXT);
            INSERT INTO custom_pokedex VALUES
              (716,1,10132,'Xerneas Paisible','Neutral Xerneas','xerneas','xerneas-neutral','Mode Paisible','Neutral Mode','Fée',NULL),
              (716,1,716,'Xerneas Déchaîné','Active Xerneas','xerneas','xerneas-active','Mode Déchaîné','Active Mode','Fée',NULL);
            CREATE TABLE pokemon_forms(id INTEGER, is_default INTEGER);
            INSERT INTO pokemon_forms VALUES (10132,0),(716,0);
            CREATE TABLE language_ids(fr INTEGER, en INTEGER);
            INSERT INTO language_ids VALUES (5,9);
            CREATE TABLE pokemon_species(id INTEGER, identifier TEXT);
            INSERT INTO pokemon_species VALUES (716,'xerneas');
            CREATE TABLE pokemon_species_names(pokemon_species_id INTEGER, local_language_id INTEGER, name TEXT);
            INSERT INTO pokemon_species_names VALUES (716,5,'Xerneas'),(716,9,'Xerneas');
        ''')
        conn.execute("UPDATE pokemon_forms SET is_default=1 WHERE id IS ?", (default_form_id,))
        return conn
    monkeypatch.setattr(engine, "_connect", connect)
    if expected is None:
        # Aucune forme par défaut connue : pas de choix arbitraire.
        with pytest.raises(ValueError):
            engine.get_pokemon_types("Xerneas")
    else:
        # L'espèce demandée sans forme garde son nom ; la forme retenue reste lisible à part.
        result = engine.get_pokemon_types("Xerneas")
        assert (result["pokemon"], result["form"], result["rows"][0]["name_fr"]) == ("Xerneas", expected, "Xerneas")
    # Une forme nommée n'est jamais remplacée par la forme par défaut, ni renommée.
    assert engine.get_pokemon_types("Xerneas Déchaîné")["pokemon"] == "Xerneas Déchaîné"
    assert engine.get_pokemon_types("Xerneas", "Mode Déchaîné")["pokemon"] == "Xerneas Déchaîné"
    assert engine.get_pokemon_types("Xerneas", "Mode Paisible")["pokemon"] == "Xerneas Paisible"


@pytest.mark.parametrize("pokemon, form", [
    ("Inconnu", None), ("Pikachu", "alola"), ("Noadkoko d'Alola", "galar"),
    ("", None), ("---", None), (None, None), ("Pikachu", ""), ("Pikachu", 123),
])
def test_unknown_entry_or_form_is_not_replaced_by_base(pokemon, form):
    with pytest.raises(ValueError):
        engine.get_pokemon_types(pokemon, form)


def test_signature_annotations_and_missing_values_are_preserved():
    result = engine.get_signature_moves("Pikachu")
    assert "Tonnerre (G1)" in format_structured_answer({"structured_result": result})["answer"]
    missing = engine.get_signature_moves("Noadkoko")
    assert "non renseigné" in format_structured_answer({"structured_result": missing})["answer"]


def test_identity_uses_generation_of_selected_form():
    row = engine.get_pokedex_identity("Alolan Exeggutor")["rows"][0]
    assert row["national_number"] == 103
    assert row["introduction_generation_fr"] == "G7"


@pytest.mark.parametrize("operation", sorted(engine.POKEDEX_OPERATIONS))
def test_version_filters_are_rejected(operation):
    with pytest.raises(ValueError, match="version"):
        engine.validate_plan({"operation": operation, "pokemon": "Pikachu", "form": None, "version_group": "red-blue"})


@pytest.mark.parametrize("game", ["dans Rouge et Bleu", "en Rouge et Bleu", "dans JeuInconnu"])
def test_llm_cannot_silently_drop_explicit_game(game):
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=
        '{"operation":"get_pokemon_types","pokemon":"Pikachu","form":null,"version_group":null}'))])
    with patch.object(parser, "_fast_parse_query", return_value=None), patch.object(
        parser.llm_client.chat.completions, "create", return_value=response
    ), patch.object(engine, "execute_plan") as execute:
        result = parser.query_structured_data(f"Quels sont les types de Pikachu {game} ?")
    assert result["error"]
    execute.assert_not_called()


def test_sql_engine_mcp_server_and_guard_load_no_llm_client():
    """Interpréteur neuf : le parcours SQL/MCP ne doit importer ni client LLM ni analyse de question."""
    import subprocess
    import sys

    code = ("import sys\n"
            "import pokemon_rag.structured.query_engine, pokemon_rag.mcp.server, pokemon_rag.agent.tool_guard\n"
            "loaded = [name for name in ('openai', 'pokemon_rag.structured.query_parser') if name in sys.modules]\n"
            "sys.exit(', '.join(loaded) or 0)")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.fixture
def spreadsheet(monkeypatch):
    """Deux formes d'une espèce avec leur ligne de tableur ; le total stocké est volontairement faux."""
    def connect():
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript('''
            CREATE TABLE custom_pokedex(source_row INTEGER, species_id INTEGER, is_default INTEGER,
              pokemon_form_id INTEGER, name_fr TEXT, name_en TEXT, pokemon_identifier TEXT,
              form_identifier TEXT, form_fr TEXT, form_en TEXT);
            INSERT INTO custom_pokedex VALUES
              (20,15,1,15,'Dardargnan','Beedrill','beedrill','beedrill',NULL,NULL),
              (21,15,0,10090,'Méga-Dardargnan','Mega Beedrill','beedrill-mega','beedrill-mega','Méga','Mega');
            CREATE TABLE custom_pokedex_fr(source_row INTEGER, total_de_base INTEGER, pv INTEGER, attaque INTEGER,
              defense INTEGER, attaque_speciale INTEGER, defense_speciale INTEGER, vitesse INTEGER,
              talent_1 TEXT, talent_2 TEXT, talent_cache TEXT, talent_signature TEXT,
              double_type_unique_a_l_introduction TEXT, stade_d_evolution TEXT, sous_groupe TEXT,
              analyse_des_statistiques TEXT, mise_en_avant_a_l_introduction TEXT,
              rencontre_ou_obtention_a_l_introduction TEXT, particularite_du_movepool TEXT,
              autre_particularite TEXT, differences_physiques_selon_le_sexe TEXT,
              type_1 TEXT, type_2 TEXT, ancien_type TEXT, pokemon_id INTEGER, exclusif_a TEXT);
            INSERT INTO custom_pokedex_fr VALUES
              (20,999,65,90,40,45,80,75,'Essaim',NULL,'Sniper',NULL,NULL,'Final · stade 3',
               'Insecte de début d’aventure',NULL,NULL,NULL,NULL,'Possède une Méga-Évolution introduite en G6.','','Insecte','Poison',
               'Insecte (G1)',15,'Rouge'),
              (21,999,65,150,40,15,80,145,'Adaptabilité',NULL,NULL,NULL,NULL,'Méga-Évolution',
               'Insecte de début d’aventure ; Méga-Évolution','Top 10 global — Attaque',NULL,NULL,NULL,NULL,NULL,'Insecte','Poison',NULL,10090,NULL);
            -- Unités et type PokéAPI : décimètres, hectogrammes, taux de capture en TEXT. Le poids nul
            -- de la Méga est fictif : il tient lieu de valeur de remplissage (Éthernatos Infinimax).
            CREATE TABLE pokemon(id INTEGER, species_id INTEGER, height INTEGER, weight INTEGER);
            INSERT INTO pokemon VALUES (15,15,10,295), (10090,15,14,0);
            CREATE TABLE pokemon_species(id INTEGER, identifier TEXT, capture_rate TEXT);
            INSERT INTO pokemon_species VALUES (15,'beedrill','45');
            -- Dès que pokemon_species existe, la résolution de l'entrée passe par le catalogue des espèces.
            CREATE TABLE language_ids(fr INTEGER, en INTEGER);
            INSERT INTO language_ids VALUES (5,9);
            CREATE TABLE pokemon_species_names(pokemon_species_id INTEGER, local_language_id INTEGER, name TEXT);
            INSERT INTO pokemon_species_names VALUES (15,5,'Dardargnan'), (15,9,'Beedrill');
        ''')
        return conn
    monkeypatch.setattr(engine, "_connect", connect)


@pytest.mark.parametrize("pokemon, form", [("Méga-Dardargnan", None), ("Dardargnan", "beedrill-mega"), ("Dardargnan", "Méga")])
def test_base_stats_of_a_named_form_are_read_for_that_form_with_a_sql_total(spreadsheet, pokemon, form):
    # Régression : aucune opération ne donnait la statistique d'un Pokémon nommé ; le modèle répondait de mémoire.
    result = engine.get_base_stats(pokemon, form)
    assert result["operation"] == "get_base_stats" and result["pokemon"] == "Méga-Dardargnan" and result["count"] == 1
    assert result["rows"] == [{"name_fr": "Méga-Dardargnan", "PV": 65, "Attaque": 150, "Défense": 40,
                               "Attaque Spéciale": 15, "Défense Spéciale": 80, "Vitesse": 145,
                               "Total des statistiques": 495}]  # somme SQL, pas le total stocké (999)


def test_base_stats_without_form_use_the_default_entry_not_the_mega(spreadsheet):
    row = engine.get_base_stats("Dardargnan")["rows"][0]
    assert (row["name_fr"], row["Attaque"], row["Vitesse"], row["Total des statistiques"]) == ("Dardargnan", 90, 75, 395)


def test_particularities_keep_filled_headings_only_and_stay_form_specific(spreadsheet):
    base = engine.get_particularities("Dardargnan")["rows"][0]
    assert base == {"name_fr": "Dardargnan", "Type 1": "Insecte", "Type 2": "Poison", "Ancien type": "Insecte (G1)",
                    "Talent 1": "Essaim", "Talent caché": "Sniper",
                    "Stade d'évolution": "Final · stade 3", "Sous-groupe": "Insecte de début d’aventure",
                    "Version exclusive à l'introduction": "Rouge",  # valeur fictive : la rubrique suit la colonne
                    "Autre particularité": "Possède une Méga-Évolution introduite en G6.",
                    "Taille": "1,0 m", "Poids": "29,5 kg", "Taux de capture": "45 sur 255"}
    mega = engine.get_particularities("Méga-Dardargnan")["rows"][0]
    assert mega["Talent 1"] == "Adaptabilité" and "Talent caché" not in mega and "Ancien type" not in mega
    assert "Version exclusive à l'introduction" not in mega
    assert mega["Statistiques remarquables"] == "Parmi tous les Pokémon — Attaque"
    # Mesures de la forme, pas de l'espèce ; une valeur de remplissage n'est pas restituée comme un poids.
    assert mega["Taille"] == "1,4 m" and "Poids" not in mega and mega["Taux de capture"] == "45 sur 255"


def test_spreadsheet_shorthand_is_spelled_out_without_changing_any_value():
    # Régression : « PV #6 (30) » recopié sans « Bottom 10 » se lisait comme un 6e meilleur score.
    text = ("Bottom 10 global — PV #3 (20), Vitesse #1 (5) ; Top 10 parmi les Méga-Évolutions — Défense #2 (230) ; "
            "Minima G2 — PV 20 ; Records G2 au même stade évolutif — Défense 230 ; "
            "Outliers faibles pour le stade évolutif — Total 395 ; Baisse en évoluant depuis Chrysacier : Défense 55→50 (-5) ; "
            "Top 10 global des répartitions les plus extrêmes : écart 225")
    assert engine._readable(text) == (
        # Le sens est dans chaque valeur : une légende « rang 1 = la plus basse » était lue comme un fait.
        "Parmi tous les Pokémon — PV : 3e plus basse (20), Vitesse : la plus basse (5) ; "
        "Parmi les Méga-Évolutions — Défense : 2e plus haute (230) ; "
        "Plus basse valeur de la génération 2 — PV 20 ; Plus haute valeur de la génération 2 à stade d'évolution égal — Défense 230 ; "
        "Anormalement bas pour son stade d'évolution — Total 395 ; Baisse en évoluant depuis Chrysacier : Défense 55→50 (-5) ; "
        "Parmi les 10 répartitions les plus déséquilibrées (tous les Pokémon) : 225 d'écart entre sa statistique la plus haute et la plus basse")
    assert engine._readable("Possède une ou plusieurs formes alternatives recensées dans ce classeur.") == "Possède une ou plusieurs formes alternatives."
    assert engine._readable("Rencontre fixe unique au fond de la Caverne Azurée.") == "Rencontre fixe unique au fond de la Caverne Azurée."


@pytest.mark.parametrize("function", [engine.get_base_stats, engine.get_particularities])
@pytest.mark.parametrize("pokemon, form", [("Inconnu", None), ("Dardargnan", "alola"), ("", None)])
def test_stats_and_particularities_of_unknown_entry_or_form_are_errors(spreadsheet, function, pokemon, form):
    with pytest.raises(ValueError):
        function(pokemon, form)
