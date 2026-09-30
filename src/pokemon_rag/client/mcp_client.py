from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from openai import OpenAI
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


SERVER_MODULE = "pokemon_rag.mcp.server"

LM_STUDIO_BASE_URL = "http://localhost:1234/v1"
MODEL = "qwen/qwen3-vl-8b"

TOOL_SELECTION_PROMPT = """Tu sélectionnes un tool MCP pour répondre à une question sur Pokémon.

Tu reçois la liste des tools disponibles avec leur description et leur schéma JSON.

Réponds uniquement avec un objet JSON de cette forme :
{
  "tool": "nom_du_tool",
  "arguments": {
    "...": "..."
  }
}

Règles :
- utilise uniquement un tool présent dans la liste fournie ;
- respecte exactement son schéma d'entrée ;
- n'invente pas de paramètre ;
- utilise pokemon_rag_search lorsque la question demande une information documentaire
  qui n'est pas couverte par un tool structuré ;
- pour pokemon_rag_search, renseigne "pokemon" lorsqu'un Pokémon unique est explicitement
  identifiable dans la question ;
- ne réponds pas toi-même à la question ;
- aucun texte avant ou après le JSON.
"""

ANSWER_PROMPT = """Tu réponds à une question sur Pokémon à partir du résultat d'un tool MCP.

Règles :
- réponds en français ;
- réponds directement à la question ;
- utilise uniquement les informations présentes dans le résultat du tool ;
- n'invente aucune information absente du résultat ;
- si le résultat ne permet pas de répondre, dis-le clairement ;
- reste concis, sauf si la question demande davantage de détails ;
- ne mentionne pas MCP, le tool, le JSON, la base de données ou le fonctionnement interne ;
- ne recopie pas les champs techniques inutiles.
"""


def create_llm_client() -> OpenAI:
    return OpenAI(
        base_url=LM_STUDIO_BASE_URL,
        api_key="lm-studio",
    )


def build_tools_payload(tools: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
        }
        for tool in tools
    ]


def parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()

    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    start = cleaned.find("{")
    end = cleaned.rfind("}")

    if start == -1 or end == -1 or end < start:
        raise ValueError("Qwen n'a pas retourné d'objet JSON.")

    parsed = json.loads(cleaned[start : end + 1])

    if not isinstance(parsed, dict):
        raise ValueError("La sélection de tool doit être un objet JSON.")

    return parsed


def choose_tool(
    question: str,
    tools: list[Any],
    client: OpenAI,
) -> tuple[str, dict[str, Any]]:
    tools_payload = build_tools_payload(tools)

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": TOOL_SELECTION_PROMPT,
            },
            {
                "role": "user",
                "content": (
                    f"Question : {question}\n\n"
                    "Tools MCP disponibles :\n"
                    f"{json.dumps(tools_payload, ensure_ascii=False, indent=2)}"
                ),
            },
        ],
        temperature=0,
        max_tokens=300,
    )

    content = response.choices[0].message.content or ""
    selection = parse_json_object(content)

    tool_name = selection.get("tool")
    arguments = selection.get("arguments", {})

    if not isinstance(tool_name, str) or not tool_name:
        raise ValueError("Qwen n'a pas sélectionné de tool valide.")

    if not isinstance(arguments, dict):
        raise ValueError("Les arguments du tool doivent être un objet JSON.")

    available_tool_names = {tool.name for tool in tools}

    if tool_name not in available_tool_names:
        raise ValueError(f"Tool MCP inconnu sélectionné par Qwen : {tool_name}")

    return tool_name, arguments


def extract_result(result: Any) -> Any:
    if result.structured_content is not None:
        return result.structured_content

    texts = [
        block.text
        for block in result.content
        if hasattr(block, "text")
    ]

    if len(texts) == 1:
        text = texts[0]

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    return texts


def formulate_answer(
    question: str,
    tool_result: Any,
    client: OpenAI,
) -> str:
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": ANSWER_PROMPT,
            },
            {
                "role": "user",
                "content": (
                    f"Question : {question}\n\n"
                    "Résultat disponible :\n"
                    f"{json.dumps(tool_result, ensure_ascii=False, indent=2)}"
                ),
            },
        ],
        temperature=0,
        max_tokens=400,
    )

    answer = (response.choices[0].message.content or "").strip()

    if not answer:
        raise ValueError("Qwen n'a pas généré de réponse.")

    return answer


async def ask(question: str) -> str:
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", SERVER_MODULE],
    )

    client = create_llm_client()

    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools_result = await session.list_tools()
            tools = tools_result.tools

            tool_name, arguments = choose_tool(
                question=question,
                tools=tools,
                client=client,
            )

            result = await session.call_tool(
                tool_name,
                arguments=arguments,
            )

            if result.is_error:
                raise RuntimeError(f"Le tool MCP {tool_name!r} a retourné une erreur.")

            tool_result = extract_result(result)

            return formulate_answer(
                question=question,
                tool_result=tool_result,
                client=client,
            )


async def main() -> None:
    question = input("Question : ").strip()

    if not question:
        return

    answer = await ask(question)
    print(answer)


if __name__ == "__main__":
    asyncio.run(main())
