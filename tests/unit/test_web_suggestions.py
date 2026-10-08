"""Boutons de questions suggérées : liste par public, question suivante, progression par navigateur."""
from pokemon_rag.web import app


def test_the_app_opens_on_the_first_novice_question_and_each_list_is_loaded():
    assert app.FIRST_QUESTION == "Quels sont les 5 Pokémon les plus lourds ?"
    assert all(len(questions) >= 5 for questions in app.SUGGESTIONS.values())


def test_each_button_moves_to_the_next_question_of_its_list_and_wraps_around():
    state = app.WebSession()
    novices = app.SUGGESTIONS["decouvrir"]
    # La première question est déjà affichée au lancement : le bouton passe à la deuxième.
    asked = [app._next_suggestion("decouvrir", state)[0] for _ in range(len(novices))]
    assert asked == novices[1:] + novices[:1]


def test_lists_and_browsers_progress_independently():
    first, second = app.WebSession(), app.WebSession()
    app._next_suggestion("experts", first)
    assert app._next_suggestion("experts", first)[0] == app.SUGGESTIONS["experts"][1]
    assert app._next_suggestion("experts", second)[0] == app.SUGGESTIONS["experts"][0]
    assert app._next_suggestion("connaisseurs", first)[0] == app.SUGGESTIONS["connaisseurs"][0]


def test_the_opening_example_answers_the_first_question_without_any_model_call(monkeypatch):
    question, answer = app._opening_example()
    assert (question["role"], question["content"]) == ("user", app.FIRST_QUESTION)
    assert answer["role"] == "assistant" and answer["content"].count("<img ") == 5
    assert "Cosmovum" in answer["content"]
    # Liste modifiée sans que l'exemple suive : rien n'est affiché plutôt qu'un échange faux.
    monkeypatch.setattr(app, "FIRST_QUESTION", "Une autre question ?")
    assert app._opening_example() == []
