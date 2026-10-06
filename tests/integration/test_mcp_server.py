from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pokemon_rag.agent.tool_guard import before_tool_guard


SERVER_MODULE = "pokemon_rag.mcp.server"
EXPECTED_TOOLS = {
    "pokemon_evolutions",
    "pokemon_level_up_moves",
    "pokemon_move_learning_methods",
    "pokemon_machine_moves",
    "pokemon_types",
    "pokemon_pokedex_identity",
    "pokemon_signature_moves",
    "pokemon_base_stats",
    "pokemon_particularities",
    "pokemon_rag_search",
    "pokemon_search",
    "pokemon_moves",
}


@pytest.mark.real_data
def test_mcp_server_discovers_tools_and_executes_real_structured_tool() -> None:
    """Valide le serveur MCP réel via stdio, sans LLM ni mocks."""
    asyncio.run(_check_server())


async def _check_server() -> None:
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", SERVER_MODULE],
    )

    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=60) as session:
            await session.initialize()

            tools_result = await session.list_tools()
            tools = {tool.name: tool for tool in tools_result.tools}

            assert set(tools) == EXPECTED_TOOLS

            # Nouveaux outils nommés : appel réel à travers stdio, forme comprise.
            stats = await session.call_tool("pokemon_base_stats", arguments={"pokemon": "Dardargnan", "form": "beedrill-mega"})
            assert not stats.is_error
            assert stats.structured_content["rows"][0]["Défense Spéciale"] == 80
            facts = await session.call_tool("pokemon_particularities", arguments={"pokemon": "Dracolosse"})
            assert facts.structured_content["rows"][0]["Sous-groupe"] == "Pseudo-légendaire"
            unknown = await session.call_tool("pokemon_base_stats", arguments={"pokemon": "Fauxkémon"})
            assert unknown.is_error

            schema = tools["pokemon_search"].input_schema["properties"]
            stage = next(option for option in schema["evolution_stage"]["anyOf"] if "enum" in option)
            assert set(stage["enum"]) == {"base", "intermediate", "final", "no-evolution", "baby"}
            fossil = await session.call_tool("pokemon_search", arguments={
                "subgroup": "fossile", "sort_by": "speed", "sort_order": "desc", "best_only": True})
            assert fossil.structured_content["results"][0]["name_fr"] == "Ptéra"
            holders = await session.call_tool("pokemon_search", arguments={"talent": "Multiécaille"})
            assert [row["name_fr"] for row in holders.structured_content["results"]] == ["Dracolosse", "Lugia"]
            wrong = await session.call_tool("pokemon_search", arguments={"subgroup": "pseudo"})
            assert wrong.is_error  # valeur inconnue : erreur, pas liste vide
            assert set(schema["sort_by"]["enum"]) == {
                "national_number", "hp", "attack", "defense", "special-attack",
                "special-defense", "speed", "base-stat-total"}
            assert set(schema["sort_order"]["enum"]) == {"asc", "desc"}
            assert "ex aequo" in schema["best_only"]["description"]
            mega = await session.call_tool("pokemon_search", arguments={
                "form_category":"mega", "sort_by":"attack", "sort_order":"desc", "best_only":True})
            assert not mega.is_error
            assert mega.structured_content["results"][0]["name_fr"] == "Méga-Mewtwo X"
            assert mega.structured_content["best_value"] == 190
            total = await session.call_tool("pokemon_search", arguments={
                "types":["Eau","Vol"], "type_match":"exact", "sort_by":"base-stat-total",
                "sort_order":"desc", "best_only":True})
            assert not total.is_error and total.structured_content["best_value"] == 540
            tied = await session.call_tool("pokemon_search", arguments={
                "form_category":"mega", "sort_by":"speed", "sort_order":"asc", "best_only":True, "limit":1})
            assert not tied.is_error and tied.structured_content["tie_count"] == 2
            assert tied.structured_content["returned_count"] == 1
            for invalid_args in ({"sort_by":"sql"}, {"sort_order":"sideways"}, {"form_category":"unknown"}):
                assert (await session.call_tool("pokemon_search", arguments=invalid_args)).is_error

            search = await session.call_tool("pokemon_search", arguments={"pokedex_number": 369})
            assert not search.is_error
            assert search.structured_content["results"][0]["name_fr"] == "Relicanth"
            moves = await session.call_tool("pokemon_moves", arguments={
                "pokemon": "Scarhino", "version_group": "scarlet-violet",
                "damage_class": "physical", "min_power": 100, "limit": 1})
            assert not moves.is_error
            assert moves.structured_content["results"][0]["power"] >= 100
            assert moves.structured_content["truncated"]
            invalid = await session.call_tool("pokemon_search", arguments={"types": ["inconnu"]})
            assert invalid.is_error

            pokemon_types = tools["pokemon_types"]
            assert pokemon_types.input_schema["type"] == "object"
            assert "pokemon" in pokemon_types.input_schema["properties"]
            assert "pokemon" in pokemon_types.input_schema["required"]

            result = await session.call_tool(
                "pokemon_types",
                arguments={"pokemon": "Pikachu"},
            )

            assert not result.is_error
            assert result.structured_content is not None

            data = result.structured_content
            nigirigon = await session.call_tool(
                "pokemon_types", arguments={"pokemon": "Nigirigon"}
            )
            assert not nigirigon.is_error
            assert nigirigon.structured_content["rows"][0]["type_1_fr"] == "Dragon"
            assert nigirigon.structured_content["rows"][0]["type_2_fr"] == "Eau"

            missing = await session.call_tool(
                "pokemon_types", arguments={"pokemon": "Espèce inexistante"}
            )
            assert missing.is_error

            assert data["operation"] == "get_pokemon_types"
            assert data["pokemon"].casefold() == "pikachu"
            assert data["count"] == len(data["rows"]) == 1

            row = data["rows"][0]

            assert row["name_fr"].casefold() == "pikachu"
            assert row["type_1_fr"] == "Électrik"
            assert row["type_2_fr"] is None


@pytest.mark.real_data
def test_guard_constraints_reach_real_mcp_and_sql_without_model():
    """Guard réel → client/stdio/serveur réels → SQLite, sans génération.

    Risque distinct des unités : noms canoniques et arguments réparés doivent
    être acceptés par les signatures MCP et produire des lignes filtrées.
    """
    async def run():
        server = StdioServerParameters(command=sys.executable,args=["-m",SERVER_MODULE])
        async with stdio_client(server) as (read,write):
            async with ClientSession(read,write,read_timeout_seconds=60) as session:
                await session.initialize()
                tools = {tool.name:tool for tool in (await session.list_tools()).tools}

                async def guarded_call(question,name,args):
                    context = SimpleNamespace(user_content=SimpleNamespace(parts=[SimpleNamespace(text=question)]))
                    refusal = before_tool_guard(tools[name],args,context)
                    assert refusal is None, refusal
                    assert set(args) <= set(tools[name].input_schema["properties"])
                    result = await session.call_tool(name,arguments=args)
                    assert not result.is_error, result
                    return result.structured_content

                moves = await guarded_call(
                    "Quelles capacités physiques de type Eau d'au moins 80 de puissance Krakos peut-il apprendre dans Pokémon Épée ?",
                    "pokemon_moves",{"pokemon":"Gourgeist","damage_class":"special","move_type":"fire","min_power":120})
                assert moves["pokemon"] == "Krakos" and moves["results"]
                assert {row["name_fr"] for row in moves["results"]} == {"Aqua-Brèche","Cascade","Plongée"}
                assert all(row["damage_class_id"] == 2 and row["type_fr"] == "Eau" and row["power"] >= 80
                           for row in moves["results"])

                special = await guarded_call(
                    "Quelles capacités spéciales de type Eau d'au moins 80 de puissance Nigirigon peut-il apprendre dans Pokémon Écarlate ?",
                    "pokemon_moves",{"pokemon":"Wrong species","damage_class":"physical","max_power":80})
                assert special["results"] and all(row["damage_class_id"] == 3 and row["power"] >= 80
                                                   for row in special["results"])
                assert special["total_count"] == 3

                question = "Quel Pokémon porte le numéro 618 du Pokédex national ?"
                context = SimpleNamespace(user_content=SimpleNamespace(parts=[SimpleNamespace(text=question)]))
                rejected = before_tool_guard(tools["pokemon_pokedex_identity"],{"pokemon":"Gigalith"},context)
                assert rejected["error"] == "unsupported_pokedex_number_constraint"
                identity = await guarded_call(question,rejected["required_tool"],rejected["required_arguments"])
                assert identity["results"][0]["national_number"] == 618
                assert identity["results"][0]["name_fr"] == "Limonde"

                mythical = await guarded_call("Les Pokémon mythiques de cinquième génération",
                    "pokemon_search",{"generation":4,"legendary":True,"mythical":False})
                assert mythical["results"]
                assert all(row["generation"] == 5 and row["mythical"] and not row["legendary"]
                           for row in mythical["results"])

                top = await guarded_call("Quels sont les 5 Pokémon les plus rapides ?",
                    "pokemon_search",{"sort_by":"defense","best_only":True,"limit":1})
                assert top["returned_count"] == 5 and not top["best_only"]
                assert top["results"][0]["name_fr"] == "Regieleki"

                form = await guarded_call("Quels sont les types de Motisma Lavage ?",
                    "pokemon_types",{"pokemon":"Gourgeist","form":"heat"})
                assert form["rows"][0]["type_1_fr"] == "Électrik"
                assert form["rows"][0]["type_2_fr"] == "Eau"
    asyncio.run(run())
