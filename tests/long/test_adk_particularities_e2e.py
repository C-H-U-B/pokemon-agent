"""Campagne E2E des particularités : vrai agent, vrai modèle, fiche du tableur.

Séparée de la campagne structurée, qui ne couvre que les rubriques fermées (talents, sous-groupe,
double type unique). Ici, une question par sorte de fait que portent les rubriques en texte libre,
pour distinguer trois pannes : la fiche n'est pas demandée (mauvais outil), la rubrique n'arrive pas,
ou elle arrive et la réponse la restitue mal. Les termes attendus viennent du tableur ; ce qu'ils ne
peuvent pas juger (sens d'un rang, date d'une mise en avant) se relit dans le rapport.
"""
import asyncio
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pytest
from test_adk_documentary_e2e import _ask, _parts

from pokemon_rag.agent.context_budget import BUDGET_ABSTENTION, DOUBLE_REQUEST_REFUSAL, TOOL_FAILURE_ABSTENTION
from pokemon_rag.config import LLM_BASE_URL, LLM_MODEL

JSONL_PATH = Path(__file__).resolve().parents[2] / "test_results" / "adk_particularities_e2e.jsonl"
REPORT_PATH = JSONL_PATH.with_suffix(".md")
RUN_ID = datetime.now().astimezone().isoformat(timespec="seconds")
FICHE = "pokemon_particularities"
STATS, OBTAINING, HIGHLIGHT = "Statistiques remarquables", "Rencontre ou obtention à l'introduction", "Mise en avant à l'introduction"
MOVEPOOL, OTHER, GENDER = "Particularité du movepool", "Autre particularité", "Différences selon le sexe"
# Fiche réduite aux rubriques que tout Pokémon possède : le tableur ne note rien de particulier (49 fiches).
NOTHING = "une particularité"
WEAK, IMMUNE, PAST_ABILITY = "Faiblesses de type", "Immunités de type", "Ancien talent"
HELD_ITEMS, GIGANTAMAX, MISSING_GAMES = "Objets tenus à l'état sauvage", "Gigamax", "Jeux sans ce Pokémon depuis son introduction"
# Les rubriques calculées depuis PokéAPI en font partie : presque toute fiche en porte, ce ne sont pas des particularités notées.
COMMON = {"name_fr", "Type 1", "Type 2", "Talent 1", "Talent 2", "Talent caché", "Stade d'évolution",
          "Taille", "Poids", "Taux de capture", WEAK, "Résistances de type", IMMUNE, PAST_ABILITY,
          "Anciennes statistiques", HELD_ITEMS, GIGANTAMAX, MISSING_GAMES}
# Ce qu'une réponse ne peut ni affirmer ni nier quand la fiche n'en dit rien.
UNRECORDED = (r"Méga-Évolutions?", r"légendaires?", r"fabuleux", r"records?", r"signatures?", r"Paradoxe", r"formes? alternatives?")


@dataclass(frozen=True)
class Case:
    id: str
    question: str
    rubric: str
    # Expressions régulières cherchées dans la réponse, sans casse, bornées aux mots.
    expected: tuple[str, ...] = ()
    forbidden: tuple[str, ...] = ()
    note: str = ""
    # Le tableur ne note rien dans cette rubrique : la réponse ne doit ni affirmer ni inventer.
    absent: bool = False


CASES = [
    # --- Statistiques remarquables : notation réécrite en clair par le moteur ---
    Case("stats-extreme-ranks", "Quelles sont les statistiques remarquables de Caratroc ?", STATS, ("230", "5"), ("Bottom", "#"),
         "Régression : l'outil des statistiques de base était appelé, la fiche n'était pas lue."),
    Case("stats-rank-direction", "Les PV de Rattata sont-ils parmi les plus élevés ou les plus bas ?", STATS, (r"bas(se)?s?", "30"), ("#",),
         "Sens du rang : « PV #6 (30) » recopié sans « Bottom 10 » se lisait comme un bon score."),
    Case("stats-drop-on-evolution", "Papilusion a-t-il perdu des statistiques en évoluant ?", STATS, ("Défense", "55", "50"), (),
         "Régression : l'outil des évolutions était appelé et la question prise à l'envers."),
    Case("stats-generation-record", "Mewtwo détient-il des records de statistiques dans sa génération ?", STATS, ("154", "680")),
    Case("stats-balanced-spread", "La répartition des statistiques de Mew a-t-elle quelque chose de remarquable ?", STATS,
         ("100", r"équilibr\w*")),
    Case("stats-prime-numbers", "Qu'ont de remarquable les statistiques de Cosmog ?", STATS, ("premiers",)),
    Case("stats-rank-among-megas", "Quelles sont les statistiques remarquables de Méga-Dracaufeu X ?", STATS, ("634", "85"), ("#",),
         "Rangs calculés parmi les Méga-Évolutions, sur une forme nommée."),
    # --- Rencontre ou obtention à l'introduction ---
    Case("obtaining-fixed-encounter", "Comment obtenait-on Mewtwo à sa sortie ?", OBTAINING, ("Caverne Azurée",)),
    Case("obtaining-version-exclusive", "Dans quelle version pouvait-on obtenir Abo à sa sortie ?", OBTAINING, ("Rouge",)),
    Case("obtaining-event-only", "Comment obtenait-on Mew à sa sortie ?", OBTAINING, (r"événements?",)),
    # --- Mise en avant à l'introduction ---
    Case("highlight-trainer", "Quel dresseur mettait Dracaufeu en avant à sa sortie ?", HIGHLIGHT, ("Régis",)),
    Case("highlight-later-exception", "Quel dresseur mettait Noadkoko en avant à sa sortie ?", OTHER, ("Rubépin",), ("Miyazaki",),
         "Régression : la recherche documentaire était appelée et une préfecture donnée pour dresseur. "
         "Le tableur range maintenant ce fait dans « Autre particularité », daté de la neuvième génération. "
         "À relire : la réponse ne doit pas situer Rubépin à la sortie de Noadkoko."),
    Case("highlight-story-legendary", "Quel rôle Reshiram avait-il dans le scénario à sa sortie ?", HIGHLIGHT, ("Noir",)),
    # --- Particularité du movepool ---
    Case("movepool-coverage", "Qu'a de particulier le movepool de Léviator ?", MOVEPOOL, ("Tonnerre", "Laser Glace")),
    Case("movepool-single-move", "Qu'a de particulier le movepool de Métamorph ?", MOVEPOOL, ("Morphing",)),
    # --- Autre particularité : rubrique fourre-tout, un cas par sorte de fait ---
    Case("other-former-type", "Rondoudou a-t-il toujours été de type Fée ?", "Ancien type", ("Normal",), (),
         "L'outil des types ne connaît que les types actuels : l'historique n'est que dans la fiche."),
    Case("other-paradox-counterpart", "Magnéton a-t-il un équivalent Paradoxe ?", OTHER, ("Pelage-Sablé",)),
    Case("other-mega-evolution", "Depuis quelle génération Dracaufeu a-t-il une Méga-Évolution ?", OTHER,
         (r"G6|6e génération|sixième génération|génération 6",)),
    Case("other-fusion", "Avec quels Pokémon Sylveroy peut-il fusionner ?", OTHER, ("Blizzeval", "Spectreval")),
    Case("other-record", "Quel record Évoli détient-il ?", OTHER, (r"huit|8",)),
    Case("other-no-workbook-wording", "Qu'a de particulier Rattata ?", OTHER, ("formes",), ("classeur", "#"),
         "Régression : « formes alternatives recensées dans ce classeur » était servi à l'utilisateur."),
    # --- Différences selon le sexe ---
    Case("gender-difference", "Y a-t-il une différence entre Léviator mâle et femelle ?", GENDER, ("bleus", "blancs")),
    Case("gender-difference-not-recorded", "Ronflex a-t-il une différence physique selon le sexe ?", GENDER, (),
         (r"aucune différence", r"pas de différence", r"ne présente"),
         "Régression : la recherche documentaire était appelée et l'absence affirmée (« Non, aucune différence »). "
         "Une rubrique absente veut dire que le tableur ne note rien, pas que le fait est faux.", absent=True),
    # --- Pokémon sans particularité : la fiche ne contient que types, talents et stade ---
    Case("nothing-special", "Qu'a de particulier Barbicha ?", NOTHING, ("Benêt",), UNRECORDED,
         "Rien de noté : la réponse restitue les talents et le stade, sans inventer ni nier une particularité.", absent=True),
    Case("nothing-special-yes-no", "Tropius a-t-il quelque chose d'unique ?", NOTHING, (), UNRECORDED,
         "Question fermée sur une fiche vide : ni « oui » inventé, ni « non » tiré d'une absence. À relire.", absent=True),
    # --- Rubriques fermées que la campagne structurée ne pose pas sous cette forme ---
    Case("unique-type-pair", "Léviator avait-il une combinaison de types unique à sa sortie ?",
         "Double type unique à l'introduction", ("Eau", "Vol")),
    Case("signature-talent", "Quel est le talent signature de Métamorph ?", "Talent signature", ("Imposteur",)),
    Case("evolution-stage", "À quel stade d'évolution est Rondoudou ?", "Stade d'évolution", (r"intermédiaire",)),
    # --- Mesures PokéAPI jointes à la fiche : l'unité est portée par la valeur ---
    Case("measure-weight", "Combien pèse Ronflex ?", "Poids", (r"460(,0)?", r"kg|kilogrammes?"), (r"4\s?600", "hectogrammes?"),
         "La base stocke 4600 hectogrammes : la réponse doit donner 460 kg."),
    Case("measure-capture-rate", "Mewtwo est-il facile à capturer ?", "Taux de capture",
         ("3", r"difficile|pas facile|faible|bas"), (),
         "Sens du taux : 3 sur 255 est le plus bas. La conclusion (difficile) est à relire, le contrôle ne lit que des mots."),
    # --- Rubriques calculées depuis PokéAPI : une question par rubrique, le cas le plus discriminant ---
    Case("type-weakness-combined", "Quelles sont les faiblesses de Dracaufeu ?", WEAK, ("Roche", "Eau", "Électrik"), (),
         "Double type : Roche compte quatre fois, et le Sol, efficace sur le Feu, n'est pas une faiblesse (immunité du Vol). "
         "À relire : le Sol ne doit pas être donné pour une faiblesse."),
    Case("type-immunity", "Ectoplasma craint-il les attaques de type Normal ?", IMMUNE,
         (r"immunis\w*|immunités?|aucun effet|insensible|n'affectent? pas",), (r"faible au type Normal", r"super efficaces?"),
         "Une immunité se lit dans sa propre rubrique ; le type Normal n'est ni une faiblesse ni une résistance."),
    Case("type-weakness-one-ability", "Smogogo est-il faible au Sol ?", WEAK, ("Lévitation",), (),
         "Un seul des talents annule la faiblesse : la fiche donne « Sol (×2 ; immunisé seulement s'il a le talent Lévitation) ». "
         "À relire : ni « oui » sans le talent, ni « non, immunisé » sans condition."),
    Case("past-ability","Ectoplasma a-t-il toujours eu le même talent ?", PAST_ABILITY, ("Lévitation", "Corps Maudit"),
         (r"^Oui", "G1", r"introduction", r"remplac\w+(?:(?!jusqu)[^.])*(?:génération 6|G6)"),
         "L'ancien talent est daté par sa dernière génération (G6) et celle du changement (G7). Régression : « Oui, toujours "
         "le même talent », puis « à l'introduction (G1), remplacé à la génération 6 », deux fois sur deux."),
    Case("held-item", "Quel objet un Pikachu sauvage peut-il tenir ?", HELD_ITEMS, ("Balle Lumière",), ("Light Ball",)),
    Case("missing-games", "Dans quels jeux Abo est-il absent ?", MISSING_GAMES, (r"Épée",), (r"Version (?:2|X)", r"plus disponible", r"supprimé", r"Sword"),
         "Absences déduites des capacités apprises par jeu. À relire : Écarlate et Violet ne doit pas être cité comme une absence."),
    Case("gigantamax", "Dracaufeu a-t-il une forme Gigamax ?", GIGANTAMAX, ("Gigamax", r"Épée"), (r"pas de forme Gigamax", r"n'a pas")),
]


def _found(term: str, answer: str) -> bool:
    return re.search(rf"(?<!\w)(?:{term})(?!\w)", answer, re.IGNORECASE) is not None


def _checks(case: Case, calls: list[dict], responses: list[dict], answer: str) -> list[tuple[bool, str]]:
    sheets = [row for response in responses if response["name"] == FICHE and isinstance(response["response"], dict)
              for row in response["response"].get("rows") or []]
    called = any(call["name"] == FICHE for call in calls)
    checks = [(called, "fiche des particularités demandée")]
    if called:
        received = any(set(row) - COMMON if case.rubric == NOTHING else case.rubric in row for row in sheets)
        checks.append((received != case.absent, f"rubrique « {case.rubric} » {'absente' if case.absent else 'reçue'}"))
    checks.append((bool(answer) and answer not in (BUDGET_ABSTENTION, DOUBLE_REQUEST_REFUSAL, TOOL_FAILURE_ABSTENTION),
                   "réponse rédigée"))
    checks += [(_found(term, answer), f"réponse contient « {term} »") for term in case.expected]
    checks += [(not _found(term, answer), f"réponse sans « {term} »") for term in case.forbidden]
    return checks


def write_report(run_id: str = RUN_ID) -> None:
    """Rapport lisible d'une exécution, réécrit après chaque cas : outils appelés, fiche reçue, réponse."""
    rows = [json.loads(line) for line in JSONL_PATH.read_text(encoding="utf-8").splitlines()]
    rows = [row for row in rows if row["run_id"] == run_id]
    if not rows:
        return
    wrong_tool = sum(not row["checks"][0]["passed"] for row in rows)
    lines = [f"# Campagne des particularités — {run_id}", "",
             f"**Modèle :** {rows[0]['model']} sur {rows[0]['server']}  ",
             f"**Réussis :** {sum(row['passed'] for row in rows)} sur {len(rows)}  ",
             f"**Fiche non demandée :** {wrong_tool} ; **fiche demandée mais réponse en échec :** "
             f"{sum(not row['passed'] for row in rows) - wrong_tool}", ""]
    for row in rows:
        lines += [f"## {'✅' if row['passed'] else '❌'} {row['case_id']}", "",
                  f"**Question :** {row['question']}  ", f"**Rubrique :** {row['rubric']}  ",
                  f"**Durée :** {row['elapsed_seconds']:.0f} s", ""]
        if row["note"]:
            lines.append(f"- But : {row['note']}")
        for call in row["tool_calls"]:
            lines.append(f"- Appel : `{call['name']}` {json.dumps(call['args'], ensure_ascii=False)}")
        failed = [check["message"] for check in row["checks"] if not check["passed"]]
        if failed:
            lines.append(f"- **Contrôles en échec :** {' ; '.join(failed)}")
        lines += ["", "### Réponse", "", row["final_answer"] or "*(aucune)*", "", "### Ce que les outils ont renvoyé", ""]
        for response in row["tool_responses"]:
            data = response["response"] if isinstance(response["response"], dict) else {}
            lines += [f"`{response['name']}` : `{json.dumps(data.get('rows') or data, ensure_ascii=False)[:1500]}`", ""]
        lines += ["---", ""]
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


@pytest.mark.models
@pytest.mark.real_data
@pytest.mark.llm
@pytest.mark.long
@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_particularities_e2e(case):
    print(f"\n→ en cours: {case.id} ({CASES.index(case) + 1}/{len(CASES)})", flush=True)
    events, elapsed = asyncio.run(_ask(case.question))
    parts = _parts(events)
    calls = [{"name": part.function_call.name, "args": dict(part.function_call.args or {})}
             for part in parts if part.function_call]
    responses = [{"name": part.function_response.name, "response": part.function_response.response}
                 for part in parts if part.function_response]
    answer = next(("".join(part.text or "" for part in event.content.parts).strip()
                   for event in reversed(events) if event.is_final_response() and event.content), "")
    checks = _checks(case, calls, responses, answer)
    JSONL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with JSONL_PATH.open("a", encoding="utf-8") as file:
        file.write(json.dumps({
            "run_id": RUN_ID, "model": LLM_MODEL, "server": LLM_BASE_URL, "case_id": case.id,
            "question": case.question, "rubric": case.rubric, "note": case.note, "elapsed_seconds": round(elapsed, 3),
            "tool_calls": calls, "tool_responses": responses, "final_answer": answer,
            "checks": [{"passed": ok, "message": message} for ok, message in checks],
            "passed": all(ok for ok, _ in checks)}, ensure_ascii=False, default=repr) + "\n")
    write_report()
    print(f"terminé: {case.id} ({elapsed:.0f} s) — rapport : {REPORT_PATH}", flush=True)
    failed = [message for ok, message in checks if not ok]
    assert not failed, f"{case.id} : {failed}\nRéponse : {answer[:300]}"
