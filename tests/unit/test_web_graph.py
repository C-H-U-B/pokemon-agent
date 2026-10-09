"""Graphe du parcours d'une question : cohérence de la liste des nœuds, angle d'arrivée des tubes, adresses des icônes."""
import json
from xml.dom import minidom

from pokemon_rag.web import graph


def test_every_link_joins_two_declared_nodes_and_the_drawing_is_well_formed():
    ids = [node["id"] for node in graph.NODES]
    assert len(ids) == len(set(ids))
    assert all(source in ids and target in ids for source, target, *_ in graph.EDGES)
    template = graph.graph_template()
    drawing = minidom.parseString(template[:template.index("</svg>") + len("</svg>")])
    drawn = [group.getAttribute("data-id") for group in drawing.getElementsByTagName("g") if group.getAttribute("data-id")]
    assert drawn == ids


def test_a_node_added_to_the_list_is_drawn_without_any_other_change(monkeypatch):
    added = {"id": "grounding", "label": "Contrôle de fidélité", "x": 320, "y": 360, "tint": "#e600b0", "role": "Vérifie."}
    monkeypatch.setattr(graph, "NODES", graph.NODES + [added])
    monkeypatch.setattr(graph, "EDGES", graph.EDGES + [("redige", "grounding")])
    template = graph.graph_template()
    assert 'data-id="grounding"' in template and 'data-to="grounding" data-from="redige"' in template


def test_the_arrival_angle_is_read_where_the_tube_reaches_the_node_not_at_its_tip():
    straight_down = ((0, 0), (0, 50), (0, 50), (0, 100))
    from_the_left = ((0, 0), (50, 0), (50, 0), (100, 0))
    # Tube qui part en haut à gauche et finit vertical sous la tête : l'arrivée visible reste en diagonale.
    diagonal = ((210, 142), (210, 166), (290, 166), (290, 190))
    assert graph._arrival_angle(straight_down) == -90
    assert graph._arrival_angle(from_the_left) == 180
    assert -150 < graph._arrival_angle(diagonal) < -110


def test_icon_addresses_follow_the_wiki_folder_rule_and_encode_accents():
    # Adresses relevées dans l'API de Poképédia le 9 octobre 2026.
    assert graph.shuffle_icon(480) == "https://www.pokepedia.fr/images/8/8c/Sprite_0480_Sh.png"
    assert graph.shuffle_icon(25, "Agacé") == "https://www.pokepedia.fr/images/f/f6/Sprite_0025_Agac%C3%A9_Sh.png"
    assert graph.random_pikachu().startswith("https://www.pokepedia.fr/images/")


def _tool(name="pokemon_search", start=1.0, **fields):
    return {"name": name, "arguments": {"limit": 5}, "start": start, "seconds": 0.1, "execution_time": 0.02,
            "result": {"results": [{"name_fr": "Cosmovum"}], "context_compacted": True}, **fields}


def _refused(start=1.0):
    return _tool("pokemon_types", start, execution_time=None,
                 result={"error": "unsupported_named_pokemon_constraint", "message": "Se lit dans la fiche."})


def _failed(start=1.0):
    return _tool("pokemon_machine_moves", start, execution_time=None,
                 result={"error": "mcp_tool_error", "message": "Forme 'default' introuvable."})


def _search(start=1.0):
    return _tool("pokemon_rag_search", start, execution_time=None, passages=1, result={"results": [{"text": "…"}]},
                 timings={"vector": 0.3, "bm25": 0.07, "rrf": 0.0002, "reranker": 1.57, "total": 2.15})


def _path(outcome, *tools):
    return graph.graph_path({"question": "Quels sont les 5 Pokémon les plus lourds ?", "outcome": outcome,
                             "tools": list(tools)})


def _nodes(path):
    return [node for _, node, _ in path]


def test_an_answered_question_follows_declared_tubes_from_the_question_to_the_answer():
    corrected = _tool(arguments={"limit": 5, "offset": 0}, proposed_arguments={"limit": 5, "subgroup": "Galar"})
    path = _path("answered", corrected)
    assert _nodes(path) == ["question", "choix", "guard", "mcp", "base", "budget", "redige", "reponse"]
    links = {(source, target) for source, target, *_ in graph.EDGES}
    assert all((source, node) in links for source, node, _ in path[1:])
    said = dict((node, text) for _, node, text in path)
    assert "Recherche de Pokémon" in said["choix"] and "subgroup = Galar" in said["choix"]  # proposition du modèle
    assert "offset = 0" in said["guard"] and "retiré : subgroup" in said["guard"]
    assert "20 ms" in said["base"] and "1 ligne" in said["base"]


def test_a_documentary_search_walks_its_four_steps_with_their_durations():
    path = _path("answered", _search())
    assert _nodes(path)[3:10] == ["mcp", "pokepedia", "vector", "bm25", "rrf", "reranker", "budget"]
    assert ("bm25", "rrf", "0.00 s") in path and ("rrf", "reranker", "1.57 s") in path


def test_a_refused_or_failed_call_returns_to_the_model_without_reaching_the_rejection():
    for failed, node in ((_refused(), "guard"), (_failed(), "mcp")):
        path = _path("answered", failed, _tool(start=2.0))
        assert (node, "choix") in [(source, target) for source, target, _ in path]
        assert "rejet" not in _nodes(path) and _nodes(path)[-1] == "reponse"
    assert "Se lit dans la fiche." in _path("answered", _refused(), _tool(start=2.0))[2][2]


def test_every_outcome_without_an_answer_ends_in_the_rejection_from_the_step_that_decided_it():
    endings = [
        (("question_too_long",), "question"), (("double_request_refusal",), "question"),
        (("budget_abstention", _tool()), "budget"), (("budget_abstention", _refused()), "guard"),
        (("budget_abstention", _failed()), "mcp"),
        (("tool_failure_abstention", _failed()), "choix"), (("tool_failure_abstention",), "choix"),
        (("tool_failure_abstention", _search()), "redige"),
        (("no_final_response", _tool()), "redige"), (("error",), "choix"), (("error", _tool()), "redige"),
        (("answered",), "choix"),  # réponse écrite sans aucun outil : non vérifiée
    ]
    links = {(source, target) for source, target, *_ in graph.EDGES}
    for (outcome, *tools), origin in endings:
        path = _path(outcome, *tools)
        assert path[-1][:2] == (origin, "rejet"), outcome
        assert all((source, node) in links for source, node, _ in path[1:]), outcome
        assert "reponse" not in _nodes(path)


def test_calls_requested_in_the_same_turn_count_as_one_passage_through_the_model():
    path = _path("answered", _tool(), _tool("pokemon_evolutions"))
    assert _nodes(path).count("choix") == 1 and _nodes(path).count("guard") == 2
    assert "Évolutions" in path[1][2]
    assert _nodes(_path("answered", _tool(), _tool(start=2.0))).count("choix") == 2


def test_a_running_question_stops_at_the_step_in_progress():
    waiting = _path("running", _tool(seconds=None, result=None))
    assert _nodes(waiting) == ["question", "choix", "guard", "mcp"]
    assert _nodes(_path("running")) == ["question", "choix"]
    # Résultat reçu : le parcours déjà affiché reste le début du nouveau, le navigateur n'a qu'à continuer.
    assert _nodes(_path("running", _tool()))[:4] == _nodes(waiting)


def test_the_value_sent_to_the_browser_is_the_ordered_path_with_its_question():
    path = _path("answered", _refused(), _tool(start=2.0))
    sent = json.loads(graph.graph_value(path, question_id="q1", running=True, user_icon="pikachu"))
    assert [tuple(step) for step in sent["path"]] == path and sent["id"] == "q1" and sent["running"] is True
    assert sent["user_icon"] == "pikachu" and _nodes(path).count("guard") == 2
    # Têtes du rejet et du chargement : les mêmes tout au long d'une question, tirées de nouveau à la suivante.
    again = json.loads(graph.graph_value(path[:2], question_id="q1"))
    assert (again["reject_icon"], again["loading_icon"]) == (sent["reject_icon"], sent["loading_icon"])
    draws = [json.loads(graph.graph_value([], question_id=f"q{number}")) for number in range(300)]
    for key, icons in (("reject_icon", graph.REJECT_ICONS), ("loading_icon", graph.LOADING_ICONS)):
        counts = [sum(draw[key] == icon for draw in draws) for icon in icons]
        assert sum(counts) == 300 and min(counts) > 60, counts   # une chance sur trois chacune


def test_the_loading_node_is_on_the_path_only_while_the_pending_search_loads_the_base():
    waiting = {"question": "Décris Ronflex", "outcome": "running",
               "tools": [_tool("pokemon_rag_search", seconds=None, result=None)]}
    assert "chargement" not in _nodes(graph.graph_path(waiting))
    loading = graph.graph_path({**waiting, "loading": True})
    assert loading[-1][:2] == ("mcp", "chargement") and ("mcp", "chargement") in {edge[:2] for edge in graph.EDGES}
    # Résultat reçu : le parcours repart du serveur d'outils, sans le chargement.
    assert "chargement" not in _nodes(_path("answered", _search()))
    assert 'class="node dynamic plain transient" data-id="chargement"' in graph.graph_template()
