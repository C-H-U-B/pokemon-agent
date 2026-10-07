"""Choix des illustrations sous une réponse : sans base, sans réseau, sans modèle."""
from pokemon_rag.constraints.query_constraints import normalize
from pokemon_rag.web.app import _answer_images

URLS = {normalize(name): f"https://img/{key}.png" for name, key in (
    ("Pikachu", "25"), ("Raichu", "26"), ("Raichu d’Alola", "10100"), ("Mew", "151"), ("Mewtwo", "150"),
    ("Abo", "23"), ("Bulbizarre", "1"), ("Salamèche", "4"), ("Carapuce", "7"), ("Herbizarre", "2"))}


def test_only_names_cited_and_present_in_the_data_are_illustrated():
    data = [{"results": [{"name_fr": "Bulbizarre"}, {"name_fr": "Salamèche"}, {"name_fr": "Carapuce"}]}]
    # « Pikachu » est cité mais absent des données : le modèle l'a ajouté de mémoire.
    answer = "Les starters sont Bulbizarre, Salamèche et Carapuce, comme Pikachu."
    assert [name for _, name in _answer_images(answer, data, URLS)] == ["Bulbizarre", "Salamèche", "Carapuce"]


def test_images_are_capped_and_follow_citation_order():
    from pokemon_rag.web.app import MAX_IMAGES
    names = ["Carapuce", "Salamèche", "Bulbizarre", "Herbizarre", "Abo", "Pikachu", "Mewtwo"]
    data = [{"results": [{"name_fr": n} for n in reversed(names)]}]
    assert [name for _, name in _answer_images(", ".join(names) + ".", data, URLS)] == names[:MAX_IMAGES]


def test_the_longest_name_wins_and_a_name_inside_another_is_not_shown():
    data = [{"rows": [{"name_fr": "Raichu d’Alola"}]}, {"pokemon": "Raichu"}, {"results": [{"name_fr": "Mewtwo"}, {"name_fr": "Mew"}]}]
    answer = "Raichu d'Alola est de type Électrik et Psy ; Mewtwo aussi est Psy."
    assert [url for url, _ in _answer_images(answer, data, URLS)] == ["https://img/10100.png", "https://img/150.png"]


def test_a_common_word_is_not_a_pokemon_unless_the_data_has_it():
    data = [{"results": [{"name_fr": "Pikachu"}]}]
    assert [name for _, name in _answer_images("Pikachu ne craint pas un abo.", data, URLS)] == ["Pikachu"]


def test_no_image_without_data():
    assert _answer_images("Aucun outil n'a renvoyé de résultat exploitable.", [], URLS) == []



def test_the_images_follow_the_data_and_skip_abstentions(monkeypatch):
    from pokemon_rag.agent.context_budget import TOOL_FAILURE_ABSTENTION
    from pokemon_rag.web import app
    monkeypatch.setattr(app, "pokemon_image_urls", lambda: URLS)
    timing = app.ActivityTiming()
    timing.results[0] = {"results": [{"name_fr": "Bulbizarre"}]}
    timing.measures[0] = {"executed_arguments": {"subgroup": "Starter"}}
    html_block = app._image_html("Le starter est Bulbizarre.", timing)
    assert '<img src="https://img/1.png" alt="Bulbizarre"' in html_block and app.IMAGE_CREDIT in html_block
    assert app._image_html(TOOL_FAILURE_ABSTENTION, timing) == ""
    assert app._image_html("Aucun Pokémon ici.", timing) == ""


def test_a_missing_database_gives_an_answer_without_images(monkeypatch):
    from pokemon_rag.web import app

    def missing():
        raise FileNotFoundError("Base introuvable")
    monkeypatch.setattr(app, "pokemon_image_urls", missing)
    timing = app.ActivityTiming()
    timing.results[0] = {"results": [{"name_fr": "Bulbizarre"}]}
    assert app._image_html("Bulbizarre.", timing) == ""
