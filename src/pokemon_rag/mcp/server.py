"""Outils MCP appelant directement SQLite et la recherche documentaire.

Cette interface ne traverse pas le graphe : génération, contrôle de fidélité
et traces du graphe ne sont pas appliqués ici. Voir README.md dans ce dossier.
Les diagnostics du serveur doivent utiliser stderr pour préserver le stdio MCP.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field

from mcp.server import MCPServer

from pokemon_rag.structured.query_engine import (
    get_evolutions,
    get_level_up_moves,
    get_machine_moves,
    get_move_learning_methods,
    get_pokedex_identity,
    get_pokemon_types,
    get_signature_moves,
    get_pokemon_moves,
    search_pokemon,
)

mcp = MCPServer("Pokemon RAG")


@mcp.tool()
def pokemon_search(
    pokedex_number: int | None = None, generation: int | None = None,
    types: list[str] | None = None, type_match: str = "all",
    legendary: Annotated[bool | None, Field(description="Légendaire uniquement ; indépendant de mythical.")] = None,
    mythical: Annotated[bool | None, Field(description="Fabuleux = true ; ne pas remplacer par legendary.")] = None,
    form: str | None = None, version_group: str | None = None,
    move_type: str | None = None, damage_class: str | None = None,
    min_power: int | None = None, max_power: int | None = None,
    learning_method: str | None = None, min_level: int | None = None,
    max_level: int | None = None,
    limit: Annotated[int, Field(description="Quantité explicite top N : limit=N et best_only=false ; défaut 30, 0 pour compter, maximum 100.")] = 30,
    offset: int = 0,
    sort_by: Annotated[Literal["national_number", "hp", "attack", "defense", "special-attack",
                              "special-defense", "speed", "base-stat-total"],
                       Field(description="Tri SQL : numéro national ou statistique de base ; total = somme des six stats.")] = "national_number",
    sort_order: Annotated[Literal["asc", "desc"],
                          Field(description="asc : minimum/plus lent ; desc : maximum/meilleur/plus rapide.")] = "asc",
    best_only: Annotated[bool, Field(description="Superlatif sans quantité, singulier ou pluriel : true conserve tous les ex aequo au min/max SQL. Top N explicite : false, limit=N.")] = False,
    form_category: Annotated[Literal["mega"] | None,
                             Field(description="mega : toutes les Méga et leurs statistiques, y compris X/Y/Z. null : sémantique de form inchangée.")] = None,
) -> dict[str, Any]:
    """Recherche et classement SQL filtrés. Superlatif sans N, singulier ou pluriel : best_only=true ; top N : best_only=false, limit=N. Méga : form_category=mega. Restituer name_fr et base_stat_value avec stat_name_fr ; égalités via tie/tie_count. Aucun calcul du modèle.

    pokedex_number est le numéro national ; generation est l'origine de l'espèce.
    legendary et mythical sont distincts. types accepte les noms français ou les
    identifiants anglais. type_match : all=possède tous les types (défaut),
    any=au moins un, exact=exactement cette combinaison.
    form absent : forme par défaut ; sinon identifiant de forme ou régional.
    move_type, damage_class (physical/special/status), bornes de puissance,
    learning_method et niveaux sélectionnent les Pokémon pouvant apprendre
    au moins une capacité respectant TOUS ces filtres. Les bornes sont inclusives.
    Sans version_group, utilise le dernier movepool disponible de chaque Pokémon,
    jamais l'union historique. Les propriétés des capacités ne sont pas historisées.
    limit : 0 à 100 (0 pour compter), offset : pagination. total_count est exact,
    truncated signale une liste partielle. Aucun filtre talent n'est disponible.
    Retourne des Pokémon, pas les noms des capacités qui justifient la sélection.
    Pour nommer ces capacités si elles sont demandées, appeler pokemon_moves.
    sort_by : national_number, hp, attack, defense, special-attack,
    special-defense, speed, base-stat-total. Hors IV/EV/nature/niveau/combat.
    best_only : filtre au minimum/maximum SQL, avec best_value et tie_count.
    Les ex aequo restent paginés ; total_count compte les gagnants, matching_count
    les candidats. Top N classique : best_only=false, limit=N.
    form_category=mega utilise is_mega, pas une liste de noms ; inclut X/Y/Z.
    """
    return search_pokemon(
        pokedex_number=pokedex_number, generation=generation, types=types,
        type_match=type_match, legendary=legendary, mythical=mythical, form=form,
        version_group=version_group, move_type=move_type, damage_class=damage_class,
        min_power=min_power, max_power=max_power, learning_method=learning_method,
        min_level=min_level, max_level=max_level, limit=limit, offset=offset,
        sort_by=sort_by, sort_order=sort_order,
        best_only=best_only, form_category=form_category,
    )


@mcp.tool()
def pokemon_moves(
    pokemon: str, form: str | None = None, version_group: str | None = None,
    move_type: str | None = None, damage_class: str | None = None,
    min_power: int | None = None, max_power: int | None = None,
    learning_method: str | None = None, min_level: int | None = None,
    max_level: int | None = None, limit: int = 30, offset: int = 0,
) -> dict[str, Any]:
    """Capacités uniques apprenables par un Pokémon, avec filtres SQL combinables.

    pokemon : nom français, anglais ou PokéAPI ; form : forme explicite, sinon défaut.
    move_type : type français ou identifiant ; damage_class : physical/special/status.
    min_power/max_power inclusifs excluent les puissances inconnues (NULL).
    Une puissance NULL ne signifie jamais statut : seule la catégorie fait foi.
    learning_method : level-up/machine/egg/tutor ou autre identifiant de la base.
    min_level/max_level inclusifs impliquent level-up, incompatibles avec les autres méthodes.
    version_group explicite est strict ; sinon dernier jeu réellement disponible
    pour cette forme, indiqué dans le résultat, avant application des filtres.
    Propriétés actuelles des capacités, sans reconstruction de leurs anciennes valeurs.
    Les méthodes retenues figurent dans learning sans répéter les capacités.
    total_count>0 répond oui à une question « peut-il apprendre une capacité… ? » ;
    total_count=0 répond non pour le movepool local uniquement si movepool_available=true.
    limit : 0 à 100 (0 pour compter), offset : pagination ; truncated indique une liste partielle.
    """
    return get_pokemon_moves(
        pokemon=pokemon, form=form, version_group=version_group, move_type=move_type,
        damage_class=damage_class, min_power=min_power, max_power=max_power,
        learning_method=learning_method, min_level=min_level, max_level=max_level,
        limit=limit, offset=offset,
    )


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
    all_versions: bool = False,
) -> dict[str, Any]:
    """Capacités par niveau : jeu explicite ou dernier jeu avec données ; all_versions=true pour une demande historique multijeux.

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
        all_versions=all_versions,
    )


@mcp.tool()
def pokemon_move_learning_methods(
    pokemon: str,
    move: str,
    form: str | None = None,
    version_group: str | None = None,
    all_versions: bool = False,
) -> dict[str, Any]:
    """Méthodes d'apprentissage : jeu demandé ou dernier movepool disponible ; all_versions=true pour l'historique multijeux.

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
        all_versions=all_versions,
    )


@mcp.tool()
def pokemon_machine_moves(
    pokemon: str,
    form: str | None = None,
    version_group: str | None = None,
    all_versions: bool = False,
) -> dict[str, Any]:
    """CT/CS : jeu demandé ou plus récent avec données de CT ; all_versions=true pour l'historique multijeux.

    Args:
        pokemon: Nom français, anglais ou identifiant PokéAPI du Pokémon.
        form: Forme particulière du Pokémon, si nécessaire.
        version_group: Groupe PokéAPI ; si absent, sélection du plus récent
            avec des données de CT/CS pour le Pokémon et sa forme.
    """
    return get_machine_moves(
        pokemon=pokemon,
        form=form,
        version_group=version_group,
        all_versions=all_versions,
    )


@mcp.tool()
def pokemon_types(
    pokemon: str,
    form: str | None = None,
) -> dict[str, Any]:
    """Retourne seulement les types d'une entrée du Pokédex personnalisé.

    Ne fournit ni apparence ni description physique, comportement ou habitat.
    Pour ces sujets, utiliser pokemon_rag_search.

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
    """Nom → numéro national : pokemon_pokedex_identity(pokemon=nom). Ne pas utiliser pokemon_search pour le numéro d'un Pokémon nommé.

    L'identité comprend notamment son numéro national et sa génération
    d'introduction.

    Direction : nom de Pokémon connu → identité. Pour retrouver le Pokémon
    correspondant à un numéro national, utiliser pokemon_search(pokedex_number=...).
    Ne pas deviner un nom pour appeler cet outil lors d'une recherche par numéro.

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
    from pokemon_rag.rag.retrieval import retrieve
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
