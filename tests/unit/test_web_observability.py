"""Blocs de l'onglet « Observabilité » : rendu d'une trace Web, sans interface, sans modèle ni base."""

from html import escape

from pokemon_rag.web.graph import LOADING_NOTICE, REJECTIONS, WRITTEN
from pokemon_rag.web.observability import EMPTY, observability_html


def trace(*tools, outcome="answered", **fields):
    return {"question": "Quels sont les Pokémon les plus lourds ?", "outcome": outcome, "tools": list(tools), **fields}


SEARCH = {"name": "pokemon_search", "arguments": {"sort_by": "weight", "limit": 5},
          "proposed_arguments": {"sort_by": "weight", "page": 2}, "seconds": 0.31, "execution_time": 0.02,
          "raw_bytes": 8412, "result": {"operation": "search_pokemon", "context_compacted": True,
                                        "results": [{"name_fr": "Cosmovum"}]}}
REFUSED = {"name": "pokemon_level_up_moves", "arguments": {"pokemon": "Carabaffe"}, "seconds": 0.06,
           "result": {"error": "unsupported_move_constraints", "required_arguments": {"move_type": "water"},
                      "message": "Cet outil ne peut pas conserver les contraintes explicites."}}
FAILED = {"name": "pokemon_moves", "arguments": {"pokemon": "Léviator", "form": "default"}, "seconds": 0.4,
          "raw_bytes": 120, "result": {"error": "mcp_tool_error", "message":
                                       "L'outil a signalé une erreur ; aucun fait ne peut en être déduit. Détail : "
                                       "Error executing tool: unable to open C:\\data\\pokemon.db"}}


def test_a_corrected_call_shows_the_four_steps_with_the_proposal_the_change_and_both_sizes():
    blocks = observability_html(trace(SEARCH), "q1")
    assert "Appel 1 · Recherche de Pokémon" in blocks and "<code>pokemon_search</code>" in blocks
    assert "sort_by = weight, page = 2" in blocks                      # proposition du modèle
    assert "ajouté ou modifié : limit = 5 — retiré : page" in blocks   # guard
    assert "Outil appelé : pokemon_search" in blocks and "pokemon_search a reçu : sort_by = weight, limit = 5" in blocks and "Requête SQL : 20 ms" in blocks
    assert "Retour de l&#x27;outil : 8 412 octets" in blocks
    assert "Appel transmis à l&#x27;outil par le guard" in blocks and '<details data-key="q1:0:guard">' in blocks
    assert "réduit aux champs utiles" in blocks and "Transmis au modèle : 90 octets" in blocks
    # Le retour transmis est entier, replié, et sa clé distingue la question et l'appel.
    assert '<details data-key="q1:0:result">' in blocks and "&quot;name_fr&quot;: &quot;Cosmovum&quot;" in blocks
    assert escape(WRITTEN["answered"]) in blocks


def test_a_refused_call_stops_at_the_guard_with_its_message_and_the_required_arguments():
    blocks = observability_html(trace(REFUSED, outcome="tool_failure_abstention"))
    assert "refuse l&#x27;appel" in blocks and "Cet outil ne peut pas conserver" in blocks
    assert "Arguments exigés : move_type = water" in blocks
    # Le texte exact du modèle et celui du guard se déplient : l'appel émis, le refus rendu.
    assert "Appel émis par le modèle" in blocks and "&quot;name&quot;: &quot;pokemon_level_up_moves&quot;" in blocks
    assert "Refus rendu au modèle par le guard" in blocks
    assert "&quot;error&quot;: &quot;unsupported_move_constraints&quot;" in blocks
    assert "Outil appelé : pokemon_level_up_moves" in blocks and "a reçu" not in blocks and "Retour transmis" not in blocks
    assert escape(REJECTIONS["tool_failure_abstention"]) in blocks


def test_a_tool_error_hides_the_exception_text_from_the_public_page():
    blocks = observability_html(trace(FAILED, outcome="tool_failure_abstention"))
    assert "L&#x27;outil a signalé une erreur" in blocks
    assert "Détail" not in blocks and "pokemon.db" not in blocks and "Retour transmis" not in blocks


def test_text_from_the_question_the_model_and_the_tools_cannot_inject_markup():
    hostile = "<script>alert(1)</script>"
    tool = {"name": hostile, "arguments": {hostile: hostile}, "seconds": 0.1, "result": {"rows": [hostile]}}
    refused = {**REFUSED, "result": {"error": hostile, "message": hostile, "required_arguments": {hostile: hostile}}}
    blocks = observability_html({"question": hostile, "outcome": "answered", "tools": [tool, refused]}, hostile)
    assert "<script" not in blocks and blocks.count("&lt;script&gt;") >= 8


def test_an_older_trace_without_the_raw_size_says_so_and_a_truncated_result_is_named():
    older = {key: value for key, value in SEARCH.items() if key not in ("raw_bytes", "proposed_arguments")}
    older["result"] = {"context_truncated": True, "rows": []}
    blocks = observability_html(trace(older))
    assert "non mesurée" in blocks and "tronque" in blocks and "Appel exécuté sans changement." in blocks
    too_large = {**SEARCH, "result": {"error": "tool_result_too_large", "message": "Résultat trop volumineux."}}
    blocks = observability_html(trace(too_large, outcome="budget_abstention"))
    assert "ne transmet rien" in blocks and "Retour transmis" not in blocks and escape(REJECTIONS["budget_abstention"]) in blocks


def test_a_running_question_shows_no_changing_duration_and_no_answer_block():
    pending = {"name": "pokemon_rag_search", "arguments": {"question": "Décris Ronflex"}, "start": 1.0,
               "seconds": None, "result": None}
    first = observability_html(trace(pending, outcome="running", seconds={"total": 1.0}), "q")
    later = observability_html(trace(pending, outcome="running", seconds={"total": 9.0}), "q")
    # Rendu identique d'un rafraîchissement à l'autre : il n'est donc pas renvoyé au navigateur.
    assert first == later and "Réponse en cours" in first and "en cours…" in first
    assert "<h4>Réponse</h4>" not in first and LOADING_NOTICE.split(" :")[0] not in first
    assert "Première recherche" in observability_html(trace(pending, outcome="running", loading=True))


def test_questions_refused_before_any_call_and_answers_written_from_memory_are_marked_as_rejections():
    assert observability_html(None) == EMPTY
    for outcome in ("question_too_long", "double_request_refusal", "error"):
        blocks = observability_html({"question": "Q", "outcome": outcome})
        assert escape(REJECTIONS[outcome]) in blocks and 'class="obs-block refused"' in blocks
    assert escape(REJECTIONS["unverified"]) in observability_html({"question": "Q", "outcome": "answered", "tools": []})
    replaced = observability_html(trace(SEARCH, outcome="list_fidelity_replacement"))
    assert escape(WRITTEN["list_fidelity_replacement"]) in replaced and 'class="obs-block refused"' not in replaced
