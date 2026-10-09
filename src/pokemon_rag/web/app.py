import asyncio
import html
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, field
import gradio as gr
from google.adk.runners import InMemoryRunner
from google.genai import types
from pokemon_rag.agent.agent import pokemon_mcp, root_agent
from pokemon_rag.agent.context_budget import BUDGET_ABSTENTION, DOUBLE_REQUEST_REFUSAL, TOOL_FAILURE_ABSTENTION
from pokemon_rag.agent.list_fidelity import REPLACEMENT_PREFIX
from pokemon_rag.config import LLM_BASE_URL, LLM_MODEL
from pokemon_rag.constraints.query_constraints import normalize
from pokemon_rag.structured.query_engine import ARTWORK_URL, pokemon_image_urls, pokemon_species_numbers
from pokemon_rag.observability.tracing import TRACE_DIR, save_trace
from pokemon_rag.web.graph import (DEEP, GRAPH_CSS, GRAPH_JS, GRAPH_KEYFRAMES, MAGENTA, PALE, PINK, ROSE,
                                   graph_path, graph_template, graph_value, random_pikachu, shuffle_icon)
from pokemon_rag.web.observability import (OBSERVABILITY_CSS, OBSERVABILITY_JS, OBSERVABILITY_TEMPLATE,
                                           observability_html)

logger = logging.getLogger(__name__)


REFRESH_INTERVAL = 0.1
# Thème de l'interface : le magenta du liquide du graphe, de sa teinte la plus claire à la plus foncée, et le
# turquoise pour ce que le thème appelle couleur secondaire. Les nuances intermédiaires relient ces cinq teintes.
APP_THEME = gr.themes.Soft(
    primary_hue=gr.themes.Color(name="liquide", c50="#fff0fb", c100="#ffe0f7", c200=PALE, c300=ROSE, c400=PINK,
                                c500="#f51fc4", c600=MAGENTA, c700="#bd0091", c800=DEEP, c900="#7a0060",
                                c950="#4a003a"),
    secondary_hue="teal", neutral_hue="slate",
).set(button_primary_background_fill="linear-gradient(180deg, *primary_400, *primary_600)",
      button_primary_background_fill_hover="linear-gradient(180deg, *primary_500, *primary_700)",
      button_primary_border_color="*primary_600", link_text_color="*primary_800",
      input_border_color_focus="*primary_400")
# Nom du modèle affiché dans le panneau : celui qui est réellement servi (Qwen local, modèle distant de la démo).
MODEL_LABEL = LLM_MODEL.rsplit("/", 1)[-1]
REPOSITORY_URL = "https://github.com/C-H-U-B/pokemon-agent"
# Page publique : chaque caractère de la question est payé au modèle distant.
MAX_QUESTION_CHARS = 300
QUESTION_TOO_LONG = f"Question trop longue : {MAX_QUESTION_CHARS} caractères au plus."
# Tant qu'aucune recherche documentaire n'a abouti dans ce processus, la base peut encore se charger.
# ponytail: indice et non état réel du serveur d'outils ; lui faire exposer son état si l'attente gêne.
_documentary_base_ready = False
# Le court délai laisse le navigateur afficher la réponse avant de calculer la position. Gradio redescend
# en bas de la conversation une fois les images chargées, après ce délai : la position est donc tenue 2 s.
# ponytail: durée fixe, pendant laquelle un défilement du lecteur est ramené sur la question ; suivre le
# chargement des images si une réponse s'affiche en plus de 2 s.
SHOW_LAST_QUESTION_JS = """() => setTimeout(() => {
    const rows = document.querySelectorAll('#chat-history .user-row');
    if (!rows.length) return;
    const show = () => rows[rows.length - 1].scrollIntoView({block: 'start'});
    show();
    const hold = setInterval(show, 100);
    setTimeout(() => clearInterval(hold), 2000);
}, 150)"""
# Un clic sur une illustration l'ouvre en grand au milieu de l'écran ; la croix, le fond ou Échap la referment.
IMAGE_VIEWER_JS = """() => {
    const viewer = document.createElement('dialog');
    viewer.id = 'image-viewer';
    viewer.innerHTML = '<button type="button" aria-label="Fermer">×</button><img alt=""><p></p>';
    document.body.append(viewer);
    const picture = viewer.querySelector('img');
    viewer.addEventListener('click', (event) => { if (event.target !== picture) viewer.close(); });
    document.addEventListener('click', (event) => {
        const image = event.target.closest?.('#chat-history .pokemon-images img');
        if (!image) return;
        picture.src = image.src;
        picture.alt = viewer.querySelector('p').textContent = image.alt;
        viewer.showModal();
    });
}"""
APP_CSS = """
.gradio-container { padding: 12px !important; }
.gradio-container footer { display: none; }
/* 56px : marges de la page (12px) et du conteneur de Gradio (16px), en haut et en bas ; avec 24px la page défilait. */
#app-shell { height: calc(100dvh - 56px); min-height: 0; gap: 12px; }
#app-heading { flex-shrink: 0; }
#app-heading h1 { margin-bottom: 4px; }
#app-heading p { margin: 0 0 2px; }
#app-heading .app-meta { font-size: 0.85em; color: var(--body-text-color-subdued); }
#workspace { display: grid; grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);
    gap: 16px; flex: 1 1 0; height: 0; min-height: 0; }
#workspace > div { min-width: 0 !important; min-height: 0; }
#agent-panel { border: 1px solid var(--border-color-primary); border-radius: 18px;
    padding: 8px 18px 18px; background: var(--background-fill-secondary); overflow: hidden; }
/* Le panneau ne défile pas : la barre d'onglets reste en place, et c'est le contenu de l'onglet qui défile.
   Gradio masque l'onglet inactif par un display: none sur ce conteneur, pas par l'attribut hidden. */
#agent-panel .tabs { display: flex; flex-direction: column; height: 100%; min-height: 0; }
#agent-panel .tabitem { flex: 1 1 0; min-height: 0; overflow-y: auto; }
/* Onglet du graphe : le dessin et son encart tiennent dans la hauteur du panneau (ajustée dans le navigateur). */
#agent-panel .tabitem:has(#question-graph) { overflow: hidden; }
/* Illustrations en haut d'une réponse : une ligne de petites images, malgré le style des images de Gradio. */
#chat-history .pokemon-images { display: flex !important; flex-wrap: wrap; gap: 8px; align-items: flex-end; }
#chat-history .pokemon-images > * { flex: 0 0 auto !important; width: auto !important; margin: 0 !important; }
#chat-history .pokemon-images img, #chat-history img[title] { width: 80px !important; height: 80px !important;
    max-width: 80px !important; object-fit: contain; display: inline-block !important; margin: 0 !important; }
#chat-history .pokemon-images img { cursor: zoom-in; }
/* Petite loupe au coin de chaque illustration : elle se clique pour s'ouvrir en grand. */
#chat-history .pokemon-images .zoomable { position: relative; display: inline-block; line-height: 0; }
#chat-history .pokemon-images .zoomable::after { content: ""; position: absolute; right: 0; bottom: 0;
    width: 16px; height: 16px; border-radius: 50%; pointer-events: none; opacity: 0.75;
    background: var(--background-fill-primary) center / 10px no-repeat url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='3' stroke-linecap='round'%3E%3Ccircle cx='10' cy='10' r='7'/%3E%3Cpath d='M15.5 15.5 21 21'/%3E%3C/svg%3E");
    box-shadow: 0 0 0 1px var(--border-color-primary); }
/* Bulle d'attente : mêmes mesures et même animation que les trois points de Gradio (composant Pending). */
#chat-history .pending-dots { display: flex; align-items: center; gap: var(--spacing-xs); min-height: var(--size-6); }
#chat-history .pending-dots i { width: var(--size-1-5); height: var(--size-1-5); margin-right: var(--spacing-xs);
    border-radius: 50%; background-color: var(--body-text-color); opacity: 0.5;
    animation: pending-dot 1.5s infinite; }
#chat-history .pending-dots i:nth-child(2) { animation-delay: 0.2s; }
#chat-history .pending-dots i:nth-child(3) { animation-delay: 0.4s; }
@keyframes pending-dot { 0%, 100% { opacity: 0.4; transform: scale(1); } 50% { opacity: 1; transform: scale(1.1); } }
#image-viewer { border: none; border-radius: 12px; padding: 16px 16px 8px; max-width: 90vw; max-height: 90vh;
    background: var(--background-fill-primary); color: var(--body-text-color); }
#image-viewer::backdrop { background: rgba(0, 0, 0, 0.6); }
#image-viewer img { display: block; width: min(80vw, 70vh, 475px); height: auto; }
#image-viewer p { margin: 4px 0 0; text-align: center; font-weight: 600; }
#image-viewer button { position: absolute; top: 4px; right: 10px; border: none; background: none;
    font-size: 30px; line-height: 1; cursor: pointer; color: inherit; }
#conversation-panel { display: grid; grid-template-rows: minmax(0, 1fr) auto auto auto;
    gap: 4px; overflow-y: auto; }
#chat-history { height: 100% !important; min-height: 0; overflow: hidden; }
#chat-history .bubble.user-row, #chat-history .user { align-self: flex-start; }
#chat-history .bubble.bot-row, #chat-history .bot { align-self: flex-end; }
#chat-history .bubble .user-row { justify-content: flex-start; }
#chat-history .bubble .bot-row { justify-content: flex-end; }
#chat-history .bubble.message-buttons-left { align-self: flex-end; }
#chat-history .bubble.message-buttons-right { align-self: flex-start; }
/* Bouton de copie à côté de sa bulle, dans la marge, et non dessous : il n'ajoute plus de hauteur à faire défiler.
   -34px : sa hauteur (24px) et l'écart avec la bulle (10px), pour l'aligner sur le bas de la bulle. */
#chat-history .message-buttons { margin: -34px 0 0 !important; padding: 0 !important; width: fit-content; z-index: 1; }
#chat-history .message-buttons .icon-button-wrapper { margin: 0 !important; }
#chat-history .message-row.user-row { margin-left: 28px; }
#chat-history .message-row.bot-row { margin-right: 28px; }
#chat-history .user { border-bottom-left-radius: 0;
    border-bottom-right-radius: var(--radius-md); }
#chat-history .bot { border-bottom-right-radius: 0;
    border-bottom-left-radius: var(--radius-md); }
#question-row, #question-actions, #question-examples { flex: 0 0 auto !important; gap: 8px; }
#question-row, #question-actions, #question-examples { align-items: center; }
#question-row > div { min-width: 0 !important; }
#question-actions button, #question-examples button { min-height: 30px; }
/* Questions d'exemple : l'intitulé puis ses trois boutons, serrés à gauche, au-dessus du champ qu'ils remplissent. */
#question-examples > * { flex: 0 0 auto !important; width: auto !important; min-width: 0 !important; }
#question-examples-title { font-size: 13px; font-weight: 600; }
#question-examples-title p, #question-hint p { margin: 0; }
/* « Nouvelle conversation » efface : seule à droite, à l'écart des questions d'exemple. */
#question-actions > button { flex: 0 0 auto !important; width: auto !important; }
#question-hint { font-size: 12px; }
#app-heading { padding: 0; }
#app-heading h1 { margin: 0; font-size: 26px; }
#question-box textarea { font-size: 16px; }
@media (max-width: 760px) {
    #workspace { grid-template-columns: minmax(0, 1fr);
        grid-template-rows: minmax(0, 3fr) minmax(0, 2fr); }
    #agent-panel { padding: 12px; }
}

/* Charte du laboratoire : celle du graphe du parcours, en trois couleurs qui ont chacune un sens partout.
   Jaune de Pikachu (--visitor) : ce qui vient du visiteur, sa question, sa saisie, les exemples proposés.
   Magenta du liquide : l'agent qui agit, titre, envoi, onglet choisi, liquide du graphe.
   Turquoise (--data) : les données rendues, réponse, retours d'outils, encart du graphe, correction d'un appel.
   Le reste est neutre (paillasse en papier millimétré, panneaux en verre) ; le gris est un liquide terni, un rejet. */
:root { --visitor: #eab308; --visitor-soft: #facc15; --data: #0d9488; }
body { background-color: #f8fafc; background-size: 24px 24px;
    background-image: linear-gradient(color-mix(in srgb, var(--neutral-500) 9%, transparent) 1px, transparent 1px),
        linear-gradient(90deg, color-mix(in srgb, var(--neutral-500) 9%, transparent) 1px, transparent 1px); }
body.dark { background-color: #0f141c; }
gradio-app, .gradio-container { background: transparent !important; }
/* Titre : une fiole à moitié pleine, dans la teinte la plus foncée du liquide. */
#app-heading h1 { display: flex; align-items: center; gap: 8px; color: var(--primary-800); }
.dark #app-heading h1 { color: var(--primary-300) !important; }
#app-heading h1::before { content: ""; width: 26px; height: 26px; flex: 0 0 auto;
    background: center / contain no-repeat url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath d='M7.3 15h9.4l2.3 4.6a1 1 0 0 1-.9 1.4H5.9a1 1 0 0 1-.9-1.4z' fill='%23ff3fcf'/%3E%3Cpath d='M9 2.5h6M10 2.5v6L4.4 19.6A1.6 1.6 0 0 0 5.8 22h12.4a1.6 1.6 0 0 0 1.4-2.4L14 8.5v-6' fill='none' stroke='%23a3007d' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round'/%3E%3Ccircle cx='10.3' cy='17.6' r='1.1' fill='%23facc15'/%3E%3Ccircle cx='13.8' cy='18.4' r='.9' fill='%232dd4bf'/%3E%3C/svg%3E"); }
#app-heading a { color: var(--primary-800); }
body.dark #app-heading a { color: var(--primary-300); }
/* Verre : panneaux translucides sur la paillasse, reflet en haut. */
#agent-panel, #chat-history { border: 1px solid var(--border-color-primary) !important;
    border-radius: 18px !important; background: color-mix(in srgb, var(--background-fill-primary) 85%, transparent) !important;
    box-shadow: inset 0 1px 0 color-mix(in srgb, #fff 70%, transparent),
        0 10px 28px -18px color-mix(in srgb, var(--neutral-900) 45%, transparent); }
/* Bulles : la question a le jaune de Pikachu, la réponse est une lame de verre. */
#chat-history .user { background: color-mix(in srgb, var(--visitor-soft) 24%, var(--background-fill-primary)) !important;
    border-color: color-mix(in srgb, var(--visitor) 60%, transparent) !important; }
#chat-history .bot { background: color-mix(in srgb, var(--data) 5%, var(--background-fill-primary)) !important;
    border-color: color-mix(in srgb, var(--data) 40%, var(--border-color-primary)) !important; }
/* Saisie et boutons : le bouton d'envoi est plein de liquide, les exemples sont des pastilles de verre. */
#question-box textarea { border: 1px solid var(--border-color-primary) !important;
    border-radius: 12px !important; background: var(--background-fill-primary) !important; }
#question-box textarea:focus { border-color: var(--visitor) !important;
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--visitor-soft) 30%, transparent) !important; }
#send-button { border-radius: 12px; }
#send-button:disabled { background: #6b7280 !important; border-color: #6b7280 !important; opacity: 0.75; }
#question-examples button, #question-actions > button { border-radius: 999px !important;
    border: 1px solid var(--border-color-primary) !important;
    background: var(--background-fill-primary) !important; transition: background 0.15s, border-color 0.15s; }
/* Les exemples sont des questions du visiteur : son jaune, en liseré, plein au survol. */
#question-examples button { border-color: color-mix(in srgb, var(--visitor) 55%, var(--border-color-primary)) !important; }
#question-examples button:hover { border-color: var(--visitor) !important;
    background: color-mix(in srgb, var(--visitor-soft) 24%, var(--background-fill-primary)) !important; }
#question-actions > button:hover { border-color: var(--neutral-400) !important; }
/* Crédit des illustrations et loupe : des données affichées. */
#chat-history .pokemon-images .zoomable::after { box-shadow: 0 0 0 1px color-mix(in srgb, var(--data) 55%, transparent); }
""" + GRAPH_KEYFRAMES  # hors du style du composant, où Gradio les ignore
# Questions suggérées par public, une par ligne : les boutons passent à la suivante de leur liste.
SUGGESTION_FILES = {"decouvrir": "questions_decouvrir.txt", "connaisseurs": "questions_connaisseurs.txt",
                    "experts": "questions_experts.txt"}
# Une ligne JSON par question posée dans l'interface.
WEB_TRACE_FILE = TRACE_DIR / "web_traces.jsonl"


@dataclass
class WebSession:
    """État propre à une conversation Gradio."""

    user_id: str = field(default_factory=lambda: f"web_{uuid.uuid4().hex}")
    # Prochaine question de chaque liste. La première « découvrir » est déjà dans la saisie au lancement.
    next_suggestion: dict[str, int] = field(default_factory=lambda: {"decouvrir": 1, "connaisseurs": 0, "experts": 0})


runner = InMemoryRunner(agent=root_agent)


@dataclass
class ActivityTiming:
    """Durées côté interface ; association FIFO des appels portant le même nom."""

    phase: str = "analysis"
    phase_start: float = 0.0
    durations: dict[str, float] = field(default_factory=dict)
    calls: list[tuple[str, float, float | None]] = field(default_factory=list)
    # Mesures côté outil par indice d'appel, et tokens cumulés des appels au modèle.
    measures: dict[int, dict] = field(default_factory=dict)
    results: dict[int, dict] = field(default_factory=dict)
    seen_measures: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    # Tokens de réflexion : facturés et comptés dans la limite de sortie, absents de la réponse.
    thinking_tokens: int = 0
    output_limit_reached: bool = False

    def transition(self, phase: str, elapsed: float) -> None:
        if phase != self.phase:
            self.durations[self.phase] = self.durations.get(self.phase, 0.0) + elapsed - self.phase_start
            self.phase, self.phase_start = phase, elapsed

    def observe(self, calls: list[tuple[str, dict]], responses: list[str], elapsed: float, event=None) -> None:
        new_measures: list[dict] = []
        if event is not None:
            # L'état ADK porte les mesures des outils hors du contexte envoyé au modèle.
            recorded = (getattr(getattr(event, "actions", None), "state_delta", None) or {}).get("tool_timings") or []
            new_measures = list(recorded[self.seen_measures:])
            self.seen_measures = max(self.seen_measures, len(recorded))
            usage = getattr(event, "usage_metadata", None)
            if usage is not None:
                self.prompt_tokens += usage.prompt_token_count or 0
                self.output_tokens += usage.candidates_token_count or 0
                self.thinking_tokens += getattr(usage, "thoughts_token_count", None) or 0
            if getattr(event, "finish_reason", None) == types.FinishReason.MAX_TOKENS:
                self.output_limit_reached = True
        returned = [part.function_response for part in getattr(getattr(event, "content", None), "parts", None) or []
                    if getattr(part, "function_response", None) is not None]
        self.calls.extend((name, elapsed, None) for name, _ in calls)
        for name in responses:
            for index, (called, start, end) in enumerate(self.calls):
                if called == name and end is None:
                    self.calls[index] = (called, start, elapsed)
                    measure = next((item for item in new_measures if item.get("tool") == name), None)
                    if measure is not None:
                        new_measures.remove(measure)
                        self.measures[index] = measure
                    result = next((item for item in returned if item.name == name), None)
                    if result is not None:
                        returned.remove(result)
                        self.results[index] = result.response
                    break
        if self.calls:
            self.transition("tools" if any(end is None for _, _, end in self.calls) else "generation", elapsed)

    def duration(self, phase: str, elapsed: float) -> float:
        return self.durations.get(phase, 0.0) + (elapsed - self.phase_start if self.phase == phase else 0.0)


def _load_questions(filename: str) -> list[str]:
    """Charge une liste de questions suggérées depuis le fichier voisin de l'interface."""

    path = Path(__file__).with_name(filename)
    questions = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    if not questions:
        raise ValueError(f"Aucune question dans {path}")

    return questions


SUGGESTIONS = {audience: _load_questions(filename) for audience, filename in SUGGESTION_FILES.items()}
FIRST_QUESTION = SUGGESTIONS["decouvrir"][0]


def _next_suggestion(audience: str, state: WebSession) -> tuple[str, WebSession]:
    """Question suivante de la liste du public, en revenant au début après la dernière."""

    questions = SUGGESTIONS[audience]
    index = state.next_suggestion.get(audience, 0) % len(questions)
    state.next_suggestion[audience] = index + 1
    return questions[index], state


MAX_IMAGES = 5


def _data_names(value) -> list[str]:
    """Noms présents dans les données reçues : champs `name_fr` et argument `pokemon`, à toute profondeur."""
    if isinstance(value, dict):
        own = [value[key] for key in ("name_fr", "pokemon") if isinstance(value.get(key), str)]
        return own + [name for item in value.values() for name in _data_names(item)]
    if isinstance(value, list):
        return [name for item in value for name in _data_names(item)]
    return []


def _answer_images(answer: str, data: list, urls: dict[str, str]) -> list[tuple[str, str]]:
    """(URL, nom) des Pokémon cités dans la réponse ET présents dans les données reçues, 3 au plus.

    La présence dans les données écarte un nom inventé par le modèle et les noms qui sont aussi
    des mots courants. Dans l'ordre de citation ; le nom le plus long l'emporte (« Raichu d'Alola »
    ne montre pas aussi Raichu). Aucune image n'est envoyée au modèle.
    """
    text = f"-{normalize(answer)}-"
    candidates = {normalize(name): name for name in _data_names(data) if normalize(name) in urls}
    found = []
    for key, name in candidates.items():
        position = text.find(f"-{key}-")
        if position >= 0:
            found.append((position, position + len(key) + 1, key, name))
    found = [hit for hit in found if not any(
        other[0] <= hit[0] and hit[1] <= other[1] and other[1] - other[0] > hit[1] - hit[0] for other in found)]
    images, seen = [], set()
    for _, _, key, name in sorted(found):
        if urls[key] not in seen:
            seen.add(urls[key])
            images.append((urls[key], name))
    return images[:MAX_IMAGES]


IMAGE_CREDIT = "Illustrations © Nintendo, Game Freak, The Pokémon Company — via PokéAPI"
IMAGE_WIDTH = 80


def _image_html(answer: str, timing: "ActivityTiming") -> str:
    """Illustrations à placer en haut de la réponse affichée, en HTML ; chaîne vide s'il n'y en a pas.

    À partir des retours d'outils et des arguments exécutés. Images liées (dépôt public
    PokeAPI/sprites) : le navigateur les charge, rien n'est téléchargé ni envoyé au modèle, et
    la trace garde la réponse sans elles. Une base absente ou illisible donne une réponse sans
    image. Du HTML dans le texte plutôt qu'un composant galerie : dans une bulle de conversation,
    la galerie était écrasée et l'image ne s'affichait pas.
    """
    return _images_block(_cited_pokemon(answer, timing))


def _cited_pokemon(answer: str, timing: "ActivityTiming") -> list[tuple[str, str]]:
    """(URL, nom) des Pokémon cités dans la réponse et présents dans les données reçues ; liste vide sinon."""
    if answer in (BUDGET_ABSTENTION, DOUBLE_REQUEST_REFUSAL, TOOL_FAILURE_ABSTENTION):
        return []
    data = list(timing.results.values()) + [measure.get("executed_arguments") or {}
                                             for measure in timing.measures.values()]
    if not _data_names(data):
        return []  # aucun nom reçu : inutile de lire le catalogue
    try:
        return _answer_images(answer, data, pokemon_image_urls())
    except Exception:
        logger.warning("answer_images_failed", exc_info=True)
        return []


def _answer_icon(answer: str, timing: "ActivityTiming") -> str:
    """Icône Shuffle du premier Pokémon de la réponse, pour le nœud « Réponse » du graphe ; chaîne vide sinon.

    Une forme porte l'icône de son espèce. Poképédia n'a pas d'icône pour tous les Pokémon (aucune après la
    septième génération) : l'adresse ne charge alors rien et le nœud reste un rond.
    """
    cited = _cited_pokemon(answer, timing)
    try:
        return shuffle_icon(pokemon_species_numbers()[normalize(cited[0][1])]) if cited else ""
    except Exception:
        logger.warning("answer_icon_failed", exc_info=True)
        return ""


def _images_block(images: list[tuple[str, str]]) -> str:
    """Ligne d'illustrations et son crédit, en HTML ; chaîne vide sans image."""
    if not images:
        return ""
    # L'enveloppe porte la petite loupe du coin (APP_CSS) : une image n'accepte pas de pseudo-élément.
    pictures = "".join(f'<span class="zoomable"><img src="{html.escape(url, quote=True)}" '
                       f'alt="{html.escape(name, quote=True)}" title="{html.escape(name, quote=True)}" '
                       f'width="{IMAGE_WIDTH}"></span>' for url, name in images)
    # Le style de l'interface (APP_CSS) aligne ces images sur une ligne et fixe leur taille.
    return f'<div class="pokemon-images">{pictures}</div>\n\n<sub>{IMAGE_CREDIT}</sub>\n\n'


def _opening_example() -> list[dict]:
    """Échange affiché à l'ouverture : la première question « découvrir », déjà répondue, sans appel au modèle.

    Réponse réelle du modèle de la démo, enregistrée dans `exemple_ouverture.json` avec les numéros de ses
    illustrations : le visiteur a de quoi lire pendant que sa propre question charge. Si la première
    question de la liste a changé sans que l'exemple suive, rien n'est affiché plutôt qu'un échange faux.
    """
    try:
        example = json.loads(Path(__file__).with_name("exemple_ouverture.json").read_text(encoding="utf-8"))
        if example["question"] != FIRST_QUESTION:
            return []
        images = _images_block([(ARTWORK_URL.format(number), name) for name, number in example["images"]])
        return [{"role": "user", "content": example["question"]},
                {"role": "assistant", "content": images + example["reponse"]}]
    except Exception:
        logger.warning("opening_example_failed", exc_info=True)
        return []


def _graph(trace: dict, question_id: str, user_icon: str, speed: float = 1.3, answer_icon: str = "") -> str:
    """Parcours d'une trace, complète ou en cours, tel que le graphe le reçoit."""
    return graph_value(graph_path(trace), question_id=question_id, running=trace["outcome"] == "running",
                       user_icon=user_icon, answer_icon=answer_icon, speed=speed)


# Une recherche documentaire dure 2 s environ ; au-delà, après un démarrage, c'est la base qui se charge.
# ponytail: indice tiré de l'attente, pas l'état réel du serveur d'outils (voir _documentary_base_ready).
LOADING_HINT_SECONDS = 3.0


EMPTY_GRAPH = graph_value([])


def _opening_trace() -> tuple[dict, dict] | None:
    """Exemple d'ouverture et sa trace réelle, gardés dans `exemple_ouverture.json` ; rien si la première
    question a changé sans que l'exemple suive."""
    try:
        example = json.loads(Path(__file__).with_name("exemple_ouverture.json").read_text(encoding="utf-8"))
        if example["question"] != FIRST_QUESTION:
            return None
        return example, {"question": example["question"], **example["trace"]}
    except Exception:
        logger.warning("opening_trace_failed", exc_info=True)
        return None


def _opening_graph() -> str:
    """Parcours de l'exemple d'ouverture, rejoué une fois en accéléré au chargement, sans appel au modèle.

    Sans sa trace, ou si la première question a changé, le graphe reste vide.
    """
    opening = _opening_trace()
    if opening is None:
        return EMPTY_GRAPH
    example, trace = opening
    return _graph(trace, "ouverture", random_pikachu(), speed=2.0,
                  answer_icon=shuffle_icon(example["images"][0][1]) if example["images"] else "")


def _opening_observability() -> str:
    """Chaîne de l'exemple d'ouverture, tirée de la même trace que son parcours."""
    opening = _opening_trace()
    return observability_html(opening and opening[1], "ouverture")


def _final_response_text(events) -> str:
    """Extrait la réponse finale produite par ADK."""

    for event in reversed(events):
        if not event.is_final_response():
            continue

        if event.content is None:
            continue

        return "".join(part.text or "" for part in event.content.parts).strip()

    return ""


def _extract_function_calls(event) -> list[tuple[str, dict]]:
    """Extrait les appels de tools contenus dans un événement ADK."""

    calls: list[tuple[str, dict]] = []

    if event.content is None:
        return calls

    for part in event.content.parts:
        if part.function_call is None:
            continue

        calls.append(
            (
                part.function_call.name,
                dict(part.function_call.args or {}),
            )
        )

    return calls


def _extract_function_responses(event) -> list[str]:
    """Extrait les noms des tools ayant retourné une réponse."""

    responses: list[str] = []

    if event.content is None:
        return responses

    for part in event.content.parts:
        if part.function_response is None:
            continue

        name = part.function_response.name

        if name:
            responses.append(name)

    return responses


def _web_trace(question: str, answer: str, outcome: str, error: Exception | None,
               tool_calls: list[tuple[str, dict]], timing: ActivityTiming, elapsed: float) -> dict:
    """Trace d'une question : appels exécutés (et proposition du modèle si le guard l'a corrigée),
    retours des outils, réponse."""
    if outcome == "answered":
        outcome = {BUDGET_ABSTENTION: "budget_abstention", DOUBLE_REQUEST_REFUSAL: "double_request_refusal",
                   TOOL_FAILURE_ABSTENTION: "tool_failure_abstention"}.get(answer, outcome)
        if answer.startswith(REPLACEMENT_PREFIX):
            outcome = "list_fidelity_replacement"
    tools = []
    for index, (name, arguments) in enumerate(tool_calls):
        _, call_start, call_end = timing.calls[index] if index < len(timing.calls) else (name, None, None)
        measure = {key: value for key, value in timing.measures.get(index, {}).items() if key != "tool"}
        # Arguments exécutés après le guard ; la proposition du modèle n'est gardée que si elle diffère.
        executed = measure.pop("executed_arguments", None)
        if executed is not None and executed != arguments:
            measure["proposed_arguments"] = arguments
        # start : deux appels partis au même instant ont été demandés par le modèle dans le même tour.
        tools.append({"name": name, "arguments": arguments if executed is None else executed, "start": call_start,
                      "seconds": None if call_start is None or call_end is None else call_end - call_start,
                      **measure, "result": timing.results.get(index)})
    return {
        "trace_id": uuid.uuid4().hex,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": LLM_MODEL, "server": LLM_BASE_URL,
        "question": question, "outcome": outcome, "answer": answer,
        "error": None if error is None else f"{type(error).__name__}: {error}",
        "seconds": {"total": elapsed, **{phase: timing.duration(phase, elapsed)
                                        for phase in ("analysis", "tools", "generation")}},
        "tokens": {"prompt": timing.prompt_tokens, "output": timing.output_tokens,
                   "thinking": timing.thinking_tokens, "output_limit_reached": timing.output_limit_reached},
        "tools": tools,
    }


def _save_web_trace(trace: dict) -> None:
    """Une trace illisible ou un disque plein ne doit jamais faire échouer une réponse déjà obtenue."""
    try:
        save_trace(trace, WEB_TRACE_FILE)
        if os.environ.get("WEB_TRACE_STDOUT") == "1":
            # Hébergeur sans disque persistant : le fichier disparaît avec l'instance, la sortie standard
            # est gardée par le journal de la plateforme (une ligne JSON, lue comme entrée structurée).
            print(json.dumps({"message": trace["question"], "web_trace": trace}, ensure_ascii=False, default=str),
                  flush=True)
    except Exception:
        logger.warning("web_trace_failed", exc_info=True)


# Affiché à la place de l'exception : son texte (adresse du serveur, nom du modèle, pile) reste
# dans le journal et dans la trace, pas sur une page publique.
TECHNICAL_ERROR_MESSAGE = "Une erreur technique est survenue. Réessayez dans un instant."
SEND_LABEL, WAITING_LABEL = "Envoyer", "Réponse en cours…"
# Bulle d'attente du chatbot : les trois points animés que Gradio montre un instant à l'envoi, et qu'il retire
# dès la première mise à jour ; redessinés ici (style dans APP_CSS) pour durer jusqu'à la réponse.
PENDING_ANSWER = '<span class="pending-dots" role="status" aria-label="Réponse en cours"><i></i><i></i><i></i></span>'
EXAMPLES_TITLE = "Pas d'idée ? Essayez une question, puis envoyez-la :"
SUGGESTION_LABELS = {"decouvrir": "🌱 Débutant", "connaisseurs": "🎮 Joueur", "experts": "🏆 Expert"}
FOCUS_QUESTION_JS = "() => document.querySelector('#question-box textarea')?.focus()"
# Le bouton d'envoi est inactif pendant une réponse ; la touche Entrée doit l'être aussi, sans vider le champ.
# En phase de capture sur le document : avant l'écouteur de Gradio sur le champ.
BLOCK_ENTER_WHILE_ANSWERING_JS = """() => document.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey && event.target.closest?.('#question-box')
            && document.querySelector('#send-button')?.disabled) {
        event.preventDefault();
        event.stopPropagation();
    }
}, true)"""


async def _run_agent_into_queue(
    state: WebSession,
    content: types.Content,
    queue: asyncio.Queue,
) -> None:
    """Exécute une question dans une session ADK indépendante et temporaire."""

    session = None
    try:
        session = await runner.session_service.create_session(
            app_name=runner.app_name, user_id=state.user_id,
        )
        async for event in runner.run_async(
            user_id=state.user_id,
            session_id=session.id,
            new_message=content,
        ):
            await queue.put(("event", event))

    except Exception as exc:
        await queue.put(("error", exc))

    finally:
        try:
            if session is not None:
                await runner.session_service.delete_session(
                    app_name=runner.app_name, user_id=state.user_id,
                    session_id=session.id,
                )
        except Exception as exc:
            await queue.put(("error", exc))
        finally:
            await queue.put(("done", None))


async def chat(
    message: str,
    history: list[dict],
    state: WebSession,
):
    """Exécute l'agent avec activité et chrono temps réel."""
    global _documentary_base_ready

    message = message.strip()

    if not message:
        yield history, gr.skip(), gr.skip(), gr.skip()
        return

    if len(message) > MAX_QUESTION_CHARS:
        # Refusée ici aussi : la limite du champ de saisie ne s'applique pas à un appel direct de l'API.
        refused = {"question": message[:MAX_QUESTION_CHARS] + "…", "outcome": "question_too_long"}
        yield (
            history + [{"role": "user", "content": refused["question"]},
                       {"role": "assistant", "content": QUESTION_TOO_LONG}],
            gr.skip(),
            observability_html(refused),
            _graph(refused, uuid.uuid4().hex, random_pikachu()),
        )
        return

    content = types.Content(
        role="user",
        parts=[
            types.Part(text=message),
        ],
    )

    start = time.perf_counter()
    pending_history = history + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": PENDING_ANSWER},
    ]

    events = []
    tool_calls: list[tuple[str, dict]] = []
    timing = ActivityTiming()

    queue: asyncio.Queue = asyncio.Queue()

    task = asyncio.create_task(
        _run_agent_into_queue(
            state=state,
            content=content,
            queue=queue,
        )
    )

    finished = False
    error: Exception | None = None
    # Tête du visiteur sur le graphe : un Pikachu tiré au hasard à chaque question.
    question_id, user_icon = uuid.uuid4().hex, random_pikachu()

    def running_views() -> tuple[str, str]:
        """Blocs d'observabilité et parcours du graphe, tirés de la même trace en cours."""
        now = time.perf_counter() - start
        trace = _web_trace(message, "", "running", None, tool_calls, timing, now)
        trace["loading"] = not _documentary_base_ready and any(
            name == "pokemon_rag_search" and end is None and now - begin > LOADING_HINT_SECONDS
            for name, begin, end in timing.calls)
        return observability_html(trace, question_id), _graph(trace, question_id, user_icon)

    sent = running_views()

    # Affichage immédiat.
    yield pending_history, gr.skip(), *sent

    try:
        while not finished:
            try:
                item_type, payload = await asyncio.wait_for(
                    queue.get(),
                    timeout=REFRESH_INTERVAL,
                )

                if item_type == "event":
                    event = payload
                    events.append(event)

                    new_calls = _extract_function_calls(event)
                    new_responses = _extract_function_responses(event)
                    timing.observe(new_calls, new_responses, time.perf_counter() - start, event)

                    tool_calls.extend(new_calls)
                    if "pokemon_rag_search" in new_responses:
                        _documentary_base_ready = True

                elif item_type == "error":
                    error = payload

                elif item_type == "done":
                    finished = True
                    timing.transition("finished", time.perf_counter() - start)

            except asyncio.TimeoutError:
                # Aucun nouvel événement ADK : seul l'indice de chargement de la base peut avoir changé.
                pass

            # Blocs et graphe ne sont renvoyés que lorsqu'ils ont changé : le navigateur déroule seul le
            # parcours, et un retour déplié par le lecteur n'est pas redessiné dix fois par seconde.
            current = sent if finished else running_views()
            updates = [gr.skip() if new == old else new for new, old in zip(current, sent)]
            sent = current

            # Conversation et état non renvoyés ici : dix mises à jour par seconde ramenaient le
            # défilement en bas et écrasaient une suggestion choisie pendant l'attente.
            yield gr.skip(), gr.skip(), *updates

        await task

    finally:
        # Page fermée ou nouvelle conversation : Gradio ferme ce générateur. Sans annulation,
        # l'agent continuerait d'appeler le modèle pour une réponse que personne ne lira.
        if not task.done():
            task.cancel()

    elapsed = time.perf_counter() - start

    if error is not None:
        logger.warning("web_request_failed", exc_info=error)
        response = TECHNICAL_ERROR_MESSAGE
        outcome = "error"

    else:
        response = _final_response_text(events)

        if not response:
            response = "L'agent n'a produit aucune réponse finale."
            outcome = "no_final_response"
        else:
            outcome = "answered"

    trace = _web_trace(message, response, outcome, error, tool_calls, timing, elapsed)
    _save_web_trace(trace)

    updated_history = history + [
        {
            "role": "user",
            "content": message,
        },
        {
            "role": "assistant",
            # Illustrations des Pokémon cités et présents dans les données, en haut de la réponse affichée.
            "content": ("" if error is not None else _image_html(response, timing)) + response,
        },
    ]

    yield (
        updated_history,
        gr.skip(),
        observability_html(trace, question_id),
        _graph(trace, question_id, user_icon, answer_icon="" if error is not None else _answer_icon(response, timing)),
    )


def new_conversation():
    """Réinitialise complètement la conversation."""

    return (
        [],
        WebSession(),
        observability_html(None),
        "",
        EMPTY_GRAPH,
        gr.update(value=SEND_LABEL, interactive=True),  # la question annulée ne rendra pas le bouton elle-même
    )


async def _warm_up() -> None:
    """Démarre le serveur d'outils à l'ouverture de la page, avant la première question.

    Le serveur est réutilisé par les questions suivantes ; avec POKEMON_RAG_PRELOAD=1, il charge
    alors la base documentaire en arrière-plan. Un échec ici ne bloque pas l'interface.
    """
    try:
        await pokemon_mcp.get_tools()
    except Exception:
        logger.warning("warm_up_failed", exc_info=True)


def build_app() -> gr.Blocks:
    """Construit l'interface web du Pokémon Agent."""

    with gr.Blocks(
        title="Pokémon Agent",
        fill_height=True,
    ) as app:
        with gr.Column(elem_id="app-shell"):
            state = gr.State(WebSession())

            gr.Markdown(
                f"""
                # Pokémon Agent
                Des réponses tirées d'une base de données et de Poképédia, pas de la mémoire du modèle.
                Posez une question et suivez à droite ce que fait l'agent.

                <span class="app-meta">Modèle : {MODEL_LABEL} ·
                <a href="{REPOSITORY_URL}" target="_blank">Code et explications sur GitHub</a> ·
                Les questions posées sont enregistrées pour améliorer l'outil.</span>
                """,
                elem_id="app-heading",
            )

            with gr.Row(equal_height=True, elem_id="workspace"):
                # Conversation
                with gr.Column(scale=3, min_width=320, elem_id="conversation-panel"):
                    opening = _opening_example()
                    chatbot = gr.Chatbot(
                        value=opening,
                        show_label=False,
                        height="100%",
                        elem_id="chat-history",
                    )
                    with gr.Row(elem_id="question-examples"):
                        gr.Markdown(EXAMPLES_TITLE, elem_id="question-examples-title")
                        suggestion_buttons = {
                            audience: gr.Button(label, size="sm", scale=0, min_width=0)
                            for audience, label in SUGGESTION_LABELS.items()
                        }
                    with gr.Row(elem_id="question-row"):
                        message = gr.Textbox(
                            # Sans exemple affiché, la première question reste proposée dans le champ.
                            value="" if opening else FIRST_QUESTION,
                            placeholder="Posez une question sur les Pokémon",
                            label="Votre question",
                            max_length=MAX_QUESTION_CHARS,
                            show_label=False,
                            container=False,
                            lines=1,
                            max_lines=2,
                            scale=6,
                            elem_id="question-box",
                        )

                        send = gr.Button(
                            SEND_LABEL,
                            variant="primary",
                            scale=1,
                            elem_id="send-button",
                        )

                    with gr.Row(elem_id="question-actions"):
                        gr.Markdown(
                            "Chaque question est indépendante : précisez le Pokémon, "
                            "sa forme et le jeu si nécessaire.",
                            elem_id="question-hint",
                        )
                        clear = gr.Button(
                            "Nouvelle conversation",
                            size="sm",
                            scale=0,
                        )

                # Activité
                with gr.Column(scale=2, min_width=320, elem_id="agent-panel"):
                    # Onglets : un troisième (guide des questions) s'ajoutera sans refaire la bascule.
                    with gr.Tabs():
                        with gr.Tab("Parcours"):
                            graph = gr.HTML(
                                value=_opening_graph() if opening else EMPTY_GRAPH,
                                html_template=graph_template(),
                                css_template=GRAPH_CSS,
                                js_on_load=GRAPH_JS,
                                elem_id="question-graph",
                            )
                        with gr.Tab("Observabilité"):
                            activity = gr.HTML(
                                value=_opening_observability() if opening else observability_html(None),
                                html_template=OBSERVABILITY_TEMPLATE,
                                css_template=OBSERVABILITY_CSS,
                                js_on_load=OBSERVABILITY_JS,
                                elem_id="question-observability",
                            )

            # La saisie est vidée dès l'envoi, pas à l'arrivée de la réponse : une question préparée
            # pendant l'attente (suggestion ou frappe) reste dans le champ. Bouton et touche Entrée.
            pending_question = gr.State("")
            chat_events = []
            for trigger in (send.click, message.submit):
                chat_event = trigger(
                    # Le bouton est rendu inactif jusqu'à la réponse, avec un libellé qui dit pourquoi.
                    fn=lambda text: ("", text, gr.update(value=WAITING_LABEL, interactive=False)),
                    inputs=message,
                    outputs=[message, pending_question, send],
                ).then(
                    fn=chat,
                    inputs=[pending_question, chatbot, state],
                    outputs=[chatbot, state, activity, graph],
                )
                # Réponse arrivée : la conversation revient sur la dernière question, même si le lecteur
                # était remonté lire une réponse précédente (Gradio ne redescend que s'il était déjà en bas).
                chat_event.then(fn=None, js=SHOW_LAST_QUESTION_JS)
                # Après la réponse, même si elle a échoué (then, pas success).
                chat_event.then(fn=lambda: gr.update(value=SEND_LABEL, interactive=True), outputs=send)
                chat_events.append(chat_event)

            # Question suivante de la liste de chaque public, puis curseur dans le champ : il reste à l'envoyer.
            for audience, button in suggestion_buttons.items():
                button.click(
                    fn=lambda current, audience=audience: _next_suggestion(audience, current),
                    inputs=state,
                    outputs=[message, state],
                ).then(fn=None, js=FOCUS_QUESTION_JS)

            # Nouvelle conversation.
            clear.click(
                fn=new_conversation,
                outputs=[
                    chatbot,
                    state,
                    activity,
                    message,
                    graph,
                    send,
                ],
                cancels=chat_events,
            )

        app.load(fn=_warm_up)
        app.load(fn=None, js=BLOCK_ENTER_WHILE_ANSWERING_JS)
        app.load(fn=None, js=IMAGE_VIEWER_JS)
        # Exemple d'ouverture : Gradio descend en bas de la conversation, la question restait cachée au-dessus.
        app.load(fn=None, js=SHOW_LAST_QUESTION_JS)

    return app


demo = build_app()


if __name__ == "__main__":
    demo.launch(
        inbrowser=True,
        theme=APP_THEME,
        css=APP_CSS,
    )
