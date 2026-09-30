"""Outils MCP appelant directement SQLite et la recherche documentaire.

Cette interface ne traverse pas le graphe : génération, contrôle de fidélité
et traces du graphe ne sont pas appliqués ici. Voir README.md dans ce dossier.
Les diagnostics du serveur doivent utiliser stderr pour préserver le stdio MCP.
"""

from __future__ import annotations

from typing import Any

from mcp.server import MCPServer

from pokemon_rag.structured.query_engine import (
    get_evolutions,
    get_level_up_moves,
    get_machine_moves,
    get_move_learning_methods,
    get_pokedex_identity,
    get_pokemon_types,
    get_signature_moves,
)

from pokemon_rag.rag.retrieval import retrieve

mcp = MCPServer("Pokemon RAG")


@mcp.tool()
def pokemon_evolutions(
    pokemon: str,
    form: str | None = None,
    version_group: str | None = None,
) -> dict[str, Any]:
    """Retourne les évolutions connues d'un Pokémon.

    Args:
        pokemon: Nom français, anglais ou identifiant PokéAPI du Pokémon.
        form: Forme particulière du Pokémon, si nécessaire.
        version_group: Groupe de versions PokéAPI à utiliser comme filtre.
    """
    return get_evolutions(
        pokemon=pokemon,
        form=form,
        version_group=version_group,
    )


@mcp.tool()
def pokemon_level_up_moves(
    pokemon: str,
    form: str | None = None,
    version_group: str | None = None,
    min_level: int | None = None,
    max_level: int | None = None,
) -> dict[str, Any]:
    """Retourne les capacités apprises par montée de niveau par un Pokémon.

    Args:
        pokemon: Nom français, anglais ou identifiant PokéAPI du Pokémon.
        form: Forme particulière du Pokémon, si nécessaire.
        version_group: Groupe de versions PokéAPI à utiliser comme filtre.
        min_level: Niveau minimum inclusif.
        max_level: Niveau maximum inclusif.
    """
    return get_level_up_moves(
        pokemon=pokemon,
        form=form,
        version_group=version_group,
        min_level=min_level,
        max_level=max_level,
    )


@mcp.tool()
def pokemon_move_learning_methods(
    pokemon: str,
    move: str,
    form: str | None = None,
    version_group: str | None = None,
) -> dict[str, Any]:
    """Retourne les méthodes permettant à un Pokémon d'apprendre une capacité.

    Args:
        pokemon: Nom français, anglais ou identifiant PokéAPI du Pokémon.
        move: Nom français, anglais ou identifiant PokéAPI de la capacité.
        form: Forme particulière du Pokémon, si nécessaire.
        version_group: Groupe de versions PokéAPI à utiliser comme filtre.
    """
    return get_move_learning_methods(
        pokemon=pokemon,
        move=move,
        form=form,
        version_group=version_group,
    )


@mcp.tool()
def pokemon_machine_moves(
    pokemon: str,
    form: str | None = None,
    version_group: str | None = None,
) -> dict[str, Any]:
    """Retourne les capacités apprises par CT ou CS par un Pokémon.

    Args:
        pokemon: Nom français, anglais ou identifiant PokéAPI du Pokémon.
        form: Forme particulière du Pokémon, si nécessaire.
        version_group: Groupe de versions PokéAPI à utiliser comme filtre.
    """
    return get_machine_moves(
        pokemon=pokemon,
        form=form,
        version_group=version_group,
    )


@mcp.tool()
def pokemon_types(
    pokemon: str,
    form: str | None = None,
) -> dict[str, Any]:
    """Retourne les types d'une entrée du Pokédex personnalisé.

    Args:
        pokemon: Nom du Pokémon ou de l'entrée du Pokédex.
        form: Forme particulière du Pokémon, si nécessaire.
    """
    return get_pokemon_types(
        pokemon=pokemon,
        form=form,
    )


@mcp.tool()
def pokemon_pokedex_identity(
    pokemon: str,
    form: str | None = None,
) -> dict[str, Any]:
    """Retourne l'identité Pokédex d'un Pokémon.

    L'identité comprend notamment son numéro national et sa génération
    d'introduction.

    Args:
        pokemon: Nom du Pokémon ou de l'entrée du Pokédex.
        form: Forme particulière du Pokémon, si nécessaire.
    """
    return get_pokedex_identity(
        pokemon=pokemon,
        form=form,
    )


@mcp.tool()
def pokemon_signature_moves(
    pokemon: str,
    form: str | None = None,
) -> dict[str, Any]:
    """Retourne les capacités signature et pseudo-signature renseignées.

    Args:
        pokemon: Nom du Pokémon ou de l'entrée du Pokédex.
        form: Forme particulière du Pokémon, si nécessaire.
    """
    return get_signature_moves(
        pokemon=pokemon,
        form=form,
    )

@mcp.tool()
def pokemon_rag_search(
    question: str,
    pokemon: str | None = None,
) -> dict[str, Any]:
    """Recherche des informations dans le corpus documentaire Poképédia.

    Renvoie des passages sourcés, pas une réponse générée ou validée.
    Une liste vide ne prouve pas l'absence du fait recherché dans le domaine.

    Args:
        question: Information à rechercher dans le corpus.
        pokemon: Nom canonique du Pokémon lorsque la recherche doit être
            strictement limitée à celui-ci.
    """
    results = retrieve(
        question=question,
        pokemon = pokemon.strip() if pokemon and pokemon.strip() else None,
    )

    if not results:
        return {
            "question": question,
            "pokemon": pokemon,
            "results": [],
        }

    context_results = results[0].get("context_results") or results

    documents = []

    for result in context_results:
        metadata = result.get("metadata") or {}

        documents.append(
            {
                "text": result.get("document", ""),
                "pokemon": metadata.get("pokemon"),
                "source_file": metadata.get("source_file"),
                "section_path": (
                    metadata.get("section_path")
                    or metadata.get("section")
                ),
                "chunk_number": metadata.get("chunk_number"),
            }
        )

    return {
        "question": question,
        "pokemon": pokemon,
        "results": documents,
    }


if __name__ == "__main__":
    mcp.run()
