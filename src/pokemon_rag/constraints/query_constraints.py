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

# Libellés de présentation ; les identifiants restent inchangés pour SQL/MCP.
VERSION_GROUP_NAMES_FR = {
    "red-blue":"Pokémon Rouge et Bleu", "yellow":"Pokémon Jaune",
    "gold-silver":"Pokémon Or et Argent", "crystal":"Pokémon Cristal",
    "ruby-sapphire":"Pokémon Rubis et Saphir", "emerald":"Pokémon Émeraude",
    "firered-leafgreen":"Pokémon Rouge Feu et Vert Feuille",
    "diamond-pearl":"Pokémon Diamant et Perle", "platinum":"Pokémon Platine",
    "heartgold-soulsilver":"Pokémon Or HeartGold et Argent SoulSilver",
    "black-white":"Pokémon Noir et Blanc", "black-2-white-2":"Pokémon Noir 2 et Blanc 2",
    "x-y":"Pokémon X et Y", "omega-ruby-alpha-sapphire":"Pokémon Rubis Oméga et Saphir Alpha",
    "sun-moon":"Pokémon Soleil et Lune", "ultra-sun-ultra-moon":"Pokémon Ultra-Soleil et Ultra-Lune",
    "lets-go-pikachu-lets-go-eevee":"Pokémon Let's Go Pikachu et Évoli",
    "sword-shield":"Pokémon Épée et Bouclier", "brilliant-diamond-shining-pearl":"Pokémon Diamant Étincelant et Perle Scintillante",
    "legends-arceus":"Légendes Pokémon : Arceus", "scarlet-violet":"Pokémon Écarlate et Violet",
}

BASE_STAT_NAMES = {
    "hp": "PV", "attack": "Attaque", "defense": "Défense",
    "special-attack": "Attaque Spéciale", "special-defense": "Défense Spéciale",
    "speed": "Vitesse", "base-stat-total": "Total des statistiques",
}

_TYPE_NAMES = {
    "normal":"Normal", "fire":"Feu", "water":"Eau", "electric":"Électrik",
    "grass":"Plante", "ice":"Glace", "fighting":"Combat", "poison":"Poison",
    "ground":"Sol", "flying":"Vol", "psychic":"Psy", "bug":"Insecte",
    "rock":"Roche", "ghost":"Spectre", "dragon":"Dragon", "dark":"Ténèbres",
    "steel":"Acier", "fairy":"Fée",
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


def extract_named_pokemon(question: str, catalogue: list[tuple[str, str, str | None]]) -> dict | None:
    """Mentions exactes avec frontières ; pas de nom déduit ou de matching flou."""
    text = "-" + normalize(question) + "-"
    hits = []
    for alias, species, form in catalogue:
        for match in re.finditer(rf"(?=-{re.escape(normalize(alias))}-)", text):
            hits.append((match.start(), match.start() + len(normalize(alias)) + 1, species, form))
    # Un alias complet de forme contient souvent aussi le nom de l'espèce.
    hits = [hit for hit in hits if not any(other[0] <= hit[0] and hit[1] <= other[1]
            and other[1]-other[0] > hit[1]-hit[0] for other in hits)]
    species = {hit[2] for hit in hits}
    if not species:
        return None
    forms = {hit[3] for hit in hits if hit[3]}
    if len(species) != 1 or len(forms) > 1:
        raise ValueError("Plusieurs Pokémon ou formes explicites : précisez une cible unique.")
    return {"pokemon":species.pop(), **({"form":forms.pop()} if forms else {})}


def is_named_identity_question(question: str) -> bool:
    text = normalize(question)
    return bool(re.search(r"(?:^|-)(?:numero-(?:national|du-pokedex)|(?:numero|identite)-.*pokedex)(?:-|$)", text))


def reconcile_search_args(question: str, arguments: dict) -> dict:
    """Invariants de recherche : classement explicite et classifications indépendantes."""
    result = reconcile_stat_ranking_args(question, arguments)
    text = normalize(question)
    if extract_stat_ranking_args(question) is None:
        # Un tri ne suffit pas à prouver une demande d'optimum.
        if result.get("best_only"):
            if re.search(r"(?:^|-)(?:plus|moins|meilleur|meilleure|minimum|maximum)(?:-|$)", text):
                raise ValueError("Superlatif non reconnu : précisez la statistique ou une quantité.")
            result["best_only"] = False
    classifications = {key for key, token in (("legendary", "legendaires?"), ("mythical", "fabuleux"))
                       if re.search(rf"(?:^|-){token}(?:-|$)", text)}
    if classifications:
        if re.search(r"(?:^|-)(?:non|pas|sans|sauf|hors|ni)-(?:les-|des-|de-)?(?:legendaires?|fabuleux)(?:-|$)|"
                     r"(?:legendaires?|fabuleux)-ou-(?:legendaires?|fabuleux)", text):
            raise ValueError("Classification ambiguë ou négative : précisez les filtres.")
        for key in ("legendary", "mythical"):
            if key in classifications:
                result[key] = True
            else:
                result.pop(key, None)
    return result


def extract_stat_ranking_args(question: str) -> dict | None:
    """Reconnaît des superlatifs explicites, jamais des valeurs ou un classement.

    Hors motifs reconnus, le choix du modèle reste inchangé. Les comparaisons
    entre espèces nommées ne sont pas couvertes. Types = mentions littérales,
    pas inférence depuis un nom d'espèce, une résistance ou une capacité.
    """
    text = normalize(question)
    if (not re.search(r"(?:^|-)(?:pokemons?|megas?|top-?\d+|les-\d+-plus)(?:-|$)", text)
            or re.search(r"(?:^|-)(?:entre|compare|comparaison|page|offset|suivants|suivantes)(?:-|$)", text)):
        return None
    aliases = {normalize(label): identifier for identifier, label in BASE_STAT_NAMES.items()}
    aliases.update({"attaques":"attack", "defenses":"defense",
                    "attaques-speciales":"special-attack", "defenses-speciales":"special-defense"})
    aliases.update({"total-de-statistiques":"base-stat-total", "total-de-base":"base-stat-total",
                    "total-des-statistiques-de-base":"base-stat-total",
                    "total-de-statistiques-de-base":"base-stat-total",
                    "total-des-stats":"base-stat-total", "total-de-stats":"base-stat-total"})
    stat_pattern = "|".join(sorted(aliases, key=len, reverse=True))
    matches = set()
    cues = {
        "asc": r"moins-(?:de|d)|plus-faibles?|pire(?:s)?|minimum-(?:de|d)",
        "desc": r"plus-(?:de|d)|meilleur(?:e|s|es)?|plus-(?:gros|grand|haut|eleve)(?:e|s|es)?",
    }
    for order, cue in cues.items():
        for match in re.finditer(rf"(?:^|-)(?:{cue})-({stat_pattern})(?=-|$)", text):
            matches.add((aliases[match.group(1)], order))
    # « la Défense la plus faible » / « les PV les plus élevés ».
    for match in re.finditer(
            rf"(?:^|-)({stat_pattern})-(?:le|la|les)-(plus-(?:faibles?|bas(?:se|ses)?|"
            rf"eleve(?:e|s|es)?|hauts?|hautes?)|moins-eleve(?:e|s|es)?)(?=-|$)", text):
        cue = match.group(2)
        order = "asc" if any(word in cue for word in ("faible", "bas", "moins")) else "desc"
        matches.add((aliases[match.group(1)], order))
    if re.search(r"(?:^|-)plus-rapides?(?:-|$)", text):
        matches.add(("speed", "desc"))
    if re.search(r"(?:^|-)plus-lent(?:e|s|es)?(?:-|$)", text):
        matches.add(("speed", "asc"))
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError("Classement ambigu : précisez une statistique et un seul ordre.")
    stat, order = matches.pop()
    counts = {int(match.group(1)) for match in re.finditer(
        r"(?:^|-)(?:top-|les-)?(\d+)-(?:pokemons?|megas?)(?:-|$)", text)}
    counts.update(int(match.group(1)) for match in re.finditer(r"(?:^|-)top-?(\d+)(?:-|$)", text))
    counts.update(int(match.group(1)) for match in re.finditer(r"(?:^|-)les-(\d+)-plus(?:-|$)", text))
    if len(counts) > 1 or any(not 1 <= count <= 100 for count in counts):
        raise ValueError("Top N invalide ou ambigu : demandez entre 1 et 100 Pokémon.")
    result = {"sort_by":stat, "sort_order":order, "best_only":not counts,
              "limit":counts.pop() if counts else 30, "offset":0}
    if re.search(r"(?:^|-)megas?(?:-|$)", text):
        result["form_category"] = "mega"
        variants = set(re.findall(r"(?:^|-)mega-([xyz])(?:-|$)", text))
        if len(variants) > 1:
            raise ValueError("Précisez une seule variante Méga pour ce classement.")
        if variants:
            result["form"] = "mega-" + variants.pop()
    return result


def reconcile_stat_ranking_args(question: str, arguments: dict) -> dict:
    """Restaure les motifs reconnus et leurs types littéraux sans comparer de stats."""
    ranking = extract_stat_ranking_args(question)
    corrected = dict(arguments)
    if ranking is None:
        return corrected
    text = normalize(question)
    type_pattern = "|".join({normalize(alias) for identifier, label in _TYPE_NAMES.items()
                            for alias in (identifier, label)})
    type_text = re.sub(rf"(?:attaques?|capacites?)-(?:physiques?-|speciales?-)?"
                       rf"(?:de-types?-)?(?:{type_pattern})(?=-|$)", "-", text)
    types = [identifier for identifier, label in _TYPE_NAMES.items()
             if any(re.search(rf"(?:^|-){re.escape(alias)}(?:-|$)", type_text)
                    for alias in {identifier, normalize(label)})]
    # Dans une question de classement, « en combat » ne définit pas un type Combat.
    if "fighting" in types and re.search(r"(?:^|-)(?:en|au)-combat(?:-|$)", text):
        raise ValueError("Ce classement porte sur les statistiques de base, pas celles en combat.")
    if len(types) > 2:
        raise ValueError("Précisez au plus deux types pour ce classement.")
    if not types and re.search(r"(?:^|-)de-types?-(?:[^-]+)(?:-|$)", type_text):
        raise ValueError("Type demandé non reconnu : précisez son nom.")
    corrected.update(ranking)
    if "form_category" not in ranking:
        corrected.pop("form_category", None)
    if types:
        corrected["types"] = types
        exact = re.search(rf"(?:^|-)(?:monotypes?|purs?|pures?|(?:uniquement|exactement)-"
                          rf"(?:de-)?(?:types?-)?(?:{type_pattern}))(?=-|$)", type_text)
        corrected["type_match"] = "exact" if exact else (
            "any" if re.search(r"(?:^|-)ou(?:-|$)", text) else "all")
    else:
        corrected.pop("types", None)
        corrected.pop("type_match", None)
    if ranking.get("form_category") == "mega" and normalize(corrected.get("form")) == "mega":
        corrected.pop("form")  # Toutes les Méga incluent aussi X/Y/Z.
    return corrected


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
