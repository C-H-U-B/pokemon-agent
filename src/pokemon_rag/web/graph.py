"""Graphe pédagogique du parcours d'une question : dessin, styles et comportement dans le navigateur.

Le graphe est un SVG affiché par un `gr.HTML`. Python n'envoie qu'un état en JSON (`nodes`, `edges`, `user_icon`,
`answer_icon`) ; le survol, l'épinglage et les animations vivent dans le navigateur. Ajouter un module revient à
ajouter une entrée dans `NODES` et ses liens dans `EDGES` : le dessin, l'angle d'arrivée du liquide et le
comportement en découlent.
"""
import hashlib
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
METALOSSE, CREHELF, MIAMIASME = shuffle_icon(376), shuffle_icon(480), shuffle_icon(568)
# Le liquide fonce à mesure qu'il est transformé, de la question à la réponse ; un rejet le ternit.
PALE, ROSE, PINK, MAGENTA, DEEP, SPOILED = "#ffb3ec", "#ff7ddf", "#ff3fcf", "#e600b0", "#a3007d", "#6b7280"
# Ajouter un module = une entrée ici (position, teinte, icône éventuelle) et ses liens dans EDGES.
NODES = [
    {"id": "question", "label": "Votre question", "x": 210, "y": 14, "tint": PALE, "icon": "user_icon",
     "role": "Le texte que vous avez envoyé, tel quel."},
    {"id": "choix", "label": "Modèle · choisit l'outil", "x": 210, "y": 54, "tint": ROSE, "icon": QUEULORIOR,
     "role": "Le modèle de langage lit la question et décide quel outil appeler, avec quels réglages. Il ne calcule rien lui-même."},
    {"id": "guard", "label": "Guard · vérifie", "x": 210, "y": 98, "tint": ROSE, "icon": EXAGIDE,
     "role": "Un contrôle écrit en code compare l'appel du modèle à votre question : il remet une contrainte oubliée ou refuse l'appel."},
    {"id": "rejet", "label": "Rejet", "x": 392, "y": 122, "tint": SPOILED, "icon": MIAMIASME, "label_below": True,
     "role": "La question ne peut pas être traitée : l'outil le dit au lieu d'inventer une réponse."},
    {"id": "mcp", "label": "Serveur d'outils", "x": 210, "y": 142, "tint": PINK, "icon": DRACOLOSSE,
     "role": "Le serveur qui exécute l'outil demandé (protocole MCP) et rapporte son résultat."},
    {"id": "base", "label": "Base de données", "x": 140, "y": 190, "tint": PINK, "icon": METALOSSE, "label_below": True,
     "role": "Les données chiffrées des Pokémon. Tris, filtres et comptages sont faits ici, en SQL."},
    {"id": "pokepedia", "label": "Poképédia", "x": 290, "y": 190, "tint": PINK, "icon": CREHELF,
     "role": "Les textes de l'encyclopédie Poképédia, découpés en passages."},
    {"id": "vector", "label": "recherche par le sens", "x": 290, "y": 226, "tint": PINK, "sub": True,
     "role": "Trouve les passages dont le sens est proche de la question."},
    {"id": "bm25", "label": "recherche par les mots", "x": 290, "y": 246, "tint": PINK, "sub": True,
     "role": "Trouve les passages qui contiennent les mots de la question."},
    {"id": "rrf", "label": "fusion", "x": 290, "y": 266, "tint": PINK, "sub": True, "role": "Réunit les deux listes en une seule."},
    {"id": "reranker", "label": "reclassement", "x": 290, "y": 286, "tint": PINK, "sub": True,
     "role": "Un second modèle relit les meilleurs passages et garde les plus pertinents."},
    {"id": "budget", "label": "Budget de contexte", "x": 210, "y": 320, "tint": MAGENTA,
     "role": "Réduit le résultat à ce que le modèle peut lire sans dépasser sa mémoire de travail."},
    {"id": "redige", "label": "Modèle · rédige", "x": 210, "y": 360, "tint": MAGENTA, "icon": QUEULORIOR,
     "role": "Le modèle écrit la réponse en français à partir des résultats reçus."},
    {"id": "reponse", "label": "Réponse", "x": 210, "y": 404, "tint": DEEP, "icon": "answer_icon",
     "role": "Le texte affiché dans la conversation."},
]
EDGES = [("question", "choix"), ("choix", "guard"), ("guard", "mcp"),  ("mcp", "base"),
         ("mcp", "pokepedia"), ("pokepedia", "vector"), ("vector", "bm25"), ("bm25", "rrf"), ("rrf", "reranker"),
         ("base", "budget"), ("reranker", "budget"), ("budget", "redige"), ("redige", "reponse"),
         ("budget", "choix", "loop"),
         # Toute étape peut échouer : ces tubes vers le rejet n'apparaissent que lorsqu'ils servent.
         ("choix", "rejet", "side", "hidden"), ("guard", "rejet", "side", "hidden"), ("mcp", "rejet", "side", "hidden"),
         ("budget", "rejet", "side", "hidden"), ("redige", "rejet", "side", "hidden")]


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
    parts = ['<svg class="graph" viewBox="0 -12 440 442" role="img" aria-label="Parcours d\'une question">']
    for source, target, *kind in EDGES:
        a, b = by_id[source], by_id[target]
        start, end = (a["x"], a["y"]), (b["x"], b["y"])
        if kind[:1] == ["side"]:  # sortie de côté, sous le libellé de la source
            curve = (start, (a["x"] + 30, b["y"]), (a["x"] + 90, b["y"]), end)
        elif kind:  # retour vers le modèle pour un nouvel appel d'outil
            curve = (start, (10, a["y"]), (10, b["y"]), end)
        else:
            middle = (a["y"] + b["y"]) / 2
            curve = (start, (a["x"], middle), (b["x"], middle), end)
        path = "M {} {} C {} {}, {} {}, {} {}".format(*(value for point in curve for value in point))
        angle = _arrival_angle(curve)
        duration = 1.4 if kind == ["loop"] else 1.3 if abs(a["y"] - b["y"]) + abs(a["x"] - b["x"]) < 70 else 0.95
        ends = f'data-to="{target}" data-from="{source}" data-dur="{duration}" data-angle="{angle}" d="{path}"'
        parts.append(f'<path class="edge track {" ".join(kind)}" {ends}/>'
                     f'<path class="edge fill" pathLength="100" style="--liquid:{b["tint"]};--dur:{duration}s" {ends}/>')
    for node in NODES:
        icon = node.get("icon")
        dynamic = icon in ("user_icon", "answer_icon")  # tête fournie avec l'état : Pikachu du visiteur, Pokémon de la réponse
        r = 18 if icon and not dynamic else 5.5 if node.get("sub") else 9
        kind = "dynamic plain" if dynamic else "icon" if icon else "sub" if node.get("sub") else "plain"
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
        if node.get("label_below"):  # à droite, le libellé toucherait une branche voisine
            parts.append(f'<text x="0" y="{r + 17}" text-anchor="middle">{escape(node["label"])}</text>')
        else:
            parts.append(f'<text x="{r + 8}" y="4">{escape(node["label"])}</text>')
        parts.append(f'<g class="badge" transform="translate({r - 2} {-r + 2})"><circle r="6"/>'
                     '<text y="3" text-anchor="middle"></text></g></g>')
    parts.append('</svg><div class="detail"><div class="detail-title"></div><div class="detail-role"></div>'
                 '<div class="detail-output"></div></div>')
    return "".join(parts)


GRAPH_CSS = """
.graph, .detail { --ink: var(--body-text-color, #1f2933); --muted: var(--body-text-color-subdued, #8a94a3);
    --line: var(--border-color-primary, #e2e6ec); --surface: var(--background-fill-primary, #fff); }
.graph { width: 100%; max-width: 440px; display: block; margin: 0 auto; }
.edge { fill: none; }
/* Un tube de verre (trait gris large) et le liquide qui avance dedans, de la source vers la cible. */
.edge.track { stroke: var(--line); stroke-width: 7; stroke-linecap: round; }
.edge.track.loop { stroke-width: 3; stroke-dasharray: 1 7; }
.edge.track.hidden { opacity: 0; }
.edge.fill { stroke: var(--liquid); stroke-width: 4; stroke-dasharray: 100; stroke-dashoffset: 100; }
.edge.fill.active { animation: graph-pour var(--dur) linear forwards; }
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
.node.done .liquid, .node.again .liquid { transform: translateY(3px); transition: transform 0.7s ease-out; }
/* Nœud à icône : même course, sur le contour coloré de la tête, à partir de l'arrivée du tube. */
.node .sweep { stroke-dasharray: 100; stroke-dashoffset: 100; }
.node.active .sweep { stroke-dashoffset: 58; transition: stroke-dashoffset 6s cubic-bezier(0.1, 0.7, 0.2, 1) var(--delay, 1s); }
.node.done .sweep, .node.again .sweep { stroke-dashoffset: 49; transition: stroke-dashoffset 0.7s ease-out; }
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
.node.pinned .glass { stroke-width: 3; }
.node .badge { display: none; }
.node.multi .badge { display: block; }
.node .badge circle { fill: var(--ink); }
.node .badge text { fill: var(--surface); stroke: none; font-size: 8.5px; font-weight: 700; }
.detail { margin: 6px auto 0; max-width: 440px; padding: 12px 14px; border: 1px solid var(--line); border-radius: 14px;
          background: var(--background-fill-secondary, #f8f9fb); min-height: 84px; }
.detail-title { font-weight: 600; color: var(--ink); }
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

# Le survol et l'épinglage vivent dans le navigateur ; Python n'envoie que l'état du parcours.
GRAPH_JS = """
let pinned = null, hovered = null;
function apply() {
    const sent = JSON.parse(props.value || '{}'), state = sent.nodes || {}, edges = sent.edges || {};
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
            target.style.setProperty('--delay', edge.dataset.dur + 's');
            if (entry && !target.classList.contains('again')) entry.setAttribute('transform', `rotate(${edge.dataset.angle})`);
        }
        edge.classList.toggle('done', reached === 'done');
    });
    const shown = pinned || hovered || Object.keys(state).find(id => status(id) === 'active');
    const node = shown && element.querySelector(`.node[data-id="${shown}"]`);
    const passes = ((state[shown] || {}).outputs || []).slice().reverse();
    element.querySelector('.detail-title').textContent = node ? node.dataset.label : 'Suivez le parcours de votre question';
    element.querySelector('.detail-role').textContent = node ? node.dataset.role : 'Survolez un rond pour voir ce que fait chaque étape ; cliquez pour le garder affiché.';
    element.querySelector('.detail-output').textContent = passes.length > 1
        ? passes.map((text, i) => `Passage ${passes.length - i} — ${text}`).join('\\n') : (passes[0] || '');
}
watch('value', apply);
apply();
"""
