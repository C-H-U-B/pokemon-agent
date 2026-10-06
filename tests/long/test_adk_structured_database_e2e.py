import asyncio
import json
import time
import re
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pytest
from google.adk.runners import InMemoryRunner
from google.genai import types

from pokemon_rag.agent.agent import root_agent
from pokemon_rag.agent.context_budget import TOOL_FAILURE_ABSTENTION
from pokemon_rag.config import LLM_BASE_URL, LLM_MODEL
from pokemon_rag.constraints.query_constraints import VERSION_GROUP_NAMES_FR, _TYPE_NAMES, normalize


RESULTS_DIR = Path(__file__).resolve().parents[2] / "test_results"
JSONL_PATH = RESULTS_DIR / "adk_structured_database_e2e.jsonl"
REPORT_PATH = RESULTS_DIR / "adk_structured_database_e2e.md"

RUN_ID = datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass(frozen=True)
class Case:
    id: str
    question: str
    expected_tool: str
    expected_args: dict = field(default_factory=dict)
    expected_answer_terms: tuple[str, ...] = ()
    forbidden_answer_terms: tuple[str, ...] = ()
    note: str = ""
    # Aucun fait à restituer : la réponse attendue est l'abstention déterministe de l'agent.
    abstention: bool = False


# Ces tests visent uniquement les données structurées / SQLite.
# Aucun cas ne doit nécessiter pokemon_rag_search.
CASES = [
    # --- Identité / types ---
    Case(
        "types-hexagel",
        "Quels sont les types de Hexagel ?",
        "pokemon_types",
        {"pokemon": "hexagel"},
        ("Glace",),
        note="Type simple.",
    ),
    Case(
        "identity-sinistrail",
        "Quel est le numéro national de Sinistrail ?",
        "pokemon_pokedex_identity",
        {"pokemon": "sinistrail"},
        ("781",),
        note="Nom français -> numéro national.",
    ),
    Case(
        "types-nigirigon",
        "Quels sont les types de Nigirigon ?",
        "pokemon_types",
        {"pokemon": "nigirigon"},
        ("Dragon", "Eau"),
        ("Normal",),
        note="Régression importante : Nigirigon ne doit jamais retomber sur une hallucination Normal.",
    ),

    # --- Évolutions ---
    Case(
        "evolutions-capumain",
        "En quoi Capumain évolue-t-il ?",
        "pokemon_evolutions",
        {"pokemon": "capumain"},
        ("Capidextre",),
    ),
    Case(
        "evolutions-lovdisc",
        "Lovdisc évolue-t-il en un autre Pokémon ?",
        "pokemon_evolutions",
        {"pokemon": "lovdisc"},
        note="Cas sans évolution : la réponse doit provenir de la DB, pas d'une supposition du modèle.",
    ),
    Case(
        "evolutions-leboulerou-steps",
        "En quoi Léboulérou évolue-t-il ?",
        "pokemon_evolutions",
        {"pokemon": "léboulérou"},
        ("Bérasca",),
        note="Gain de niveau sans seuil avec une condition rare (1 000 pas) : ni niveau inventé, "
             "ni condition omise ou niée. Le contrôle générique des conditions accepte « 1 000 ».",
    ),

    # --- Capacités par niveau / CT / méthode ---
    Case(
        "level-opermine-range",
        "Quelles capacités Opermine apprend-il entre les niveaux 10 et 25 ?",
        "pokemon_level_up_moves",
        {"pokemon": "opermine", "min_level": 10, "max_level": 25},
        forbidden_answer_terms=("Fury Swipes", "Slash", "Mud-Slap", "Clamp", "Rock Polish"),
        note="Régression noms anglais + conservation de la plage de niveaux.",
    ),
    Case(
        "machine-gouroutan-sun-moon",
        "Combien de CT Gouroutan peut-il apprendre dans Pokémon Soleil et Lune ?",
        "pokemon_machine_moves",
        {"pokemon": "gouroutan", "version_group": "sun-moon"},
        ("43",),
        note="Jeu explicite -> version_group explicite ; comptage plutôt que 43 lignes à recopier.",
    ),
    Case(
        "learning-method",
        "Par quelles méthodes Concombaffe peut-il apprendre Toxik ?",
        "pokemon_move_learning_methods",
        {"pokemon": "concombaffe", "move":"Toxik"},
        note="Méthodes d'apprentissage d'une capacité précise.",
    ),

    # --- Recherche par numéro / génération / classification ---
    Case(
        "search-national-number",
        "Quel Pokémon porte le numéro 618 du Pokédex national ?",
        "pokemon_search",
        {"pokedex_number": 618},
        ("Limonde",),
    ),
    Case(
        "search-generation-legendary",
        "Quels sont les Pokémon légendaires introduits en quatrième génération ?",
        "pokemon_search",
        {"generation": 4, "legendary": True, "mythical":None},
        note="Composition génération + classification.",
    ),
    Case(
        "search-generation-mythical",
        "Quels sont les Pokémon fabuleux introduits en cinquième génération ?",
        "pokemon_search",
        {"generation": 5, "mythical": True, "legendary":None},
        note="Classification fabuleux distincte de légendaire.",
    ),

    # --- Recherche par type ---
    Case(
        "count-type-ghost",
        "Combien de Pokémon sont de type Spectre ?",
        "pokemon_search",
        {"types":["ghost"],"type_match":"all"},
        ("65",),
        note="Comptage : le total vient du SQL, sans recopier une longue liste.",
    ),
    Case(
        "search-double-type-water-flying",
        "Quels Pokémon sont de type Eau et Vol ?",
        "pokemon_search",
        {"types":["water","flying"],"type_match":"all","best_only":False},
        note="Double type : les deux types doivent être préservés.",
    ),

    # --- Superlatifs / classements connus ---
    Case(
        "legendary-fastest",
        "Quel est le Pokémon légendaire le plus rapide ?",
        "pokemon_search",
        {"legendary": True, "sort_by": "speed", "sort_order": "desc", "best_only": True},
        ("Regieleki", "200"),
        note="Superlatif : la valeur statistique doit apparaître dans la réponse finale.",
    ),
    Case(
        "fire-highest-attack",
        "Quel Pokémon Feu a le plus d'Attaque ?",
        "pokemon_search",
        {"sort_by": "attack", "sort_order": "desc", "best_only": True},
        ("Darumacho", "140"),
        ("Darmanitan",),
        note="Filtre Feu + superlatif + absence du nom anglais.",
    ),
    Case(
        "mega-slowest-tie",
        "Quels sont les Pokémon Méga les plus lents ?",
        "pokemon_search",
        {"form_category": "mega", "sort_by": "speed", "sort_order": "asc", "best_only": True},
        ("Méga-Ténéfix", "Méga-Camérupt", "20"),
        note="Ex æquo : les deux gagnants doivent survivre jusqu'à la réponse finale.",
    ),
    Case(
        "water-flying-best-total",
        "Quel Pokémon Eau/Vol possède le meilleur total de statistiques ?",
        "pokemon_search",
        {"sort_by": "base-stat-total", "sort_order": "desc", "best_only": True},
        ("Léviator", "540"),
        note="Double type + statistique calculée en SQL.",
    ),
    Case(
        "top-five-ghost-special-attack",
        "Quels sont les 5 Pokémon Spectre avec le plus d'Attaque Spéciale ?",
        "pokemon_search",
        {"sort_by": "special-attack", "sort_order": "desc", "best_only": False, "limit": 5},
        note="Filtre type + classement + top N.",
    ),
    Case(
        "legendary-gen4-defense",
        "Quel Pokémon légendaire de quatrième génération a la meilleure Défense ?",
        "pokemon_search",
        {"generation": 4, "legendary": True, "sort_by": "defense", "sort_order": "desc", "best_only": True},
        note="Composition de trois contraintes + superlatif.",
    ),

    # --- Classement croissant avec quantité ---
    Case(
        "rank-slowest",
        "Quels sont les 4 Pokémon les plus lents ?",
        "pokemon_search",
        {"sort_by": "speed", "sort_order": "asc", "best_only": False, "limit": 4},
    ),

    # --- Statistiques et particularités d'un Pokémon nommé ---
    Case(
        "stats-mega-dardargnan",
        "Quelle est la Défense Spéciale de Méga-Dardargnan ?",
        "pokemon_base_stats",
        {"pokemon": "Dardargnan", "form": "beedrill-mega"},
        ("80",),
        ("120",),
        note="Régression : sans outil pour un Pokémon nommé, le modèle répondait 120 de mémoire.",
    ),
    Case(
        "stats-xerneas",
        "Quelles sont les statistiques de base de Xerneas ?",
        "pokemon_base_stats",
        {"pokemon": "xerneas"},
        ("126", "131", "95", "98", "99"),
        ("Paisible",),
        note="Forme par défaut nommée par son espèce ; les six valeurs viennent du résultat.",
    ),
    Case(
        "talents-concombaffe",
        "Quels sont les talents de Concombaffe ?",
        "pokemon_particularities",
        {"pokemon": "concombaffe"},
        ("Expuls’Organes", "Inconscient"),
        note="Talents du tableur, talent caché compris.",
    ),
    Case(
        "particularities-malamandre",
        "En quoi Malamandre est-il particulier ?",
        "pokemon_particularities",
        {"pokemon": "malamandre"},
        ("Corrosion", "Poison"),
        note="Fiche d'unicité : talent signature et double type unique à l'introduction.",
    ),

    # --- Recherche par sous-groupe, talent et stade d'évolution ---
    Case(
        "subgroup-fastest-fossil",
        "Quel est le fossile le plus rapide ?",
        "pokemon_search",
        {"subgroup": "Fossile", "sort_by": "speed", "sort_order": "desc", "best_only": True},
        ("Ptéra", "130"),
        note="Classement sur un sous-groupe, sans le mot « Pokémon » dans la question.",
    ),
    Case(
        "subgroup-pseudo-legendary-gen6",
        "Quels sont les pseudo-légendaires de la sixième génération ?",
        "pokemon_search",
        {"subgroup": "Pseudo-légendaire", "generation": 6, "legendary": None},
        ("Mucuscule", "Colimucus", "Muplodocus"),
        note="Pseudo-légendaire n'est pas légendaire : ce filtre viderait la liste.",
    ),
    Case(
        "search-talent",
        "Quels Pokémon ont le talent Momie ?",
        "pokemon_search",
        {"talent": "Momie"},
        ("Tutafeh", "Tutankafer"),
        note="Recherche inverse par talent ; non protégée par le guard, mesure le modèle seul.",
    ),
    Case(
        "stage-no-evolution-attack",
        "Quel Pokémon sans évolution a le plus d'Attaque ?",
        "pokemon_search",
        {"evolution_stage": "no-evolution", "sort_by": "attack", "sort_order": "desc", "best_only": True},
        ("Katagami", "181"),
        note="Stade d'évolution combiné à un superlatif ; filtre non protégé par le guard.",
    ),

    # --- Pokémon inconnu ---
    Case(
        "unknown-pokemon",
        "Quels sont les types de Fauxkémon ?",
        "pokemon_types",
        {"pokemon": "fauxkémon"},
        note="Aucun résultat d'outil exploitable : abstention, jamais une réponse de mémoire.",
        abstention=True,
    ),

    # --- Movepool filtré ---
    Case(
        "moves-type",
        "Quelles capacités de type Eau Krakos peut-il apprendre ?",
        "pokemon_moves",
        {"pokemon": "krakos", "move_type":"water", "learning_method": None},
        note="Pokémon -> movepool filtré par type.",
    ),
    Case(
        "moves-damage-class",
        "Quelles capacités physiques Sovkipou peut-il apprendre ?",
        "pokemon_moves",
        {"pokemon": "sovkipou", "damage_class":"physical", "learning_method": None},
        note="damage_class doit être appliqué par SQL.",
    ),
    Case(
        "moves-combined",
        "Quelles capacités spéciales de type Eau d'au moins 80 de puissance Nigirigon peut-il apprendre ?",
        "pokemon_moves",
        {"pokemon": "nigirigon", "min_power": 80, "move_type":"water", "damage_class":"special", "learning_method": None},
        note="Composition type + catégorie + puissance.",
    ),
]


def _normalise(value):
    return str(value).strip().casefold()


def _json_safe(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump())
    return repr(value)


async def _run_agent(question: str, events=None, executions=None, raw_responses=None):
    events = [] if events is None else events
    executions = [] if executions is None else executions
    raw_responses = [] if raw_responses is None else raw_responses

    async def before(tool, args, tool_context):
        proposed = deepcopy(args)
        refusal = root_agent.before_tool_callback(tool=tool,args=args,tool_context=tool_context)
        declaration = tool._get_declaration()
        properties = (declaration.parameters_json_schema or {}).get("properties",{})
        defaults = {key:deepcopy(value["default"]) for key,value in properties.items() if "default" in value}
        effective = {**defaults, **args}
        executions.append({"name":tool.name,"proposed_args":proposed,"proposed_effective_args":{**defaults, **proposed},
                           "args":deepcopy(args),"effective_args":deepcopy(effective),
                           "blocked":refusal is not None,"guard_response":deepcopy(refusal)})
        return refusal

    async def after(tool,args,tool_context,tool_response):
        last = next((call for call in reversed(executions) if call["name"] == tool.name),None)
        raw_responses.append({"name":tool.name,"origin":"guard" if last and last["blocked"] else "mcp",
                              "response":_json_safe(deepcopy(tool_response))})
        return root_agent.after_tool_callback(tool=tool,args=args,tool_context=tool_context,tool_response=tool_response)

    agent = root_agent.model_copy(update={"before_tool_callback":before,"after_tool_callback":after})
    runner = InMemoryRunner(agent=agent)
    session = await runner.session_service.create_session(
        app_name=runner.app_name,
        user_id="structured_database_e2e",
    )
    message = types.Content(role="user", parts=[types.Part(text=question)])
    start = time.perf_counter()

    try:
        async for event in runner.run_async(user_id="structured_database_e2e",
                session_id=session.id,new_message=message):
            events.append(event)
        return events,time.perf_counter()-start,executions,raw_responses
    finally:
        await runner.close()


def _final_text(events):
    for event in reversed(events):
        if event.is_final_response() and event.content is not None:
            return "".join(part.text or "" for part in event.content.parts).strip()
    return ""


def _calls(events, executions=()):
    if executions:
        return [{"name":call["name"],"args":deepcopy(call["proposed_args"]),
                 "effective_args":deepcopy(call.get("proposed_effective_args",call["proposed_args"]))}
                for call in executions]
    result = []
    for event in events:
        if event.content is None:
            continue
        for part in event.content.parts:
            if part.function_call is not None:
                result.append({
                    "name": part.function_call.name,
                    "args": dict(part.function_call.args or {}),
                })
    return result


def _responses(events):
    result = []
    for event in events:
        if event.content is None:
            continue
        for part in event.content.parts:
            if part.function_response is not None:
                result.append({
                    "name": part.function_response.name,
                    "response": _json_safe(part.function_response.response),
                })
    return result


def _first_call(calls, tool):
    return next((call for call in calls if call["name"] == tool), None)


def _response_for(responses, tool):
    matches = [r for r in responses if r["name"] == tool]
    return matches[-1]["response"] if matches else None


def _arg_matches(actual, expected, key=None):
    if key == "move_type" and isinstance(actual,str) and isinstance(expected,str):
        return _arg_matches([actual],[expected],"types")
    if key == "damage_class" and isinstance(actual,str) and isinstance(expected,str):
        aliases = {"physique":"physical","speciale":"special","statut":"status"}
        return aliases.get(normalize(actual),normalize(actual)) == aliases.get(normalize(expected),normalize(expected))
    if key == "types" and isinstance(actual,list) and isinstance(expected,list):
        def canonical(value):
            return next((identifier for identifier,label in _TYPE_NAMES.items()
                         if normalize(value) in {identifier,normalize(label)}),normalize(value))
        return {canonical(value) for value in actual} == {canonical(value) for value in expected}
    if isinstance(expected, str):
        return _normalise(actual) == _normalise(expected)
    return actual == expected


def _proposal_checks(case,calls):
    """Diagnostic de la proposition brute ; un argument omis vaut son défaut de schéma."""
    call = _first_call(calls,case.expected_tool)
    proposed = call.get("effective_args",call["args"]) if call else {}
    return [(call is not None and _arg_matches(proposed.get(key),expected,key),
             f"Proposition Qwen {key}={expected!r}",
             f"Proposition Qwen {key}: attendu={expected!r}, obtenu={proposed.get(key)!r}")
            for key,expected in case.expected_args.items()]


def _english_additions(pairs,answer):
    """Un libellé français peut contenir un mot anglais : le retirer avant la recherche."""
    for french,_ in sorted(pairs,key=lambda pair:-len(pair[0])):
        answer = re.sub(re.escape(french),"",answer,flags=re.I)
    return [(french,english,bool(re.search(rf"(?<!\w){re.escape(english)}(?!\w)",answer,re.I)))
            for french,english in pairs]


def _localized_pairs(value):
    if isinstance(value,list):
        return [pair for item in value for pair in _localized_pairs(item)]
    if not isinstance(value,dict):
        return []
    pairs = []
    for key,item in value.items():
        french = value.get(key[:-3]+"_fr") if key.endswith("_en") else value.get("fr") if key == "en" else None
        if isinstance(item,str) and french and item.casefold() != str(french).casefold():
            pairs.append((str(french),item))
    return pairs + [pair for item in value.values() for pair in _localized_pairs(item)]


_DAY_PARTS = {"day": r"jour(?:née)?|diurne", "jour": r"jour(?:née)?|diurne", "night": r"nuit|nocturne", "nuit": r"nuit|nocturne"}


def _evolution_condition_checks(result, answer):
    """Chaque condition renvoyée pour une évolution doit se retrouver dans la réponse.

    Contrôle par valeur, quel que soit le nom de la clé : nombre, nom français, moment de la
    journée. Limité aux résultats courts, où omettre une condition rend la réponse trompeuse.
    Il ne détecte pas une condition citée puis niée dans la même phrase.
    """
    evolutions = result.get("evolutions") or []
    if result.get("operation") != "get_evolutions" or not 0 < len(evolutions) <= 3:
        return []
    # « 1 000 » et « 1000 » désignent le même nombre.
    text = re.sub(r"(?<=\d)[\s\u00a0\u202f](?=\d{3}(?!\d))", "", answer)
    checks = []
    for evolution in evolutions:
        for key, value in (evolution.get("conditions") or {}).items():
            if isinstance(value, dict):
                value = value.get("fr")
            if type(value) in {int, float} and value > 1:  # 1 est un simple indicateur (rocher spécial…)
                present = bool(re.search(rf"(?<!\d){re.escape(str(value))}(?!\d)", text))
            elif isinstance(value, str) and normalize(value) in _DAY_PARTS:
                present = bool(re.search(rf"\b(?:{_DAY_PARTS[normalize(value)]})\b", text, re.I))
            elif isinstance(value, str) and value:
                present = value.casefold() in text.casefold()
            else:
                continue
            checks.append((present, f"Condition restituée : {key}={value}", f"Condition omise : {key}={value}"))
    return checks


def _factual_checks(result, answer):
    """Contrôles typés limités, pas un juge général de toute formulation libre."""
    checks = []
    answer = re.sub(r"[*_`]", "", answer)
    def values(value, keys):
        if isinstance(value, dict):
            return [item for key,item in value.items() if key in keys and type(item) in {int,float}] + [
                item for nested in value.values() for item in values(nested,keys)]
        if isinstance(value,list):
            return [item for nested in value for item in values(nested,keys)]
        return []
    levels = values(result.get("moves",[]), {"level"}) + values(result.get("methods",[]),{"level"})
    levels += values(result.get("results",[]), {"level"})  # pokemon_moves : niveaux dans learning
    levels += values(result.get("evolutions",[]), {"minimum_level", "niveau minimum"})
    for match in re.finditer(r"\bniveau\s*(?:de\s*)?(\d+)\b",answer,re.I):
        level = int(match.group(1))
        checks.append((level in levels,f"Niveau {level} prouvé",f"Niveau {level} absent du résultat outil"))
    for french,english,added in _english_additions(_localized_pairs(result),answer):
        checks.append((not added,f"Libellé français privilégié : {french}",f"Nom anglais ajouté : {english}"))
    checks.extend(_evolution_condition_checks(result, answer))
    def games(value):
        if isinstance(value,dict):
            return [value["version_group"]] if isinstance(value.get("version_group"),str) else [
                version for item in value.values() for version in games(item)]
        if isinstance(value,list):
            return [version for item in value for version in games(item)]
        return []
    for version in set(games(result)):
        if (version in VERSION_GROUP_NAMES_FR and not all(len(word) == 1 for word in version.split("-"))
                and normalize(version) not in normalize(VERSION_GROUP_NAMES_FR[version])):
            english_pattern = r"(?<!\w)" + r"(?:\s*(?:&|and|-)\s*|\s+)".join(
                re.escape(word) for word in version.split("-")) + r"(?!\w)"
            checks.append((not re.search(english_pattern,answer,re.I),
                f"Jeu présenté en français : {VERSION_GROUP_NAMES_FR[version]}",f"Nom anglais du jeu ajouté : {version}"))
    def stat_value(row):
        return row.get("base_stat_value", row.get(result.get("stat_name_fr")))
    if result.get("operation") == "search_pokemon":
        require_all = bool(result.get("stat_name_fr")) or len(result.get("results",[])) <= 10
        if result.get("results"):
            checks.append((any(str(row.get("name_fr", "")).casefold() in answer.casefold()
                               for row in result["results"] if row.get("name_fr")),
                           "Réponse nomme un résultat SQL", "Réponse ne nomme aucun résultat SQL"))
        for row in result.get("results",[]):
            for value in (row.get("name_fr"),stat_value(row)):
                if value is not None and require_all:
                    present = (bool(re.search(rf"(?<!\d){re.escape(str(value))}(?!\d)",answer))
                               if type(value) in {int,float} else str(value).casefold() in answer.casefold())
                    checks.append((present,f"Résultat final restitue {value!r}",f"Résultat final omet {value!r}"))
        stat = result.get("stat_name_fr")
        if stat:
            allowed = {stat_value(row) for row in result.get("results",[])}
            # Espaces horizontaux seulement : le rang de la ligne suivante n'est pas une valeur.
            for match in re.finditer(rf"{re.escape(stat)}[^\S\n]*(?:de[^\S\n]*base[^\S\n]*)?(?:[:=]|de)?[^\S\n]*(\d+)\b",answer,re.I):
                value = int(match.group(1))
                checks.append((value in allowed,f"{stat} {value} prouvé",f"{stat} {value} absent du résultat SQL"))
    elif result.get("stat_name_fr"):
        for row in result.get("results",[]):
            for value in (row.get("name_fr"),stat_value(row)):
                if value is not None:
                    present = bool(re.search(rf"(?<!\d){re.escape(str(value))}(?!\d)",answer))
                    checks.append((present,f"Classement restitue {value!r}",f"Classement omet {value!r}"))
    return checks


def _semantic_checks(case, calls, responses, answer, executions, raw_responses=()):
    checks = []

    rag_calls = [c for c in calls if c["name"] == "pokemon_rag_search"]
    checks.append((
        not rag_calls,
        "Aucun appel RAG",
        f"RAG appelé {len(rag_calls)} fois",
    ))
    if case.abstention:
        return checks + [(answer == TOOL_FAILURE_ABSTENTION, "Abstention déterministe",
                          f"Réponse au lieu d'une abstention : {answer[:120]!r}")]

    call = next((call for call in reversed(executions)
                 if call["name"] == case.expected_tool and not call["blocked"]),None)
    checks.append((
        call is not None,
        f"Outil attendu exécuté : {case.expected_tool}",
        f"Outil attendu absent ; appels={[c['name'] for c in calls]}",
    ))

    tool_response = _response_for(responses, case.expected_tool)
    if call is not None:
        for key, expected in case.expected_args.items():
            actual = call.get("effective_args",call["args"]).get(key)
            if key == "move" and isinstance(tool_response, dict):
                actual = tool_response.get("move", {}).get("name_fr", actual)
            checks.append((
                _arg_matches(actual, expected,key),
                f"Argument exécuté {key}={expected!r}",
                f"Argument exécuté {key}: attendu={expected!r}, obtenu={actual!r}",
            ))

    checks.append((
        tool_response is not None,
        "Réponse MCP reçue",
        "Aucune réponse MCP pour l'outil attendu",
    ))

    if tool_response is not None:
        checks.append((not tool_response.get("error"),"Résultat MCP sans erreur",f"Erreur MCP : {tool_response.get('error')}"))
        checks.extend(_factual_checks(tool_response,answer))
    raw = next((r["response"] for r in reversed(raw_responses)
                if r["name"] == case.expected_tool and r.get("origin") == "mcp"),None)
    if raw:
        raw_data = raw.get("structuredContent",raw.get("structured_content"))
        if not isinstance(raw_data,dict) and len(raw.get("content",[])) == 1:
            try:
                raw_data = json.loads(raw["content"][0].get("text",""))
            except (ValueError,TypeError):
                raw_data = None
        if isinstance(raw_data,dict):
            for french,english,added in _english_additions(_localized_pairs(raw_data),answer):
                checks.append((not added,f"Libellé français : {french}",f"Nom anglais ajouté : {english}"))

    checks.append((
        bool(answer) and "Je n'ai pas pu obtenir une réponse fiable" not in answer,
        "Réponse finale hors abstention de budget",
        "Réponse finale vide ou abstention de budget",
    ))

    answer_folded = answer.casefold()
    for term in case.expected_answer_terms:
        checks.append((
            term.casefold() in answer_folded,
            f"Réponse finale contient {term!r}",
            f"Réponse finale ne contient pas {term!r}",
        ))

    for term in case.forbidden_answer_terms:
        checks.append((
            term.casefold() not in answer_folded,
            f"Réponse finale n'expose pas {term!r}",
            f"Terme interdit présent dans la réponse : {term!r}",
        ))

    return checks


def _format_value(value):
    if isinstance(value, (dict, list)):
        return "```json\n" + json.dumps(value, ensure_ascii=False, indent=2) + "\n```"
    return f"`{value}`"


def _append_report(case, elapsed, calls, responses, answer, checks, error=None,
                   executions=(),raw_responses=(),proposal_checks=()):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    passed = error is None and all(ok for ok, _, _ in checks)

    with REPORT_PATH.open("a", encoding="utf-8") as f:
        f.write(f"\n## {case.id}\n\n")
        f.write(f"**Question :** {case.question}\n\n")
        f.write(f"**Statut :** {'✅ PASS' if passed else '❌ FAIL'}  \n")
        f.write(f"**Durée :** {elapsed:.2f} s\n\n")
        if case.note:
            f.write(f"**But :** {case.note}\n\n")

        f.write("### Appels proposés par Qwen\n\n")
        if calls:
            for call in calls:
                f.write(f"- `{call['name']}`\n")
                f.write("```json\n")
                f.write(json.dumps(call["args"], ensure_ascii=False, indent=2))
                f.write("\n```\n")
        else:
            f.write("_Aucun function call._\n\n")

        f.write("### Arguments après guard\n\n" + _format_value(list(executions)) + "\n\n")
        f.write("### Qualité de proposition Qwen (diagnostic)\n\n")
        for ok,success,failure in proposal_checks:
            f.write(f"- {'✅' if ok else '⚠️'} {success if ok else failure}\n")
        f.write("\n### Résultats MCP bruts avant adaptation ADK\n\n" + _format_value(list(raw_responses)) + "\n\n")
        f.write("### Résultats transmis à Qwen\n\n")
        if responses:
            for response in responses:
                f.write(f"#### `{response['name']}`\n\n")
                f.write(_format_value(response["response"]))
                f.write("\n\n")
        else:
            f.write("_Aucune function response._\n\n")

        f.write("### Réponse finale du LLM\n\n")
        if answer:
            f.write("```text\n")
            f.write(answer)
            f.write("\n```\n\n")
        else:
            f.write("_Aucune réponse finale._\n\n")

        f.write("### Vérifications automatiques\n\n")
        for ok, success, failure in checks:
            f.write(f"- {'✅' if ok else '❌'} {success if ok else failure}\n")

        if error:
            f.write(f"\n### Exception\n\n`{error}`\n")

        f.write("\n---\n")


def _append_jsonl(case, elapsed, calls, responses, answer, checks, error=None,
                  executions=(),raw_responses=(),proposal_checks=()):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "run_id": RUN_ID,
        "model": LLM_MODEL, "server": LLM_BASE_URL,
        "case_id": case.id,
        "question": case.question,
        "elapsed_seconds": round(elapsed, 3),
        "tool_calls": calls,
        "tool_responses": responses,
        "executed_calls":executions,"raw_mcp_responses":raw_responses,
        "proposal_checks":[{"passed":ok,"message":success if ok else failure} for ok,success,failure in proposal_checks],
        "final_answer": answer,
        "checks": [
            {"passed": ok, "message": success if ok else failure}
            for ok, success, failure in checks
        ],
        "passed": error is None and all(ok for ok, _, _ in checks),
        "error": error,
    }
    with JSONL_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _initialise_report():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        "# Rapport E2E — Base structurée Pokémon\n\n"
        f"**Run :** {RUN_ID}  \n"
        f"**Modèle :** {LLM_MODEL} sur {LLM_BASE_URL}  \n"
        f"**Nombre de cas :** {len(CASES)}\n\n"
        "Ce rapport est destiné à la revue humaine. Il contient les questions, "
        "les propositions Qwen (diagnostic), les arguments après guard, les retours bruts "
        "et adaptés et les réponses finales. Une proposition réparée ne fait pas échouer "
        "le verdict fonctionnel ; une erreur ou une réponse incorrecte échoue. "
        "Les tests de ce fichier ne doivent jamais utiliser le RAG.\n\n"
        "> Un PASS automatique ne remplace pas la lecture de la réponse finale : "
        "le but du rapport est aussi de repérer une formulation incorrecte, une "
        "information superflue ou une fuite de terminologie anglaise.\n\n"
        "---\n",
        encoding="utf-8",
    )


@pytest.fixture(scope="session", autouse=True)
def human_report():
    _initialise_report()




_PROGRESS = {"done": 0, "started": False}


def _print_progress(case_id: str, *, completed: bool = False) -> None:
    """Progression visible même avec la capture de sortie de pytest."""
    total = len(CASES)

    if completed:
        _PROGRESS["done"] += 1

    done = _PROGRESS["done"]
    width = 30
    filled = int(width * done / total)
    bar = "█" * filled + "░" * (width - filled)
    percent = 100 * done / total

    if not _PROGRESS["started"]:
        print(
            f"\nE2E base structurée: [{bar}] {done}/{total} ({percent:5.1f}%)",
            flush=True,
        )
        _PROGRESS["started"] = True

    if completed:
        print(
            f"E2E base structurée: [{bar}] {done}/{total} "
            f"({percent:5.1f}%) · terminé: {case_id}",
            flush=True,
        )
    else:
        print(
            f"→ en cours: {case_id}",
            flush=True,
        )


@pytest.mark.models
@pytest.mark.real_data
@pytest.mark.llm
@pytest.mark.long
@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_structured_database_e2e(case):
    _print_progress(case.id)
    events = []
    elapsed = 0.0
    calls = []
    responses = []
    answer = ""
    checks = []
    executions,raw_responses,proposal_checks = [],[],[]

    try:
        events, elapsed, executions, raw_responses = asyncio.run(_run_agent(case.question,events,executions,raw_responses))
        calls = _calls(events,executions)
        responses = _responses(events)
        answer = _final_text(events)
        proposal_checks = _proposal_checks(case,calls)
        checks = _semantic_checks(case, calls, responses, answer,executions,raw_responses)

        failed = [failure for ok, _, failure in checks if not ok]
        assert not failed, (
            f"{case.id} : " + " | ".join(failed)
            + f" | Réponse finale={answer!r}"
        )

    except Exception as exc:
        if not checks:
            calls,responses,answer = _calls(events,executions),_responses(events),_final_text(events)
            proposal_checks = _proposal_checks(case,calls)
            checks = _semantic_checks(case, calls, responses, answer,executions,raw_responses)
        error = f"{type(exc).__name__}: {exc}"
        _append_report(case, elapsed, calls, responses, answer, checks, error,executions,raw_responses,proposal_checks)
        _append_jsonl(case, elapsed, calls, responses, answer, checks, error,executions,raw_responses,proposal_checks)
        _print_progress(case.id, completed=True)
        raise

    _append_report(case, elapsed, calls, responses, answer, checks,
                   executions=executions,raw_responses=raw_responses,proposal_checks=proposal_checks)
    _append_jsonl(case, elapsed, calls, responses, answer, checks,
                  executions=executions,raw_responses=raw_responses,proposal_checks=proposal_checks)
    _print_progress(case.id, completed=True)
