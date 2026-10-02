from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


REGION_FORMS = {
    "alola": "alola",
    "galar": "galar",
    "hisui": "hisui",
    "paldea": "paldea",
}

VERSION_ALIASES = {
    "rouge": "red-blue",
    "bleu": "red-blue",
    "rouge-et-bleu": "red-blue",
    "red": "red-blue",
    "blue": "red-blue",
    "red-and-blue": "red-blue",
    "diamant": "diamond-pearl",
    "perle": "diamond-pearl",
    "diamant-et-perle": "diamond-pearl",
    "diamond": "diamond-pearl",
    "pearl": "diamond-pearl",
    "diamond-and-pearl": "diamond-pearl",
    "soleil": "sun-moon",
    "lune": "sun-moon",
    "soleil-et-lune": "sun-moon",
    "sun": "sun-moon",
    "moon": "sun-moon",
    "sun-and-moon": "sun-moon",
    "epee": "sword-shield",
    "bouclier": "sword-shield",
    "epee-et-bouclier": "sword-shield",
    "sword": "sword-shield",
    "shield": "sword-shield",
    "sword-and-shield": "sword-shield",
    "ecarlate": "scarlet-violet",
    "violet": "scarlet-violet",
    "ecarlate-et-violet": "scarlet-violet",
    "scarlet": "scarlet-violet",
    "scarlet-and-violet": "scarlet-violet",
    "ev": "scarlet-violet",
}


@dataclass(frozen=True)
class ExplicitConstraints:
    form: str | None
    version_group: str | None
    version_ambiguous: bool
    explicit_game: bool
    level_bounds: tuple[int | None, int | None] | None
    level_explicit: bool


def normalize(text: str | None) -> str:
    if text is None:
        return ""
    value = unicodedata.normalize("NFKD", str(text))
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = value.casefold()
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-")


def extract_form(question: str) -> str | None:
    normalized = normalize(question)
    matches = [
        form
        for token, form in REGION_FORMS.items()
        if re.search(rf"(?:^|-){re.escape(token)}(?:-|$)", normalized)
    ]
    return matches[0] if len(matches) == 1 else None


def has_explicit_game(question: str) -> bool:
    normalized = normalize(question)
    padded = f"-{normalized}-"
    if any(f"-{alias}-" in padded for alias in VERSION_ALIASES):
        return True
    return bool(
        re.search(
            r"(?:^|-)(?:dans|in|version|versions|jeu|jeux|(?:en|sur)-pokemon)(?:-|$)",
            normalized,
        )
    )


def extract_version_group(
    question: str,
    known_version_groups: set[str] | None = None,
) -> tuple[str | None, bool]:
    normalized = normalize(question)
    padded = f"-{normalized}-"
    matches = {
        value
        for alias, value in VERSION_ALIASES.items()
        if f"-{alias}-" in padded
    }
    if len(matches) > 1:
        return None, True
    if len(matches) == 1:
        return next(iter(matches)), False

    direct = {
        identifier
        for identifier in (known_version_groups or set())
        if f"-{normalize(identifier)}-" in padded
    }
    if len(direct) > 1:
        return None, True
    if direct:
        return next(iter(direct)), False
    return None, has_explicit_game(question)


def extract_level_bounds(question: str) -> tuple[int | None, int | None] | None:
    normalized = normalize(question)
    range_patterns = [
        r"(?:entre)-(?:les-)?niveaux-(\d+)-et-(\d+)",
        r"(?:entre)-(?:le-)?niveau-(\d+)-et-(?:le-)?niveau-(\d+)",
    ]

    for pattern in range_patterns:
        match = re.search(r"(?:^|-)(?:" + pattern + r")(?=-|$)", normalized)
        if match:
            minimum = int(match.group(1))
            maximum = int(match.group(2))

            if minimum > maximum:
                raise ValueError("Intervalle de niveaux impossible.")

            return minimum, maximum
    if re.search(r"(?:^|-)(?:ou|or)(?:-|$)", normalized):
        return None

    patterns = [
        (r"(?:apres|after)-(?:le-)?(?:niveau|level)-(\d+)", "min", 1),
        (r"(?:a-partir-du|a-partir-de|from)-(?:niveau|level)-(\d+)", "min", 0),
        (r"(?:avant|before)-(?:le-)?(?:niveau|level)-(\d+)", "max", -1),
        (r"(?:jusqu-au|jusqu-a|jusque-au|jusque-a)-(?:niveau|level)-(\d+)", "max", 0),
        (r"(?:au|a|at)-(?:niveau|level)-(\d+)", "exact", 0),
    ]

    lower: list[int] = []
    upper: list[int] = []
    spans: list[tuple[int, int]] = []
    for pattern, kind, offset in patterns:
        for match in re.finditer(r"(?:^|-)(?:" + pattern + r")(?=-|$)", normalized):
            if any(start <= match.start(1) < end for start, end in spans):
                continue
            spans.append(match.span())
            value = int(match.group(1)) + offset
            if kind in {"min", "exact"}:
                lower.append(value)
            if kind in {"max", "exact"}:
                upper.append(value)

    if not spans:
        return None

    remaining = list(normalized)
    for start, end in spans:
        remaining[start:end] = " " * (end - start)
    if re.search(r"\d|\b(?:niveau|niveaux|level|levels)\b", "".join(remaining)):
        return None

    minimum = max(lower) if lower else None
    maximum = min(upper) if upper else None
    if maximum is not None and (maximum < 0 or (minimum is not None and minimum > maximum)):
        raise ValueError("Intervalle de niveaux impossible.")
    return minimum, maximum


def extract_national_pokedex_number(question: str) -> int | None:
    """Numéro explicite en contexte Pokémon/Pokédex, sans résolution d'espèce.

    Reconnaît numéro/n°/no suivis de chiffres, pas les nombres isolés de
    niveau ou génération. Refuse plusieurs numéros distincts et les Pokédex
    régionaux, qui ne doivent pas devenir un numéro national.
    """
    normalized = normalize(question)
    if not re.search(r"(?:^|-)(?:pokemon|pokedex)(?=-|$)", normalized):
        return None
    numbers = {int(value) for value in re.findall(
        r"(?:^|-)(?:numeros?-(?:national-)?|n-?|no-?)(\d+)(?=-|$)", normalized)}
    if not numbers:
        return None
    numbers.update(int(value) for value in re.findall(r"(?:^|-)(?:ou|et|a)-(\d+)(?=-|$)", normalized))
    if re.search(r"(?:num[eé]ros?|n[°º]|no)\s*-\s*\d", question, re.IGNORECASE):
        raise ValueError("Le numéro national doit être strictement positif.")
    if re.search(r"(?:^|-)pokedex-(?:regional|de|d|kanto|johto|hoenn|sinnoh|unys|kalos|alola|galar|hisui|paldea)(?=-|$)", normalized):
        raise ValueError("Ce numéro concerne un Pokédex régional, pas le Pokédex national.")
    if len(numbers) != 1 or 0 in numbers:
        raise ValueError("Précisez un seul numéro national strictement positif.")
    return numbers.pop()


def extract_explicit_constraints(
    question: str,
    known_version_groups: set[str] | None = None,
) -> ExplicitConstraints:
    normalized = normalize(question)
    level_explicit = bool(
        re.search(r"(?:^|-)(?:niveau|niveaux|level|levels)(?:-|$)", normalized)
        and re.search(r"(?:^|-)\d+(?:-|$)", normalized)
    )
    version_group, version_ambiguous = extract_version_group(
        question,
        known_version_groups=known_version_groups,
    )
    return ExplicitConstraints(
        form=extract_form(question),
        version_group=version_group,
        version_ambiguous=version_ambiguous,
        explicit_game=has_explicit_game(question),
        level_bounds=extract_level_bounds(question),
        level_explicit=level_explicit,
    )
