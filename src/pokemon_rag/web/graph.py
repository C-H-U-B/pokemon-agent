"""Graphe pédagogique du parcours d'une question : dessin, styles et comportement dans le navigateur.

Le graphe est un SVG affiché par un `gr.HTML`. Python n'envoie que le parcours en JSON (`graph_value` : passages
dans l'ordre, question en cours ou non, icônes) ; le navigateur le déroule pas à pas, et le survol, l'épinglage
et les animations y vivent. Ajouter un module revient à
ajouter une entrée dans `NODES` et ses liens dans `EDGES` : le dessin, l'angle d'arrivée du liquide et le
comportement en découlent.
"""
import hashlib
import json
import math
import random
from html import escape
from urllib.parse import quote


def shuffle_icon(number: int, variant: str = "") -> str:
    """Adresse de l'icône Pokémon Shuffle d'un numéro de Pokédex, liée depuis Poképédia.

    Le dossier d'un fichier MediaWiki se déduit du MD5 de son nom. Tous les Pokémon n'ont pas d'icône Shuffle :
    l'adresse existe alors sans image, et le dessin garde un rond simple.
    """
    name = f"Sprite_{number:04d}_{variant}_Sh.png" if variant else f"Sprite_{number:04d}_Sh.png"
    digest = hashlib.md5(name.encode()).hexdigest()
    return f"https://www.pokepedia.fr/images/{digest[0]}/{digest[:2]}/{quote(name)}"


# L'utilisateur est un Pikachu tiré au hasard parmi les 40 variantes de Pokémon Shuffle hébergées par Poképédia
# (relevées dans son API le 9 octobre 2026 ; "" est le Pikachu ordinaire).
PIKACHU_VARIANTS = (
    "Agacé", "Amoureux", "Assoupi", "Casquette_Originale", "Casquette_d'Alola", "Casquette_d'Unys",
    "Casquette_de_Hoenn", "Casquette_de_Kalos", "Casquette_de_Sinnoh", "Clin_d'œil", "Confus", "Content",
    "Costume_(Dracaufeu)", "Costume_(Ho-Oh)", "Costume_(Lugia)", "Costume_(Léviator)",
    "Costume_(Léviator_chromatique)", "Costume_(Magicarpe)", "Costume_(Rayquaza)", "Costume_(Rayquaza_chromatique)",
    "Déguisé", "Fêtes", "Heureux", "Impérial", "Kimono", "Motivé", "", "Surpris", "Événement_(Artiste)",
    "Événement_(Chef_pâtissier)", "Événement_(Cueillette_de_champignons)", "Événement_(Danse_du_lion)",
    "Événement_(Diplômé)", "Événement_(Festival_d'été)", "Événement_(Fin_d'année)", "Événement_(Jour_des_enfants)",
    "Événement_(Kotatsu)", "Événement_(Promenade_à_la_plage)", "Événement_(Saison_des_pluies)",
    "Événement_(Uniforme)",
)


def random_pikachu() -> str:
    return shuffle_icon(25, random.choice(PIKACHU_VARIANTS))


QUEULORIOR, EXAGIDE, DRACOLOSSE = shuffle_icon(235), shuffle_icon(681), shuffle_icon(149)
METALOSSE, CREHELF, MIAMIASME, RAMOLOSS = shuffle_icon(376), shuffle_icon(480), shuffle_icon(568), shuffle_icon(79)
# Le liquide fonce à mesure qu'il est transformé, de la question à la réponse ; un rejet le ternit.
PALE, ROSE, PINK, MAGENTA, DEEP, SPOILED = "#ffb3ec", "#ff7ddf", "#ff3fcf", "#e600b0", "#a3007d", "#6b7280"
# Les deux branches forment un anneau entre le serveur d'outils et le budget : Métalosse au milieu de la sienne,
# Poképédia et ses quatre étapes le long de l'autre. Leurs positions sont des points de cette ellipse.
RING = {"x": 210, "y": 231, "rx": 100, "ry": 89}
# Ajouter un module = une entrée ici (position, teinte, icône éventuelle) et ses liens dans EDGES.
NODES = [
    {"id": "question", "label": "Votre question", "x": 210, "y": 14, "tint": PALE, "icon": "user_icon",
     "role": "Le texte que vous avez envoyé, tel quel."},
    {"id": "choix", "label": "Modèle · choisit l'outil", "x": 210, "y": 54, "tint": ROSE, "icon": QUEULORIOR,
     "role": "Le modèle de langage lit la question et décide quel outil appeler, avec quels réglages. Il ne calcule rien lui-même."},
    {"id": "guard", "label": "Guard · vérifie", "x": 210, "y": 98, "tint": ROSE, "icon": EXAGIDE,
     "role": "Un contrôle écrit en code compare l'appel du modèle à votre question : il remet une contrainte oubliée ou refuse l'appel."},
    {"id": "rejet", "label": "Rejet", "x": 420, "y": 108, "tint": SPOILED, "icon": MIAMIASME, "transient": True,
     "role": "La question ne peut pas être traitée : l'outil le dit au lieu d'inventer une réponse."},
    # En miroir du rejet. Transitoires tous les deux : dessinés seulement quand le parcours y passe, avec leurs tubes.
    {"id": "chargement", "label": "Chargement", "x": 0, "y": 108, "tint": PINK, "icon": RAMOLOSS, "label_left": True,
     "transient": True, "role": "La base documentaire se charge en mémoire : cela n'arrive qu'après un démarrage."},
    {"id": "mcp", "label": "Serveur d'outils", "x": 210, "y": 142, "tint": PINK, "icon": DRACOLOSSE,
     "role": "Le serveur qui exécute l'outil demandé (protocole MCP) et rapporte son résultat."},
    {"id": "base", "label": "Base de données", "x": 110, "y": 231, "tint": PINK, "icon": METALOSSE,
     "role": "Les données chiffrées des Pokémon. Tris, filtres et comptages sont faits ici, en SQL."},
    {"id": "pokepedia", "label": "Poképédia", "x": 297, "y": 187, "tint": PINK, "icon": CREHELF,
     "role": "Les textes de l'encyclopédie Poképédia, découpés en passages."},
    {"id": "vector", "label": "recherche par le sens", "x": 309, "y": 222, "tint": PINK, "sub": True,
     "role": "Trouve les passages dont le sens est proche de la question."},
    {"id": "bm25", "label": "recherche par les mots", "x": 308, "y": 247, "tint": PINK, "sub": True,
     "role": "Trouve les passages qui contiennent les mots de la question."},
    {"id": "rrf", "label": "fusion", "x": 300, "y": 270, "tint": PINK, "sub": True, "role": "Réunit les deux listes en une seule."},
    {"id": "reranker", "label": "reclassement", "x": 284, "y": 291, "tint": PINK, "sub": True,
     "role": "Un second modèle relit les meilleurs passages et garde les plus pertinents."},
    {"id": "budget", "label": "Budget de contexte", "x": 210, "y": 320, "tint": MAGENTA,
     "role": "Réduit le résultat à ce que le modèle peut lire sans dépasser sa mémoire de travail."},
    {"id": "redige", "label": "Modèle · rédige", "x": 210, "y": 360, "tint": MAGENTA, "icon": QUEULORIOR,
     "role": "Le modèle écrit la réponse en français à partir des résultats reçus."},
    {"id": "reponse", "label": "Réponse", "x": 210, "y": 404, "tint": DEEP, "icon": "answer_icon",
     "role": "Le texte affiché dans la conversation."},
]
EDGES = [("question", "choix"), ("choix", "guard"), ("guard", "mcp"), ("mcp", "base", "ring"),
         ("mcp", "pokepedia", "ring"), ("pokepedia", "vector", "ring"), ("vector", "bm25", "ring"),
         ("bm25", "rrf", "ring"), ("rrf", "reranker", "ring"), ("base", "budget", "ring"),
         ("reranker", "budget", "ring"), ("budget", "redige"), ("redige", "reponse"),
         ("budget", "choix", "loop", "hidden"),
         # Toute étape peut échouer : ces tubes vers le rejet n'apparaissent que lorsqu'ils servent.
         ("question", "rejet", "over", "hidden"), ("choix", "rejet", "side", "hidden"),
         ("guard", "rejet", "side", "hidden"), ("mcp", "rejet", "side", "hidden"),
         ("budget", "rejet", "side", "hidden"), ("redige", "rejet", "side", "hidden"),
         # Appel refusé ou outil en erreur : la question n'est pas rejetée, le modèle est relancé.
         ("guard", "choix", "loop", "hidden"), ("mcp", "choix", "loop", "hidden"),
         ("mcp", "chargement", "left", "hidden")]


TOOL_LABELS = {
    "pokemon_search": "Recherche de Pokémon",
    "pokemon_moves": "Movepool filtré",
    "pokemon_types": "Types du Pokémon",
    "pokemon_pokedex_identity": "Identité Pokédex",
    "pokemon_evolutions": "Évolutions",
    "pokemon_level_up_moves": "Capacités par niveau",
    "pokemon_move_learning_methods": "Méthodes d'apprentissage",
    "pokemon_machine_moves": "CT et CS",
    "pokemon_signature_moves": "Capacités signature",
    "pokemon_base_stats": "Statistiques de base",
    "pokemon_particularities": "Talents et particularités",
    "pokemon_rag_search": "Recherche documentaire Poképédia",
}
SEARCH_STEPS = ("vector", "bm25", "rrf", "reranker")
# Erreurs nées après le guard ; tout autre code d'erreur dans un retour d'outil est un refus du guard.
TOOL_ERRORS = ("mcp_tool_error", "tool_result_too_large")
REJECTIONS = {
    "question_too_long": "Question trop longue : elle n'est pas envoyée au modèle.",
    "double_request_refusal": "La question demande à la fois une description et un fait précis : elle est refusée "
                              "avant tout appel au modèle.",
    "budget_abstention": "Limites de traitement atteintes (trop d'appels au modèle ou trop de texte à lui faire "
                         "lire) : l'agent s'abstient.",
    "tool_failure_abstention": "Aucun outil n'a fourni de résultat exploitable : le texte du modèle est remplacé "
                               "par une abstention.",
    "no_final_response": "Le modèle n'a rendu aucun texte.",
    "error": "Erreur technique pendant cette étape.",
    "unverified": "Réponse écrite sans consulter les données : elle n'est pas vérifiée.",
}
WRITTEN = {
    "answered": "Réponse rédigée à partir des résultats reçus.",
    "list_fidelity_replacement": "La réponse du modèle omettait ou niait une ligne de la liste : elle est remplacée "
                                 "par la liste tirée des données.",
}
LOADING_NOTICE = ("Première recherche depuis le démarrage : la base documentaire se charge (jusqu'à une minute "
                  "et demie).")


def _arguments(arguments: dict) -> str:
    return ", ".join(f"{key} = {value}" for key, value in arguments.items()) or "aucun réglage"


def guard_correction(tool: dict) -> str:
    """Ce que le guard a changé à la proposition du modèle ; chaîne vide s'il n'a rien ajouté ni retiré."""
    proposed = tool["proposed_arguments"]
    changed = {key: value for key, value in tool["arguments"].items() if proposed.get(key) != value}
    dropped = [key for key in proposed if key not in tool["arguments"]]
    return ((f" — ajouté ou modifié : {_arguments(changed)}" if changed else "")
            + (f" — retiré : {', '.join(dropped)}" if dropped else ""))


def graph_path(trace: dict) -> list[tuple[str, str, str]]:
    """Parcours d'une trace Web : un triplet (nœud de départ, nœud atteint, phrase) par passage, dans l'ordre.

    `trace` a la forme de `_web_trace` ; `outcome` vaut "running" tant que la question est en cours (avec
    `loading` quand l'outil en attente charge la base documentaire), et
    "question_too_long" pour une question refusée avant tout traitement. Le parcours ne suit que des faits
    de la trace : le guard est jugé sur le retour de l'outil, les sous-étapes de recherche sur leurs durées.
    """
    outcome, tools = trace["outcome"], trace.get("tools") or []
    path = [("", "question", trace["question"])]
    if outcome in ("question_too_long", "double_request_refusal"):
        return path + [("question", "rejet", REJECTIONS[outcome])]
    at, pending = "question", False
    for index, tool in enumerate(tools):
        name, start = tool["name"], tool.get("start")
        result = tool["result"] if isinstance(tool.get("result"), dict) else {}
        # Appels demandés d'un seul coup : même instant de départ, un seul passage par le modèle.
        if index == 0 or start is None or start != tools[index - 1].get("start"):
            turn = [tool] if start is None else [other for other in tools[index:] if other.get("start") == start]
            path.append((at, "choix", " ; ".join(
                f"Outil demandé : {TOOL_LABELS.get(other['name'], other['name'])} "
                f"({_arguments(other.get('proposed_arguments', other['arguments']))})" for other in turn)))
        if tool.get("seconds") is None and not result:
            path += [("choix", "guard", ""), ("guard", "mcp", "Outil en cours d'exécution…")]
            if trace.get("loading"):
                path.append(("mcp", "chargement", LOADING_NOTICE))
            pending = True
            break
        error = result.get("error")
        if error and error not in TOOL_ERRORS:
            path.append(("choix", "guard", f"Appel refusé : {result.get('message', error)}"))
            at = "guard"
            continue
        if tool.get("proposed_arguments") is None:
            path.append(("choix", "guard", "Appel conforme à la question : exécuté sans changement."))
        else:
            path.append(("choix", "guard", f"Appel corrigé avant exécution{guard_correction(tool)}."))
        if error == "mcp_tool_error":
            path.append(("guard", "mcp", result.get("message", error)))
            at = "mcp"
            continue
        path.append(("guard", "mcp", f"{TOOL_LABELS.get(name, name)} : résultat rendu en {tool.get('seconds') or 0:.2f} s."))
        if name == "pokemon_rag_search":
            timings = tool.get("timings") or {}
            path.append(("mcp", "pokepedia", f"{tool.get('passages', 0)} passage(s) retenu(s)"
                         + (f" en {timings['total']:.2f} s." if "total" in timings else ".")))
            at = "pokepedia"
            for step in SEARCH_STEPS:
                path.append((at, step, f"{timings[step]:.2f} s" if step in timings else ""))
                at = step
        else:
            rows = next((len(result[key]) for key in ("results", "moves", "rows", "evolutions", "methods")
                         if isinstance(result.get(key), list)), None)
            path.append(("mcp", "base", (f"Requête SQL en {tool['execution_time'] * 1000:.0f} ms"
                                         if tool.get("execution_time") is not None else "Requête SQL")
                         + (f" · {rows} ligne(s)." if rows is not None else ".")))
            at = "base"
        path.append((at, "budget",
                     "Résultat trop volumineux : rien n'est transmis au modèle." if error
                     else "Résultat trop long : seule une partie est transmise au modèle, et il en est prévenu."
                     if result.get("context_truncated")
                     else "Résultat réduit aux champs utiles à la question." if result.get("context_compacted")
                     else "Résultat transmis en entier."))
        at = "budget"
    if outcome == "budget_abstention":  # décidée avant de rappeler le modèle
        return path + [(at, "rejet", REJECTIONS[outcome])]
    if not pending:
        # Après un résultat, le modèle rédige ; après un appel refusé ou en erreur, il est relancé pour choisir.
        path.append((at, "redige" if at == "budget" else "choix", ""))
    source, last, _ = path[-1]
    if outcome == "running":
        return path
    if outcome not in ("answered", "list_fidelity_replacement"):
        return path + [(last, "rejet", REJECTIONS.get(outcome, REJECTIONS["error"]))]
    if not tools:
        path[-1] = (source, last, "Aucun outil demandé.")
        return path + [(last, "rejet", REJECTIONS["unverified"])]
    written = WRITTEN[outcome]
    if last == "choix":
        # ponytail: réponse écrite après un dernier appel en échec (0 cas sur 153 réponses tracées) : « rédige »
        # s'allume sans tube ; ajouter un tube choix → rédige si le cas se présente.
        path[-1] = (source, last, "Le modèle n'appelle plus d'outil.")
        path.append(("choix", "redige", written))
    else:
        path[-1] = (source, last, written)
    return path + [("redige", "reponse", "Réponse affichée dans la conversation.")]


def graph_value(path: list[tuple[str, str, str]], *, question_id: str = "", running: bool = False,
                user_icon: str = "", answer_icon: str = "", speed: float = 1.0) -> str:
    """Valeur envoyée au navigateur : le parcours, qu'il déroule un passage après l'autre.

    Chaque passage attend que le nœud précédent soit plein, puis que son tube soit traversé ; `speed` divise
    ces durées (rejeu accéléré de l'exemple d'ouverture).

    `question_id` distingue deux questions : le navigateur reprend au début quand il change, et continue là où
    il en était quand le parcours de la même question s'allonge. `running` : le dernier passage est en cours.
    """
    return json.dumps({"id": question_id, "path": path, "running": running, "speed": speed,
                       "user_icon": user_icon, "answer_icon": answer_icon}, ensure_ascii=False)


def _wave(r: float) -> str:
    """Surface ondulée, plus large que le rond pour glisser d'une période sans montrer son bord."""
    crests = " ".join(f"q {r / 4} -1.6 {r / 2} 0 t {r / 2} 0" for _ in range(6))
    return f"M {-2 * r} {-r} {crests} V {r + 4} H {-2 * r} Z"


def _arrival_angle(curve, radius: float = 20) -> int:
    """Angle (degrés, repère SVG) sous lequel le tube touche le bord du nœud d'arrivée.

    Lu sur le tracé lui-même, là où il entre dans le rayon du nœud : vaut pour tout tube, quelle que soit sa forme.
    La tangente au bout du tracé ne convient pas : un tube qui arrive en diagonale finit vertical sous la tête.
    """
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = curve
    for step in range(60, -1, -1):
        t = step / 60
        x = (1 - t) ** 3 * x0 + 3 * (1 - t) ** 2 * t * x1 + 3 * (1 - t) * t ** 2 * x2 + t ** 3 * x3
        y = (1 - t) ** 3 * y0 + 3 * (1 - t) ** 2 * t * y1 + 3 * (1 - t) * t ** 2 * y2 + t ** 3 * y3
        if math.hypot(x - x3, y - y3) >= radius:
            break
    return round(math.degrees(math.atan2(y - y3, x - x3)))


def graph_template() -> str:
    by_id = {node["id"]: node for node in NODES}
    parts = ['<svg class="graph" viewBox="-110 -12 640 442" role="img" aria-label="Parcours d\'une question">']
    for source, target, *kind in EDGES:
        a, b = by_id[source], by_id[target]
        start, end = (a["x"], a["y"]), (b["x"], b["y"])
        if kind[:1] == ["side"]:  # sortie de côté, sous le libellé de la source
            curve = (start, (a["x"] + 30, b["y"]), (a["x"] + 90, b["y"]), end)
        elif kind[:1] == ["left"]:  # même sortie, de l'autre côté
            curve = (start, (a["x"] - 30, b["y"]), (a["x"] - 90, b["y"]), end)
        elif kind[:1] == ["over"]:  # source bien plus haute : passe entre deux libellés, puis descend sur la cible
            curve = (start, (a["x"] + 90, a["y"] + 16), (b["x"], a["y"] + 6), end)
        elif kind[:1] == ["ring"]:  # arc de l'anneau entre deux de ses points, approché par une courbe de Bézier
            side = 1 if a["x"] + b["x"] > 2 * RING["x"] else -1
            t0, t1 = (math.atan2(abs(point["x"] - RING["x"]) / RING["rx"], (RING["y"] - point["y"]) / RING["ry"])
                      for point in (a, b))
            reach = 4 / 3 * math.tan((t1 - t0) / 4)
            (dx0, dy0), (dx1, dy1) = ((reach * side * RING["rx"] * math.cos(t), reach * RING["ry"] * math.sin(t))
                                      for t in (t0, t1))
            curve = (start, (round(a["x"] + dx0, 1), round(a["y"] + dy0, 1)),
                     (round(b["x"] - dx1, 1), round(b["y"] - dy1, 1)), end)
        elif kind:  # retour vers le modèle pour un nouvel appel d'outil
            # L'arc s'écarte d'autant plus que le retour est long : un retour court reste près de la colonne.
            left = a["x"] - min(200, 40 + 0.6 * abs(a["y"] - b["y"]))
            curve = (start, (left, a["y"]), (left, b["y"]), end)
        else:
            middle = (a["y"] + b["y"]) / 2
            curve = (start, (a["x"], middle), (b["x"], middle), end)
        path = "M {} {} C {} {}, {} {}, {} {}".format(*(value for point in curve for value in point))
        angle = _arrival_angle(curve)
        duration = 1.4 if kind[:1] == ["loop"] else 1.3 if abs(a["y"] - b["y"]) + abs(a["x"] - b["x"]) < 70 else 0.95
        ends = f'data-to="{target}" data-from="{source}" data-dur="{duration}" data-angle="{angle}" d="{path}"'
        parts.append(f'<path class="edge track {" ".join(kind)}" {ends}/>'
                     f'<path class="edge fill" pathLength="100" style="--liquid:{b["tint"]};--dur:{duration}s" {ends}/>')
    for node in NODES:
        icon = node.get("icon")
        dynamic = icon in ("user_icon", "answer_icon")  # tête fournie avec l'état : Pikachu du visiteur, Pokémon de la réponse
        r = 18 if icon and not dynamic else 5.5 if node.get("sub") else 9
        kind = "dynamic plain" if dynamic else "icon" if icon else "sub" if node.get("sub") else "plain"
        kind += " transient" if node.get("transient") else ""
        parts.append(
            f'<g class="node {kind}" data-id="{node["id"]}" data-source="{icon if dynamic else ""}" data-label="{escape(node["label"])}" '
            f'data-role="{escape(node["role"])}" transform="translate({node["x"]} {node["y"]})" '
            f'style="--h:{2 * r}px;--p:{r}px;--liquid:{node["tint"]}" tabindex="0"><g class="vessel">')
        if not icon or dynamic:
            clip = f'clip-{node["id"]}'
            parts.append(f'<g class="round"><clipPath id="{clip}"><circle r="{r}"/></clipPath><circle class="back" r="{r}"/>'
                         f'<g clip-path="url(#{clip})"><g class="liquid shimmer"><path class="wave" d="{_wave(r)}"/></g></g>'
                         f'<circle class="glass" r="{r}"/></g>')
        if icon:
            # La tête est au premier plan, entière. Le liquide l'entoure en suivant sa silhouette : la même image,
            # épaissie et colorée par un filtre. Un masque en deux demi-disques la découvre en partant du point
            # d'arrivée du tube et en faisant le tour par les deux côtés.
            image = ("" if dynamic else f'href="{icon}" ') + 'x="-20" y="-20" width="40" height="40"'
            sweep = '<circle class="sweep" r="16" pathLength="100" fill="none" stroke="#fff" stroke-width="32"'
            parts.append(
                f'<g class="head"><filter id="outline-{node["id"]}" x="-20%" y="-20%" width="140%" height="140%">'
                f'<feMorphology in="SourceAlpha" operator="dilate" radius="2.6" result="shape"/>'
                f'<feFlood flood-color="{node["tint"]}"/><feComposite in2="shape" operator="in"/></filter>'
                f'<mask id="sweep-{node["id"]}" maskUnits="userSpaceOnUse" x="-32" y="-32" width="64" height="64">'
                f'<g class="entry" transform="rotate(-90)">{sweep}/>{sweep} transform="scale(1 -1)"/></g></mask>'
                f'<g class="shimmer"><g mask="url(#sweep-{node["id"]})"><image {image} filter="url(#outline-{node["id"]})"/></g></g>'
                f'<image class="face" {image}/></g>')
        parts.append('</g>')
        r = 18 if icon else r
        if node.get("label_left"):
            parts.append(f'<text x="{-r - 8}" y="4" text-anchor="end">{escape(node["label"])}</text>')
        elif node.get("label_below"):  # à droite, le libellé toucherait une branche voisine
            parts.append(f'<text x="0" y="{r + 17}" text-anchor="middle">{escape(node["label"])}</text>')
        else:
            parts.append(f'<text x="{r + 8}" y="4">{escape(node["label"])}</text>')
        parts.append(f'<g class="badge" transform="translate({r - 2} {-r + 2})"><circle r="6"/>'
                     '<text y="3" text-anchor="middle"></text></g></g>')
    parts.append('</svg><div class="detail"><div class="detail-head"><div class="detail-title"></div>'
                 '<div class="detail-time"></div></div><div class="detail-role"></div>'
                 '<div class="detail-output"></div></div>')
    return "".join(parts)


GRAPH_CSS = """
.graph, .detail { --ink: var(--body-text-color, #1f2933); --muted: var(--body-text-color-subdued, #8a94a3);
    --line: var(--border-color-primary, #e2e6ec); --surface: var(--background-fill-primary, #fff); }
.graph { width: 100%; max-width: 640px; display: block; margin: 0 auto; }
.node.transient { display: none; }
.node.transient.active, .node.transient.done { display: block; }
.edge { fill: none; }
/* Un tube de verre (trait gris large) et le liquide qui avance dedans, de la source vers la cible. */
.edge.track { stroke: var(--line); stroke-width: 7; stroke-linecap: round; }
.edge.track.hidden { opacity: 0; }
.edge.fill { stroke: var(--liquid); stroke-width: 4; stroke-dasharray: 100; stroke-dashoffset: 100; }
/* Le liquide ne part dans un tube qu'une fois le nœud d'où il sort rempli (--wait, la durée de ce remplissage). */
.edge.fill.active { animation: graph-pour var(--dur) linear var(--wait, 0s) forwards; }
.edge.fill.done { stroke-dashoffset: 0; opacity: 0.8; }
.node { cursor: pointer; outline: none; }
.node .back { fill: var(--surface); }
.node .glass { fill: none; stroke: var(--line); stroke-width: 2; transition: stroke 0.3s; }
.node.sub .glass { stroke-width: 1.6; }
/* Remplissage en transitions : interrompue par la fin de l'étape, la descente repart de là où elle en était. */
.node .liquid { fill: var(--liquid); transform: translateY(calc(-1 * (var(--h) + 4px))); }
.node .wave { transform: scaleY(-1); }
/* Durée réelle inconnue d'avance : le liquide descend vite puis ralentit, et finit sa course à la fin de l'étape. */
.node.active .liquid { transform: translateY(calc(var(--h) * -0.18));
                       transition: transform 6s cubic-bezier(0.1, 0.7, 0.2, 1) var(--delay, 1s); }
.node.active .wave { animation: graph-slide 1.4s linear infinite; }
.node.done .liquid, .node.again .liquid { transform: translateY(3px); transition: transform var(--wait, 0.45s) ease-out; }
/* Nœud à icône : sur le contour coloré de la tête, à partir de l'arrivée du tube. Le contour fait le tour complet
   même si l'étape dure : arrêté en chemin, il donnait l'impression d'un blocage. */
.node .sweep { stroke-dasharray: 100; stroke-dashoffset: 100; }
/* 49.5 et non 49 : à valeur d'arrivée égale, « terminé » ne relancerait aucune transition et le contour finirait
   sur cette course lente, pendant que le tube suivant se remplit déjà (mesuré le 9 octobre 2026). */
.node.active .sweep { stroke-dashoffset: 49.5; transition: stroke-dashoffset 6s cubic-bezier(0.1, 0.7, 0.2, 1) var(--delay, 1s); }
.node.done .sweep, .node.again .sweep { stroke-dashoffset: 49; transition: stroke-dashoffset var(--wait, 0.45s) ease-out; }
/* Au repos, le masque laisse un filet au point d'entrée : le contour n'est affiché qu'une fois le nœud atteint. */
.node .head .shimmer { opacity: 0; }
.node.active .head .shimmer, .node.done .head .shimmer { opacity: 1; }
/* Tête connue à la fin seulement : rond simple tant qu'aucune image n'est chargée, tête ensuite. */
.node.dynamic .head, .node.dynamic.has-icon .round { display: none; }
.node.dynamic.has-icon .head { display: block; }
/* La teinte du liquide oscille tant que l'étape travaille. */
.node.active .shimmer { animation: graph-shimmer 0.9s ease-in-out infinite alternate; }
/* Second passage : le nœud reste plein et bat tant que l'étape travaille. */
.node.active.again .vessel { animation: graph-throb 0.7s ease-in-out infinite alternate; }
.node.done .glass, .node.active .glass { stroke: color-mix(in srgb, var(--liquid) 75%, var(--ink)); }
.node text { fill: var(--muted); font-size: 12.5px; font-weight: 500; transition: fill 0.4s;
             paint-order: stroke; stroke: var(--surface); stroke-width: 5px; stroke-linejoin: round; }
.node.sub text { font-size: 11px; font-weight: 400; }
.node.done text, .node.active text { fill: var(--ink); }
.node:hover .face, .node.pinned .face { filter: drop-shadow(0 0 2px var(--ink)); }
.node:hover .glass, .node.pinned .glass { stroke: var(--ink); }
/* Au survol, la tête et son contour grossissent légèrement. */
.node .vessel { transition: transform 0.15s ease-out; }
.node:hover .vessel { transform: scale(1.12); }
.node.pinned .glass { stroke-width: 3; }
.node .badge { display: none; }
.node.multi .badge { display: block; }
.node .badge circle { fill: var(--ink); }
.node .badge text { fill: var(--surface); stroke: none; font-size: 8.5px; font-weight: 700; }
/* Hauteur fixe : un texte long défile dans l'encart, le panneau lui-même ne défile pas. */
.detail { margin: 6px auto 0; max-width: 460px; padding: 10px 14px; border: 1px solid var(--line); border-radius: 14px;
          background: var(--background-fill-secondary, #f8f9fb); height: 118px; box-sizing: border-box; overflow-y: auto; }
.detail-head { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; }
.detail-title { font-weight: 600; color: var(--ink); }
/* Temps écoulé sur l'étape en cours ; chiffres de largeur fixe pour que le texte ne tremble pas. */
.detail-time { color: var(--muted); font-size: 13px; font-variant-numeric: tabular-nums; white-space: nowrap; }
.detail-role { color: var(--muted); font-size: 13px; margin: 2px 0 8px; }
.detail-output { color: var(--ink); font-size: 13.5px; white-space: pre-wrap; }
"""

# Hors du style du composant : Gradio emboîte css_template dans un sélecteur, où @keyframes est ignoré.
GRAPH_KEYFRAMES = """
@keyframes graph-pour { to { stroke-dashoffset: 0; } }
@keyframes graph-slide { to { transform: scaleY(-1) translateX(calc(var(--p) * -1)); } }
@keyframes graph-shimmer { to { filter: brightness(1.3) hue-rotate(-28deg); } }
@keyframes graph-throb { to { transform: scale(1.15); } }
"""

# Le navigateur déroule le parcours reçu et garde le survol et l'épinglage ; Python n'envoie que le parcours.
GRAPH_JS = """
let pinned = null, hovered = null, sent = {}, shown = 0, timer = null, waiting = null, since = 0, pouring = false;
// Secondes pour finir de remplir un nœud quitté, et pour traverser un tube, à la vitesse demandée.
const finish = () => 0.45 / (sent.speed || 1);
const crossing = edge => edge.dataset.dur / (sent.speed || 1);
// Nouveau parcours reçu : reprendre au premier passage qui diffère, puis avancer d'un passage à la fois.
function receive() {
    const next = JSON.parse(props.value || '{}'), path = next.path || [], old = sent.path || [];
    let same = 0;
    while (next.id === sent.id && same < path.length && same < old.length
           && path[same][0] === old[same][0] && path[same][1] === old[same][1]) same++;
    const rewound = same < shown;
    shown = Math.min(shown, same);
    sent = next;
    // Un tube est en train de se remplir et rien n'est à reprendre : la suite attendra son tour.
    if (pouring && !rewound) apply(); else advance();
}
function advance() {
    clearTimeout(timer);
    const path = sent.path || [];
    element.style.setProperty('--wait', finish() + 's');
    pouring = shown < path.length;
    if (pouring) shown++;
    apply();
    if (!pouring) return;
    // Le passage suivant attend que le nœud quitté soit plein, puis que le tube de celui-ci soit traversé.
    // Le dernier passage aussi : il ne passe à « terminé » qu'une fois son tube traversé.
    const [from, to] = path[shown - 1];
    const edge = element.querySelector(`.edge.fill[data-from="${from}"][data-to="${to}"]`);
    timer = setTimeout(advance, (finish() + (edge ? crossing(edge) : 0)) * 1000);
}
// Le dessin prend la hauteur qui reste dans la fenêtre au-dessus de l'encart : ni l'un ni l'autre ne défile.
function fit() {
    const svg = element.querySelector('.graph'), detail = element.querySelector('.detail');
    const box = svg.getBoundingClientRect();
    if (!box.width) return;  // onglet masqué
    // Mesuré par rapport au panneau qui contient le graphe : si l'en-tête de la page bouge, les deux bougent ensemble.
    const bottom = panel ? panel.getBoundingClientRect().bottom : window.innerHeight;
    const room = bottom - box.top - detail.offsetHeight - 36;
    svg.style.height = Math.max(200, Math.min(room, 520)) + 'px';
}
function apply() {
    const path = (sent.path || []).slice(0, shown), state = {}, edges = {};
    path.forEach(([from, id, text]) => {
        (state[id] = state[id] || {status: 'done', outputs: []}).outputs.push(text);
        edges[from + '>' + id] = 'done';
    });
    const last = path[path.length - 1];
    if (last && (sent.running || pouring)) {
        state[last[1]].status = 'active';
        edges[last[0] + '>' + last[1]] = 'active';
    }
    const status = id => (state[id] || {}).status;
    element.querySelectorAll('.node').forEach(node => {
        const id = node.dataset.id, passes = (state[id] || {}).outputs || [];
        node.classList.toggle('active', status(id) === 'active');
        node.classList.toggle('done', status(id) === 'done');
        node.classList.toggle('again', passes.length > 1);
        node.classList.toggle('multi', passes.length > 1);
        node.classList.toggle('pinned', id === pinned);
        node.querySelector('.badge text').textContent = passes.length;
        node.onmouseenter = () => { hovered = id; apply(); };
        node.onmouseleave = () => { hovered = null; apply(); };
        node.onclick = () => { pinned = pinned === id ? null : id; apply(); };
    });
    element.querySelectorAll('.node.dynamic').forEach(node => {
        const url = sent[node.dataset.source] || '';
        if (node.dataset.icon === url) return;
        node.dataset.icon = url;
        node.classList.remove('has-icon');
        node.querySelectorAll('image').forEach(image => {
            // Pas d'icône Shuffle pour ce Pokémon : le chargement échoue et le rond simple reste.
            image.onload = () => node.classList.add('has-icon');
            if (url) image.setAttribute('href', url); else image.removeAttribute('href');
        });
    });
    element.querySelectorAll('.edge').forEach(edge => {
        const reached = edges[edge.dataset.from + '>' + edge.dataset.to];
        edge.classList.toggle('active', reached === 'active');
        if (reached === 'active')  // le rond d'arrivée attend que le liquide ait traversé le tube
        {
            const target = element.querySelector(`.node[data-id="${edge.dataset.to}"]`), entry = target.querySelector('.entry');
            edge.style.setProperty('--dur', crossing(edge) + 's');
            target.style.setProperty('--delay', finish() + crossing(edge) + 's');
            if (entry && !target.classList.contains('again')) entry.setAttribute('transform', `rotate(${edge.dataset.angle})`);
        }
        edge.classList.toggle('done', reached === 'done');
    });
    const chosen = pinned || hovered || Object.keys(state).find(id => status(id) === 'active');
    const node = chosen && element.querySelector(`.node[data-id="${chosen}"]`);
    const passes = ((state[chosen] || {}).outputs || []).slice().reverse();
    element.querySelector('.detail-title').textContent = node ? node.dataset.label : 'Suivez le parcours de votre question';
    element.querySelector('.detail-role').textContent = node ? node.dataset.role : 'Survolez un rond pour voir ce que fait chaque étape ; cliquez pour le garder affiché.';
    element.querySelector('.detail-output').textContent = passes.length > 1
        ? passes.map((text, i) => `Passage ${passes.length - i} — ${text}`).join('\\n') : (passes[0] || '');
}
// Temps passé sur l'étape réellement en cours (pas pendant un rejeu), tant que l'encart la montre.
function clock() {
    const path = sent.path || [], last = path[path.length - 1];
    const key = sent.running && last && shown === path.length ? sent.id + ':' + path.length : null;
    if (key !== waiting) { waiting = key; since = performance.now(); }
    const chosen = pinned || hovered;
    element.querySelector('.detail-time').textContent = key && (!chosen || chosen === last[1])
        ? ((performance.now() - since) / 1000).toFixed(1).replace('.', ',') + ' s' : '';
}
setInterval(clock, 100);
watch('value', receive);
window.addEventListener('resize', fit);
const panel = element.closest('#agent-panel');
const sizes = new ResizeObserver(fit);
sizes.observe(element);
if (panel) sizes.observe(panel);
receive();
fit();
"""
