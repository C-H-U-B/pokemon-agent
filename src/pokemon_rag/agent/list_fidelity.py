"""Fidélité d'une réponse à une liste structurée entièrement transmise au modèle.

Qwen peut retirer des lignes en les déclarant hors du résultat, même quand la propriété lui est
rappelée (trio des lacs déclaré « non légendaire » 3 fois sur 4). Une réponse qui omet ou nie une
ligne est remplacée par la liste construite depuis les données, sans nouvel appel au modèle.
Contrôle lexical : il voit les noms absents et les négations d'appartenance courantes, pas toutes
les tournures (« ce sont des évolutions »).
"""
from __future__ import annotations

import re
from typing import Any

# Phrase qui nie l'appartenance d'un élément au résultat : « ne sont pas des légendaires », « à tort ».
# Une négation sur une autre propriété (« Kartana, qui n'évolue pas ») ne compte pas.
DENIAL = re.compile(r"\b(?:ne|n['’])\s*(?:\w+\s+)?(?:sont|est|font|fait|figurent|figure|appartiennent|appartient|"
                    r"comptent|compte)\s+pas\b|\bà\s+tort\b|\bexclus?\b", re.I)
# Au-delà, la page n'est plus contrôlée : c'est la page par défaut des recherches.
MAX_ROWS = 30
LIST_TOOLS = {"pokemon_search": "Pokémon", "pokemon_moves": "capacités"}
REPLACEMENT_PREFIX = "D'après les données locales"


def fold(text: Any) -> str:
    """Casse et apostrophe typographique ignorées : « Expuls'Organes » vaut « Expuls’Organes »."""
    return str(text).casefold().replace("’", "'")


def affirmed(name: str, answer: str) -> bool:
    """Le nom figure dans au moins un passage qui ne nie pas son appartenance au résultat."""
    return any(fold(name) in fold(part) and not DENIAL.search(part)
               # Un point ne coupe qu'après un mot de trois lettres : « M. Mime » reste entier.
               # Pas de coupure aux parenthèses : « Les trois premiers (Créhelf, …) ne sont pas
               # légendaires » isolait les noms de leur négation.
               for part in re.split(r"[!?;\n]|(?<=\w\w\w)\.(?=\s|$)", answer))


def complete_list(tool_name: str, result: dict) -> dict | None:
    """Liste à contrôler : lignes d'un outil de liste, toutes transmises au modèle, sans erreur."""
    rows = result.get("results")
    if (tool_name not in LIST_TOOLS or result.get("error") or result.get("context_truncated")
            or not isinstance(rows, list) or not 0 < len(rows) <= MAX_ROWS):
        return None
    statistic = result.get("stat_name_fr")
    names = [row["name_fr"] for row in rows if isinstance(row, dict) and row.get("name_fr")]
    if len(names) != len(rows):
        return None
    return {"noun": LIST_TOOLS[tool_name], "names": names, "total": result.get("total_count", len(names)),
            "statistic": statistic, "values": [row.get(statistic) for row in rows] if statistic else None}


def unfaithful_names(listing: dict, answer: str) -> list[str]:
    """Lignes transmises que la réponse omet ou nie."""
    return [name for name in listing["names"] if not affirmed(name, answer)]


def render(listing: dict) -> str:
    """Réponse construite depuis les données seules."""
    items = [f"{name} ({listing['statistic']} : {value})" if listing["statistic"] and value is not None else name
             for name, value in zip(listing["names"], listing["values"] or [None] * len(listing["names"]))]
    shown, total = len(items), listing["total"]
    head = (f"{REPLACEMENT_PREFIX}, {total} {listing['noun']} correspondent à la question"
            + (f" ; voici les {shown} premiers" if total > shown else ""))
    return f"{head} : " + ", ".join(items) + "."
