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
from pokemon_rag.structured.query_engine import ARTWORK_URL, pokemon_image_urls
from pokemon_rag.observability.tracing import TRACE_DIR, save_trace
from pokemon_rag.web.graph import (GRAPH_CSS, GRAPH_JS, GRAPH_KEYFRAMES, TOOL_LABELS, graph_path, graph_template,
                                   graph_value, random_pikachu)

logger = logging.getLogger(__name__)


REFRESH_INTERVAL = 0.1
# Nom du modèle affiché dans le panneau : celui qui est réellement servi (Qwen local, modèle distant de la démo).
MODEL_LABEL = LLM_MODEL.rsplit("/", 1)[-1]
REPOSITORY_URL = "https://github.com/C-H-U-B/pokemon-agent"
# Page publique : chaque caractère de la question est payé au modèle distant.
MAX_QUESTION_CHARS = 300
QUESTION_TOO_LONG = f"Question trop longue : {MAX_QUESTION_CHARS} caractères au plus."
# Tant qu'aucune recherche documentaire n'a abouti dans ce processus, la base peut encore se charger.
# ponytail: indice et non état réel du serveur d'outils ; lui faire exposer son état si l'attente gêne.
_documentary_base_ready = False
# Le court délai laisse le navigateur afficher la réponse avant de calculer la position.
SHOW_LAST_QUESTION_JS = """() => setTimeout(() => {
    const rows = document.querySelectorAll('#chat-history .user-row');
    if (rows.length) rows[rows.length - 1].scrollIntoView({behavior: 'smooth', block: 'start'});
}, 150)"""
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
    padding: 18px; background: var(--background-fill-secondary); overflow-y: auto; }
#agent-panel h3 { margin-top: 20px; }
/* Onglet du graphe : le dessin et son encart tiennent dans la hauteur du panneau (ajustée dans le navigateur). */
#agent-panel:has(#question-graph:not([hidden])) { overflow: hidden; padding-top: 8px; }
/* Illustrations en haut d'une réponse : une ligne de petites images, malgré le style des images de Gradio. */
#chat-history .pokemon-images { display: flex !important; flex-wrap: wrap; gap: 8px; align-items: flex-end; }
#chat-history .pokemon-images > * { flex: 0 0 auto !important; width: auto !important; margin: 0 !important; }
#chat-history .pokemon-images img, #chat-history img[title] { width: 80px !important; height: 80px !important;
    max-width: 80px !important; object-fit: contain; display: inline-block !important; margin: 0 !important; }
#agent-panel code { overflow-wrap: anywhere; white-space: pre-wrap; }
#conversation-panel { display: grid; grid-template-rows: minmax(0, 1fr) auto auto auto;
    gap: 4px; overflow-y: auto; }
#chat-history { height: 100% !important; min-height: 0; overflow: hidden; }
#chat-history .bubble.user-row, #chat-history .user { align-self: flex-start; }
#chat-history .bubble.bot-row, #chat-history .bot { align-self: flex-end; }
#chat-history .bubble .user-row { justify-content: flex-start; }
#chat-history .bubble .bot-row { justify-content: flex-end; }
#chat-history .bubble.message-buttons-left { align-self: flex-end; }
#chat-history .bubble.message-buttons-right { align-self: flex-start; }
#chat-history .message-buttons-right .icon-button-wrapper { margin-left: 0; }
#chat-history .user { border-bottom-left-radius: 0;
    border-bottom-right-radius: var(--radius-md); }
#chat-history .bot { border-bottom-right-radius: 0;
    border-bottom-left-radius: var(--radius-md); }
#question-row, #question-actions { flex: 0 0 auto !important; gap: 8px; }
#question-row { align-items: center; }
#question-row > div { min-width: 0 !important; }
#question-actions button { min-height: 30px; }
#question-hint { font-size: 12px; }
#question-hint p { margin: 0; }
#app-heading { padding: 0; }
#app-heading h1 { margin: 0; font-size: 26px; }
#question-box textarea { font-size: 16px; }
@media (max-width: 760px) {
    #workspace { grid-template-columns: minmax(0, 1fr);
        grid-template-rows: minmax(0, 3fr) minmax(0, 2fr); }
    #agent-panel { padding: 12px; }
}
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
    # Tête du visiteur sur le graphe : un Pikachu tiré au hasard par conversation.
    icon: str = field(default_factory=random_pikachu)


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
    if answer in (BUDGET_ABSTENTION, DOUBLE_REQUEST_REFUSAL, TOOL_FAILURE_ABSTENTION):
        return ""
    data = list(timing.results.values()) + [measure.get("executed_arguments") or {}
                                             for measure in timing.measures.values()]
    if not _data_names(data):
        return ""  # aucun nom reçu : inutile de lire le catalogue
    try:
        images = _answer_images(answer, data, pokemon_image_urls())
    except Exception:
        logger.warning("answer_images_failed", exc_info=True)
        return ""
    return _images_block(images)


def _images_block(images: list[tuple[str, str]]) -> str:
    """Ligne d'illustrations et son crédit, en HTML ; chaîne vide sans image."""
    if not images:
        return ""
    pictures = "".join(f'<img src="{html.escape(url, quote=True)}" alt="{html.escape(name, quote=True)}" '
                       f'title="{html.escape(name, quote=True)}" width="{IMAGE_WIDTH}">' for url, name in images)
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


def _graph(trace: dict, question_id: str, state: WebSession, pace: int = 700) -> str:
    """Parcours d'une trace, complète ou en cours, tel que le graphe le reçoit."""
    return graph_value(graph_path(trace), question_id=question_id, running=trace["outcome"] == "running",
                       user_icon=state.icon, pace=pace)


EMPTY_GRAPH = graph_value([])


def _opening_graph() -> str:
    """Parcours de l'exemple d'ouverture, rejoué une fois en accéléré au chargement, sans appel au modèle.

    Trace réelle de la réponse affichée, gardée dans `exemple_ouverture.json`. Sans elle, ou si la première
    question a changé, le graphe reste vide.
    """
    try:
        example = json.loads(Path(__file__).with_name("exemple_ouverture.json").read_text(encoding="utf-8"))
        if example["question"] != FIRST_QUESTION:
            return EMPTY_GRAPH
        return _graph({"question": example["question"], **example["trace"]}, "ouverture", WebSession(), pace=550)
    except Exception:
        logger.warning("opening_graph_failed", exc_info=True)
        return EMPTY_GRAPH


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


STARTUP_STEPS = (("embedding", "modèle d'embedding"), ("reranker", "modèle de reclassement"),
                 ("corpus", "corpus"), ("bm25", "index lexical"))
SEARCH_STEPS = (("vector", "vectorielle"), ("bm25", "lexicale"), ("rrf", "fusion"), ("reranker", "reclassement"))


def _steps(values: dict, labels: tuple) -> str:
    return " · ".join(f"{label} {values[key]:.2f} s" for key, label in labels if key in values)


def _measure_lines(measure: dict | None) -> list[str]:
    """Temps mesurés par l'outil lui-même : chargement et étapes de la recherche, ou requête SQL."""
    if not measure:
        return []
    lines = []
    timings = measure.get("timings") or {}
    startup = timings.get("startup")
    if startup:
        lines.append(f"- Chargement de la base (premier appel) : {startup.get('total', 0.0):.1f} s"
                     f" ({_steps(startup, STARTUP_STEPS)})")
    if "total" in timings:
        steps = _steps(timings, SEARCH_STEPS)
        lines.append(f"- Recherche : {timings['total']:.2f} s" + (f" ({steps})" if steps else "")
                     + f" · {measure.get('passages', 0)} passage(s)")
    if measure.get("execution_time") is not None:
        lines.append(f"- Requête SQL : {measure['execution_time'] * 1000:.0f} ms")
    return lines


def _format_activity(
    tool_calls: list[tuple[str, dict]],
    completed_tools: list[str],
    elapsed_seconds: float,
    status: str,
    timing: ActivityTiming | None = None,
) -> str:
    """Construit le panneau d'activité temps réel."""

    lines = [
        "## Agent et outils en action",
        "",
        f"**Agent Pokémon — ADK + {MODEL_LABEL}**",
        f"ADK orchestre les échanges ; {MODEL_LABEL} interprète la question et rédige la réponse.",
        "",
        f"**⏱ {elapsed_seconds:.1f} s · {len(tool_calls)} appel(s) d'outil**",
        "",
        status,
        "",
    ]

    if timing is not None:
        lines.extend([
            "**Temps par étape**",
            f"- Analyse / choix des outils : {timing.duration('analysis', elapsed_seconds):.1f} s",
            f"- Attente des outils : {timing.duration('tools', elapsed_seconds):.1f} s",
            f"- Préparation de la réponse : {timing.duration('generation', elapsed_seconds):.1f} s",
        ])
        startup = next((measure["timings"]["startup"] for measure in timing.measures.values()
                        if (measure.get("timings") or {}).get("startup")), None)
        if startup:
            lines.append(f"- Chargement de la base documentaire (premier appel) : {startup.get('total', 0.0):.1f} s")
        if timing.prompt_tokens or timing.output_tokens:
            model_time = timing.duration("analysis", elapsed_seconds) + timing.duration("generation", elapsed_seconds)
            # Le serveur de modèle ne sépare pas lecture et génération : ce débit couvre les deux.
            rate = (f" · ≈ {timing.output_tokens / model_time:.0f} tokens/s, lecture des requêtes comprise"
                    if timing.output_tokens and model_time > 0 else "")
            lines.append(f"- {MODEL_LABEL} : {timing.prompt_tokens} tokens lus, {timing.output_tokens} générés{rate}")
        lines.append("")

    if not tool_calls:
        lines.append("**Outils sollicités :** aucun pour le moment.")
        return "\n".join(lines)

    completed_counts: dict[str, int] = {}

    for name in completed_tools:
        completed_counts[name] = completed_counts.get(name, 0) + 1

    displayed_counts: dict[str, int] = {}

    lines.extend([
        f"### 1. Analyse de la question · {MODEL_LABEL}",
        "L'agent a demandé les outils ci-dessous pour traiter la question.",
        "",
    ])

    for index, (name, arguments) in enumerate(tool_calls, start=1):
        displayed_counts[name] = displayed_counts.get(name, 0) + 1

        is_completed = displayed_counts[name] <= completed_counts.get(name, 0)

        label = TOOL_LABELS.get(name, name)
        lines.append(f"### 1.{index} {label} · outil MCP")
        lines.append(f"`{name}` · " + (
            "Réponse reçue" if is_completed else "Appel observé · réponse en attente"
        ))
        lines.append("")
        if timing is not None and index <= len(timing.calls):
            _, call_start, call_end = timing.calls[index - 1]
            end = call_end if call_end is not None else (
                timing.phase_start if timing.phase == "finished" else elapsed_seconds
            )
            lines.append(f"**⏱ {end - call_start:.1f} s**" + (" · en attente" if call_end is None else ""))
        if name == "pokemon_rag_search":
            lines.append(
                "**Recherche RAG — Poképédia / index Chroma.** "
                + ("La recherche a retourné son résultat à l'agent."
                   if is_completed else
                   "Recherche de passages textuels pertinents pour documenter la réponse.")
            )
        elif name in TOOL_LABELS:
            lines.append(
                "**Requête structurée — base SQLite.** "
                + ("L'outil a retourné le résultat de la consultation à l'agent."
                   if is_completed else
                   "Consultation des données Pokémon dans la base locale.")
            )
        else:
            lines.append("L'agent échange avec cet outil via le protocole MCP.")

        measured = _measure_lines(timing.measures.get(index - 1)) if timing is not None else []
        if measured:
            lines.extend(["", *measured])

        executed = (timing.measures.get(index - 1) or {}).get("executed_arguments") if timing is not None else None
        shown = arguments if executed is None else executed
        if shown:
            lines.append("")
            if executed is not None and executed != arguments:
                lines.append("Arguments exécutés après correction par le guard :")

            for key, value in shown.items():
                lines.append(f"- `{key}` : `{value}`")

        lines.append("")

    if completed_tools:
        lines.extend([
            f"### 2. Préparation de la réponse · {MODEL_LABEL}",
            f"{MODEL_LABEL} dispose des retours d'outils pour préparer une réponse textuelle en français.",
            "",
        ])

    return "\n".join(lines)


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
        yield (
            history,
            gr.skip(),
            _format_activity([], [], 0.0, "Aucune requête envoyée."),
            gr.skip(),
        )
        return

    if len(message) > MAX_QUESTION_CHARS:
        # Refusée ici aussi : la limite du champ de saisie ne s'applique pas à un appel direct de l'API.
        yield (
            history + [{"role": "user", "content": message[:MAX_QUESTION_CHARS] + "…"},
                       {"role": "assistant", "content": QUESTION_TOO_LONG}],
            gr.skip(),
            _format_activity([], [], 0.0, "Aucune requête envoyée."),
            _graph({"question": message[:MAX_QUESTION_CHARS] + "…", "outcome": "question_too_long"},
                   uuid.uuid4().hex, state),
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
        {"role": "assistant", "content": "…"},
    ]

    events = []
    tool_calls: list[tuple[str, dict]] = []
    completed_tools: list[str] = []
    timing = ActivityTiming()

    queue: asyncio.Queue = asyncio.Queue()

    task = asyncio.create_task(
        _run_agent_into_queue(
            state=state,
            content=content,
            queue=queue,
        )
    )

    status = f"🧠 **{MODEL_LABEL} analyse la question et choisit les outils adaptés…**"
    finished = False
    error: Exception | None = None
    question_id = uuid.uuid4().hex

    def running_graph() -> str:
        return _graph(_web_trace(message, "", "running", None, tool_calls, timing, time.perf_counter() - start),
                      question_id, state)

    sent_graph = running_graph()

    # Affichage immédiat.
    yield (
        pending_history,
        gr.skip(),
        _format_activity(
            tool_calls,
            completed_tools,
            0.0,
            status,
            timing,
        ),
        sent_graph,
    )

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

                    if new_calls:
                        tool_calls.extend(new_calls)
                        sources = []
                        for name, _ in new_calls:
                            source = ("recherche de passages textuels dans Poképédia"
                                      if name == "pokemon_rag_search" else
                                      "consultation de la base SQLite" if name in TOOL_LABELS else
                                      "appel d'un outil MCP")
                            if source not in sources:
                                sources.append(source)
                        status = "🔎 **En cours : " + " ; ".join(sources) + ".**"
                        if not _documentary_base_ready and any(name == "pokemon_rag_search" for name, _ in new_calls):
                            status += ("\n\nPremière recherche depuis le démarrage : la base documentaire peut "
                                       "encore se charger (jusqu'à une minute et demie). Les questions sur les "
                                       "données, elles, répondent tout de suite.")

                    if new_responses:
                        if "pokemon_rag_search" in new_responses:
                            _documentary_base_ready = True
                        completed_tools.extend(new_responses)
                        status = f"🧠 **Retour d'outil reçu — {MODEL_LABEL} prépare la réponse textuelle…**"

                elif item_type == "error":
                    error = payload
                    status = "❌ **Erreur pendant l'exécution.**"

                elif item_type == "done":
                    finished = True
                    timing.transition("finished", time.perf_counter() - start)

            except asyncio.TimeoutError:
                # Aucun nouvel événement ADK :
                # on rafraîchit quand même le chrono.
                pass

            elapsed = time.perf_counter() - start
            # Le graphe n'est renvoyé que lorsque le parcours a changé : le navigateur le déroule seul.
            current_graph = sent_graph if finished else running_graph()
            graph_update = gr.skip() if current_graph == sent_graph else current_graph
            sent_graph = current_graph

            # Conversation et état non renvoyés ici : dix mises à jour par seconde ramenaient le
            # défilement en bas et écrasaient une suggestion choisie pendant l'attente.
            yield (
                gr.skip(),
                gr.skip(),
                _format_activity(
                    tool_calls,
                    completed_tools,
                    elapsed,
                    status,
                    timing,
                ),
                graph_update,
            )

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

        status = "❌ **Erreur**"
        outcome = "error"

    else:
        response = _final_response_text(events)

        if not response:
            response = "L'agent n'a produit aucune réponse finale."
            status = "⚠️ **Aucune réponse finale**"
            outcome = "no_final_response"
        else:
            status = "✅ **Réponse disponible**"
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
        _format_activity(
            tool_calls,
            completed_tools,
            elapsed,
            status,
            timing,
        ),
        _graph(trace, question_id, state),
    )


def new_conversation():
    """Réinitialise complètement la conversation."""

    return (
        [],
        WebSession(),
        _format_activity([], [], 0.0, "En attente d'une question."),
        "",
        EMPTY_GRAPH,
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
                    gr.Markdown(
                        "Chaque question est indépendante : précisez le Pokémon, "
                        "sa forme et le jeu si nécessaire.",
                        elem_id="question-hint",
                    )
                    with gr.Row(elem_id="question-row"):
                        message = gr.Textbox(
                            # Sans exemple affiché, la première question reste proposée dans le champ.
                            value="" if opening else FIRST_QUESTION,
                            placeholder="Posez une question sur les Pokémon, ou choisissez une suggestion ci-dessous",
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
                            "Envoyer",
                            variant="primary",
                            scale=1,
                        )

                    with gr.Row(elem_id="question-actions"):
                        suggestion_buttons = {
                            "decouvrir": gr.Button("🌱 Je découvre Pokémon", size="sm"),
                            "connaisseurs": gr.Button("🎮 Je connais Pokémon", size="sm"),
                            "experts": gr.Button("🏆 Expert", size="sm"),
                        }

                        clear = gr.Button(
                            "Nouvelle conversation",
                            size="sm",
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
                        with gr.Tab("Temps"):
                            activity = gr.Markdown(
                                _format_activity([], [], 0.0, "En attente d'une question."),
                            )

            # La saisie est vidée dès l'envoi, pas à l'arrivée de la réponse : une question préparée
            # pendant l'attente (suggestion ou frappe) reste dans le champ. Bouton et touche Entrée.
            pending_question = gr.State("")
            chat_events = []
            for trigger in (send.click, message.submit):
                chat_event = trigger(
                    fn=lambda text: ("", text),
                    inputs=message,
                    outputs=[message, pending_question],
                ).then(
                    fn=chat,
                    inputs=[pending_question, chatbot, state],
                    outputs=[chatbot, state, activity, graph],
                )
                # Réponse arrivée : la conversation revient sur la dernière question, même si le lecteur
                # était remonté lire une réponse précédente (Gradio ne redescend que s'il était déjà en bas).
                chat_event.then(fn=None, js=SHOW_LAST_QUESTION_JS)
                chat_events.append(chat_event)

            # Question suivante de la liste de chaque public.
            for audience, button in suggestion_buttons.items():
                button.click(
                    fn=lambda current, audience=audience: _next_suggestion(audience, current),
                    inputs=state,
                    outputs=[message, state],
                )

            # Nouvelle conversation.
            clear.click(
                fn=new_conversation,
                outputs=[
                    chatbot,
                    state,
                    activity,
                    message,
                    graph,
                ],
                cancels=chat_events,
            )

        app.load(fn=_warm_up)
        # Exemple d'ouverture : Gradio descend en bas de la conversation, la question restait cachée au-dessus.
        app.load(fn=None, js=SHOW_LAST_QUESTION_JS)

    return app


demo = build_app()


if __name__ == "__main__":
    demo.launch(
        inbrowser=True,
        theme=gr.themes.Soft(primary_hue="red", secondary_hue="slate"),
        css=APP_CSS,
    )
