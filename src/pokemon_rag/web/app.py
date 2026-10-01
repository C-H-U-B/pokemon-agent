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
EXAMPLE_QUESTIONS_PATH = Path(__file__).with_name("example_questions.txt")


@dataclass
class WebSession:
    """État propre à une conversation Gradio."""

    user_id: str = field(default_factory=lambda: f"web_{uuid.uuid4().hex}")


runner = InMemoryRunner(agent=root_agent)


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
) -> str:
    """Construit le panneau d'activité temps réel."""

    lines = [
        "## Agent activity",
        "",
        f"### ⏱ {elapsed_seconds:.1f} s",
        "",
        status,
        "",
    ]

    if not tool_calls:
        lines.append("**Tool :** aucun pour le moment")
        return "\n".join(lines)

    completed_counts: dict[str, int] = {}

    for name in completed_tools:
        completed_counts[name] = completed_counts.get(name, 0) + 1

    displayed_counts: dict[str, int] = {}

    for index, (name, arguments) in enumerate(tool_calls, start=1):
        displayed_counts[name] = displayed_counts.get(name, 0) + 1

        is_completed = displayed_counts[name] <= completed_counts.get(name, 0)

        icon = "✅" if is_completed else "🔧"

        if len(tool_calls) > 1:
            lines.append(f"### {icon} Appel {index} — `{name}`")
        else:
            lines.append(f"### {icon} `{name}`")

        if arguments:
            lines.append("")

            for key, value in arguments.items():
                lines.append(f"- `{key}` : `{value}`")

        lines.append("")

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
            "## Agent activity\n\nAucune requête envoyée.",
        )
        return

    content = types.Content(
        role="user",
        parts=[
            types.Part(text=message),
        ],
    )

    start = time.perf_counter()

    events = []
    tool_calls: list[tuple[str, dict]] = []
    completed_tools: list[str] = []

    queue: asyncio.Queue = asyncio.Queue()

    task = asyncio.create_task(
        _run_agent_into_queue(
            state=state,
            content=content,
            queue=queue,
        )
    )

    status = "🧠 **L'agent analyse la question...**"
    finished = False
    error: Exception | None = None

    # Affichage immédiat.
    yield (
        history,
        state,
        _format_activity(
            tool_calls,
            completed_tools,
            0.0,
            status,
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

                if new_calls:
                    tool_calls.extend(new_calls)
                    status = "🔧 **Exécution d'un outil...**"

                if new_responses:
                    completed_tools.extend(new_responses)
                    status = "🧠 **Résultat reçu — génération de la réponse...**"

            elif item_type == "error":
                error = payload
                status = "❌ **Erreur pendant l'exécution.**"

            elif item_type == "done":
                finished = True

        except asyncio.TimeoutError:
            # Aucun nouvel événement ADK :
            # on rafraîchit quand même le chrono.
            pass

        elapsed = time.perf_counter() - start

        yield (
            history,
            state,
            _format_activity(
                tool_calls,
                completed_tools,
                elapsed,
                status,
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

        status = "✅ **Terminé**"

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
        ),
    )


def new_conversation():
    """Réinitialise complètement la conversation."""

    return (
        [],
        WebSession(),
        "## Agent activity\n\nNouvelle conversation.",
        _random_example_question(),
    )


def build_app() -> gr.Blocks:
    """Construit l'interface web du Pokémon Agent."""

    with gr.Blocks(
        title="Pokémon Agent",
        fill_height=True,
    ) as app:
        state = gr.State(WebSession())

        gr.Markdown(
            """
            # Pokémon Agent
            Assistant Pokémon local — **Qwen · ADK · MCP**
            """
        )

        with gr.Row(equal_height=True):
            # Conversation
            with gr.Column(scale=3):
                with gr.Row():
                    message = gr.Textbox(
                        value=_random_example_question(),
                        placeholder="Posez une question sur un Pokémon...",
                        label=None,
                        lines=1,
                        scale=6,
                    )

                    send = gr.Button(
                        "Envoyer",
                        variant="primary",
                        scale=1,
                    )

                with gr.Row():
                    example = gr.Button(
                        "🎲 Autre exemple",
                        size="sm",
                    )

                    clear = gr.Button(
                        "Nouvelle conversation",
                        size="sm",
                    )

                chatbot = gr.Chatbot(
                    label="Conversation",
                    height=480,
                )

            # Activité
            with gr.Column(scale=2):
                activity = gr.Markdown(
                    """
                    ## Agent activity

                    En attente d'une question.
                    """
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
    )
