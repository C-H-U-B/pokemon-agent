import asyncio
import random
import time
import uuid
from pathlib import Path
from dataclasses import dataclass, field
import gradio as gr
from google.adk.runners import InMemoryRunner
from google.genai import types
from pokemon_rag.agent.agent import root_agent


REFRESH_INTERVAL = 0.1
APP_CSS = """
.gradio-container { padding: 12px !important; }
.gradio-container footer { display: none; }
#app-shell { height: calc(100dvh - 24px); min-height: 0; gap: 12px; }
#app-heading { flex-shrink: 0; }
#workspace { display: grid; grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);
    gap: 16px; flex: 1 1 0; height: 0; min-height: 0; }
#workspace > div { min-width: 0 !important; min-height: 0; }
#agent-panel { border: 1px solid var(--border-color-primary); border-radius: 18px;
    padding: 18px; background: var(--background-fill-secondary); overflow-y: auto; }
#agent-panel h3 { margin-top: 20px; }
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
"""
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
    "pokemon_rag_search": "Recherche documentaire Poképédia",
}
EXAMPLE_QUESTIONS_PATH = Path(__file__).with_name("example_questions.txt")


@dataclass
class WebSession:
    """État propre à une conversation Gradio."""

    user_id: str = field(default_factory=lambda: f"web_{uuid.uuid4().hex}")


runner = InMemoryRunner(agent=root_agent)


@dataclass
class ActivityTiming:
    """Durées côté interface ; association FIFO des appels portant le même nom."""

    phase: str = "analysis"
    phase_start: float = 0.0
    durations: dict[str, float] = field(default_factory=dict)
    calls: list[tuple[str, float, float | None]] = field(default_factory=list)

    def transition(self, phase: str, elapsed: float) -> None:
        if phase != self.phase:
            self.durations[self.phase] = self.durations.get(self.phase, 0.0) + elapsed - self.phase_start
            self.phase, self.phase_start = phase, elapsed

    def observe(self, calls: list[tuple[str, dict]], responses: list[str], elapsed: float) -> None:
        self.calls.extend((name, elapsed, None) for name, _ in calls)
        for name in responses:
            for index, (called, start, end) in enumerate(self.calls):
                if called == name and end is None:
                    self.calls[index] = (called, start, elapsed)
                    break
        if self.calls:
            self.transition("tools" if any(end is None for _, _, end in self.calls) else "generation", elapsed)

    def duration(self, phase: str, elapsed: float) -> float:
        return self.durations.get(phase, 0.0) + (elapsed - self.phase_start if self.phase == phase else 0.0)


def _load_example_questions() -> list[str]:
    """Charge les questions d'exemple depuis le fichier associé à l'interface."""

    questions = [
        line.strip()
        for line in EXAMPLE_QUESTIONS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    if not questions:
        raise ValueError(f"Aucune question d'exemple dans {EXAMPLE_QUESTIONS_PATH}")

    return questions


EXAMPLE_QUESTIONS = _load_example_questions()


def _random_example_question() -> str:
    """Retourne une question d'exemple aléatoire."""

    return random.choice(EXAMPLE_QUESTIONS)


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
        "**Agent Pokémon — ADK + Qwen local**",
        "ADK orchestre les échanges ; Qwen interprète la question et rédige la réponse.",
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
            "",
        ])

    if not tool_calls:
        lines.append("**Outils sollicités :** aucun pour le moment.")
        return "\n".join(lines)

    completed_counts: dict[str, int] = {}

    for name in completed_tools:
        completed_counts[name] = completed_counts.get(name, 0) + 1

    displayed_counts: dict[str, int] = {}

    lines.extend([
        "### 1. Analyse de la question · Qwen",
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

        if arguments:
            lines.append("")

            for key, value in arguments.items():
                lines.append(f"- `{key}` : `{value}`")

        lines.append("")

    if completed_tools:
        lines.extend([
            "### 2. Préparation de la réponse · Qwen",
            "Qwen dispose des retours d'outils pour préparer une réponse textuelle en français.",
            "",
        ])

    return "\n".join(lines)


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

    message = message.strip()

    if not message:
        yield (
            history,
            state,
            _format_activity([], [], 0.0, "Aucune requête envoyée."),
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

    status = "🧠 **Qwen analyse la question et choisit les outils adaptés…**"
    finished = False
    error: Exception | None = None

    # Affichage immédiat.
    yield (
        pending_history,
        state,
        _format_activity(
            tool_calls,
            completed_tools,
            0.0,
            status,
            timing,
        ),
    )

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
                timing.observe(new_calls, new_responses, time.perf_counter() - start)

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

                if new_responses:
                    completed_tools.extend(new_responses)
                    status = "🧠 **Retour d'outil reçu — Qwen prépare la réponse textuelle…**"

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

        yield (
            pending_history,
            state,
            _format_activity(
                tool_calls,
                completed_tools,
                elapsed,
                status,
                timing,
            ),
        )

    await task

    elapsed = time.perf_counter() - start

    if error is not None:
        response = (
            "Une erreur est survenue pendant l'exécution de l'agent : "
            f"{type(error).__name__}: {error}"
        )

        status = "❌ **Erreur**"

    else:
        response = _final_response_text(events)

        if not response:
            response = "L'agent n'a produit aucune réponse finale."
            status = "⚠️ **Aucune réponse finale**"
        else:
            status = "✅ **Réponse disponible**"

    updated_history = history + [
        {
            "role": "user",
            "content": message,
        },
        {
            "role": "assistant",
            "content": response,
        },
    ]

    yield (
        updated_history,
        state,
        _format_activity(
            tool_calls,
            completed_tools,
            elapsed,
            status,
            timing,
        ),
    )


def new_conversation():
    """Réinitialise complètement la conversation."""

    return (
        [],
        WebSession(),
        _format_activity([], [], 0.0, "En attente d'une question."),
        "",
    )


def build_app() -> gr.Blocks:
    """Construit l'interface web du Pokémon Agent."""

    with gr.Blocks(
        title="Pokémon Agent",
        fill_height=True,
    ) as app:
        with gr.Column(elem_id="app-shell"):
            state = gr.State(WebSession())

            gr.Markdown(
                """
                # Pokémon Agent
                Posez une question et observez comment l'agent utilise ses outils.
                """,
                elem_id="app-heading",
            )

            with gr.Row(equal_height=True, elem_id="workspace"):
                # Conversation
                with gr.Column(scale=3, min_width=320, elem_id="conversation-panel"):
                    chatbot = gr.Chatbot(
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
                            value="",
                            placeholder="Quelles CT Bruyverne apprend-il dans Pokémon Écarlate et Violet ?",
                            label="Votre question",
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
                        example = gr.Button(
                            "🎲 Question d'exemple",
                            size="sm",
                        )

                        clear = gr.Button(
                            "Nouvelle conversation",
                            size="sm",
                        )

                # Activité
                with gr.Column(scale=2, min_width=320, elem_id="agent-panel"):
                    activity = gr.Markdown(
                        _format_activity([], [], 0.0, "En attente d'une question."),
                    )

            # Envoi avec le bouton.
            send.click(
                fn=chat,
                inputs=[
                    message,
                    chatbot,
                    state,
                ],
                outputs=[
                    chatbot,
                    state,
                    activity,
                ],
            ).then(
                fn=lambda: "",
                outputs=message,
            )

            # Envoi avec Entrée.
            message.submit(
                fn=chat,
                inputs=[
                    message,
                    chatbot,
                    state,
                ],
                outputs=[
                    chatbot,
                    state,
                    activity,
                ],
            ).then(
                fn=lambda: "",
                outputs=message,
            )

            # Nouvelle question d'exemple.
            example.click(
                fn=_random_example_question,
                outputs=message,
            )

            # Nouvelle conversation.
            clear.click(
                fn=new_conversation,
                outputs=[
                    chatbot,
                    state,
                    activity,
                    message,
                ],
            )

    return app


demo = build_app()


if __name__ == "__main__":
    demo.launch(
        inbrowser=True,
        theme=gr.themes.Soft(primary_hue="red", secondary_hue="slate"),
        css=APP_CSS,
    )
