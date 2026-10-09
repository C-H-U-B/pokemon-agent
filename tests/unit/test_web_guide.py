"""Onglet « Guide » : contrôle et rendu du fichier du guide, sans interface, sans modèle ni base."""

import json
from html import unescape
from pathlib import Path

import pytest

from pokemon_rag.web.graph import REJECTIONS
from pokemon_rag.web.guide import drawable_names, guide_html, known_failure, load_guide

VALID = """
[[famille]]
titre = "Records"
phrase = "Le plus lourd."
questions = ["Quel est le plus lourd ?", "Quel est le plus grand ?"]
en_cours = ["Quel est le plus grand ?"]

[[indisponible]]
titre = "Un avis"
raison = "Pas d'avis."
questions = ["Qui est le plus beau ?"]
voisine = "Quel est le plus lourd ?"
"""


def write(tmp_path, text):
    path = tmp_path / "guide.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_the_real_guide_loads_and_every_family_offers_an_example():
    guide = load_guide()
    page = guide_html(guide)
    assert page.count('class="guide-example"') == len(guide["famille"]) + sum(
        "voisine" in reason for reason in guide["indisponible"])
    assert "Questions non disponibles" in page


def test_a_family_shows_its_title_and_example_button_and_unfolds_its_description(tmp_path):
    page = guide_html(load_guide(write(tmp_path, VALID)))
    summary, body = page.split("</summary>")[0], page.split("</summary>")[1]
    assert "<span>Records</span>" in summary and 'class="guide-example"' in summary
    # Les questions voyagent dans le bouton, pas à l'écran : le navigateur en tire une.
    assert json.loads(unescape(summary.split('data-questions="')[1].split('"')[0])) == [
        "Quel est le plus lourd ?", "Quel est le plus grand ?"]
    assert "Le plus lourd." in body and "En cours d'amélioration : « Quel est le plus grand ? »" in body


def test_an_unavailable_reason_lists_its_questions_and_offers_the_nearby_one(tmp_path):
    page = guide_html(load_guide(write(tmp_path, VALID))).split("Questions non disponibles")[1]
    assert "<span>Un avis</span>" in page and "Pas d&#x27;avis." in page and "<li>Qui est le plus beau ?</li>" in page
    assert "À la place :" in page and ">Quel est le plus lourd ?</button>" in page


def test_text_from_the_file_is_escaped(tmp_path):
    page = guide_html(load_guide(write(tmp_path, VALID.replace("Records", "<script>x</script>")
                                       .replace("Qui est le plus beau ?", "<img src=x onerror='y'>"))))
    assert "<script>" not in page and "<img" not in page and "&lt;script&gt;" in page


@pytest.mark.parametrize("old, new, named", [
    ('phrase = "Le plus lourd."', "", "famille « Records » : « phrase »"),
    ('raison = "Pas d\'avis."', 'raison = " "', "indisponible « Un avis » : « raison »"),
    ('questions = ["Qui est le plus beau ?"]', "questions = []", "indisponible « Un avis » : « questions »"),
    ('questions = ["Quel est le plus lourd ?", "Quel est le plus grand ?"]\nen_cours = ["Quel est le plus grand ?"]', "",
     "famille « Records » : « questions »"),
    ("Qui est le plus beau ?", "Quel est le plus lourd ?", "question citée deux fois : Quel est le plus lourd ?"),
    ('en_cours = ["Quel est le plus grand ?"]', 'en_cours = ["Autre ?"]', "famille « Records » : « en_cours »"),
    ('voisine = "Quel est le plus lourd ?"', 'voisine = "Autre ?"', "indisponible « Un avis » : « voisine »"),
])
def test_a_malformed_guide_is_refused_with_the_faulty_entry_named(tmp_path, old, new, named):
    assert old in VALID
    with pytest.raises(ValueError, match=named):
        load_guide(write(tmp_path, VALID.replace(old, new)))


REFUSAL = {"name": "pokemon_evolutions", "arguments": {"pokemon": "Évoli"}, "result": {
    "error": "invalid_explicit_constraints", "message": "Plusieurs Pokémon ou formes explicites : précisez une cible unique."}}
OTHER_REFUSAL = {"name": "pokemon_search", "arguments": {}, "result": {
    "error": "invalid_explicit_constraints", "message": "Classification ambiguë ou négative : précisez les filtres."}}


def failed(outcome, *tools):
    return {"question": "Question", "outcome": outcome, "tools": list(tools)}


def test_a_known_failure_is_named_by_the_guard_message_before_the_outcome():
    guide = load_guide()
    # Le même code de refus couvre deux raisons : seul le message les distingue.
    assert known_failure(guide, failed("tool_failure_abstention", REFUSAL)) == "Deux Pokémon dans la même question"
    assert known_failure(guide, failed("budget_abstention", OTHER_REFUSAL)) == "Un critère que la recherche ne connaît pas encore"
    assert known_failure(guide, failed("budget_abstention")) == "Une réponse trop longue à rédiger"
    assert known_failure(guide, failed("double_request_refusal")) == "Deux demandes dans la même question"


def test_an_answer_a_running_question_or_an_unexplained_budget_abstention_names_no_reason():
    guide = load_guide()
    assert known_failure(guide, failed("running", REFUSAL)) is None
    assert known_failure(guide, failed("answered", {"name": "pokemon_types", "arguments": {}, "result": {"rows": []}})) is None
    # Abstention de budget après des refus au message non répertorié : ce n'est pas une réponse trop longue.
    unlisted = {"name": "pokemon_machine_moves", "arguments": {}, "result": {
        "error": "unsupported_search_constraints", "message": "Cet outil ne peut pas conserver les contraintes explicites."}}
    # Abstention faute de résultat, quel que soit le refus ou l'erreur : raison générique. Une abstention de budget
    # après des refus au message non répertorié en est une, pas une réponse trop longue.
    vague = "Une question trop vague ou hors des données"
    assert known_failure(guide, failed("budget_abstention", unlisted)) == vague
    assert known_failure(guide, failed("tool_failure_abstention")) == vague
    assert known_failure(guide, failed("tool_failure_abstention", unlisted)) == vague
    # Ce même refus suivi d'une réponse n'est pas un échec : le modèle a changé d'outil.
    assert known_failure(guide, failed("answered", unlisted, {"name": "pokemon_moves", "arguments": {}, "result": {}})) is None


def test_a_question_outside_the_tool_is_signalled_even_when_the_model_answered():
    guide = load_guide()
    superlative = {"name": "pokemon_search", "arguments": {}, "result": {
        "error": "invalid_explicit_constraints", "message": "Superlatif non reconnu : précisez la statistique ou une quantité."}}
    retried = {"name": "pokemon_search", "arguments": {"sort_by": "attack"}, "result": {"results": [{"name_fr": "Darumacho"}]}}
    # Le refus vient de la question ; la réponse vient d'un second appel sans la contrainte.
    assert known_failure(guide, failed("answered", superlative, retried)) == "Un avis, un conseil ou une stratégie"
    # Réponse écrite sans aucun outil : rien ne la vérifie.
    assert known_failure(guide, failed("answered")) == "Une réponse donnée de mémoire"
    assert known_failure(guide, failed("list_fidelity_replacement")) is None


def test_the_noticed_reason_is_marked_and_the_others_are_not(tmp_path):
    guide = load_guide(write(tmp_path, VALID))
    page = guide_html(guide, "Un avis")
    assert 'class="guide-block unavailable noticed" data-key="Un avis"' in page and "Votre dernière question" in page
    assert "noticed" not in guide_html(guide) and "noticed" not in guide_html(guide, "Raison inconnue")


def test_every_failed_outcome_of_the_interface_is_signalled_by_the_real_guide():
    guide = load_guide()
    # Chaque issue qui mène au rejet dans le graphe a sa raison : aucune erreur ne reste sans notification.
    assert all(known_failure(guide, failed("answered" if outcome == "unverified" else outcome)) for outcome in REJECTIONS)
    assert known_failure(guide, failed("error")) == known_failure(guide, failed("no_final_response")) == "Un incident technique"
    assert known_failure(guide, failed("question_too_long")) == "Une question trop longue"
    assert "<ul>" not in guide_html(guide).split("Un incident technique")[1].split("</details>")[0]


def test_every_message_and_outcome_named_by_the_real_guide_still_exists():
    source = (Path(__file__).resolve().parents[2] / "src/pokemon_rag/constraints/query_constraints.py").read_text(encoding="utf-8")
    reasons = load_guide()["indisponible"]
    messages = [message for reason in reasons for message in reason.get("messages", [])]
    assert messages and all(f'ValueError("{message}' in source for message in messages)
    assert all(issue in REJECTIONS for reason in reasons for issue in reason.get("issues", []))


WITH_TEMPLATE = VALID.replace('en_cours = ["Quel est le plus grand ?"]', 'modeles = ["Quels sont les types {de_pokemon} ?"]')


def test_a_family_template_travels_in_its_button_and_names_are_sent_only_when_given(tmp_path):
    guide = load_guide(write(tmp_path, WITH_TEMPLATE))
    page = guide_html(guide, names=["Arcanin", "Pikachu"])
    button = page.split("</summary>")[0]
    assert json.loads(unescape(button.split('data-templates="')[1].split('"')[0])) == ["Quels sont les types {de_pokemon} ?"]
    assert json.loads(unescape(page.split('data-names="')[1].split('"')[0])) == ["Arcanin", "Pikachu"]
    # Sans noms, la page ne les répète pas : le navigateur garde ceux de l'ouverture.
    assert "data-names" not in guide_html(guide) and "data-templates" not in guide_html(load_guide(write(tmp_path, VALID)))


def test_drawable_names_are_the_species_of_the_catalogue_without_the_excluded_ones(tmp_path):
    catalogue = [("pikachu", "Pikachu", None), ("raichu-alola", "Raichu", "alola"), ("raichu", "Raichu", None),
                 ("type-0", "Type:0", None)]
    guide = load_guide(write(tmp_path, 'noms_exclus = ["Type:0"]\n' + WITH_TEMPLATE))
    assert drawable_names(guide, catalogue) == ["Pikachu", "Raichu"]


def test_a_template_without_a_name_placeholder_is_refused(tmp_path):
    with pytest.raises(ValueError, match="famille « Records » : un modèle doit contenir"):
        load_guide(write(tmp_path, WITH_TEMPLATE.replace("{de_pokemon}", "Pikachu")))
