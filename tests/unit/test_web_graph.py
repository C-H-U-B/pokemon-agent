"""Graphe du parcours d'une question : cohérence de la liste des nœuds, angle d'arrivée des tubes, adresses des icônes."""
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
