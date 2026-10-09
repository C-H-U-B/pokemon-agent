"""Onglet « Guide » : ce qu'on peut demander à l'outil, et ce qu'il ne sait pas faire.

Tout le contenu vient de `guide.toml`, modifié à la main ; ce module le contrôle et l'affiche. Une famille
montre son titre et un bouton d'exemple, sa description se déplie ; le bouton met dans le champ de saisie une
question de la famille tirée au hasard par le navigateur, sans l'envoyer. Les questions non disponibles sont
rangées par raison. La page est publique : tout texte du fichier est échappé.
"""
import json
import tomllib
from html import escape
from pathlib import Path

from pokemon_rag.web.graph import WRITTEN

GUIDE_FILE = Path(__file__).with_name("guide.toml")
# Dans un modèle de question : le nom tiré au hasard, seul ou précédé de « de » élidé devant une voyelle.
PLACEHOLDERS = ("{pokemon}", "{de_pokemon}")


def load_guide(path: Path = GUIDE_FILE) -> dict:
    """Lit et contrôle le fichier du guide ; une entrée fautive est nommée dans l'erreur."""
    guide = tomllib.loads(path.read_text(encoding="utf-8"))
    families, reasons = guide.get("famille") or [], guide.get("indisponible") or []
    if not families:
        raise ValueError(f"{path.name} : aucune famille")
    seen = set()
    for kind, entries, text in (("famille", families, "phrase"), ("indisponible", reasons, "raison")):
        for index, entry in enumerate(entries, start=1):
            where = f"{path.name}, {kind} « {entry.get('titre') or f'n° {index}'} »"
            for key in ("titre", text):
                if not isinstance(entry.get(key), str) or not entry[key].strip():
                    raise ValueError(f"{where} : « {key} » manquant ou vide")
            questions = entry.get("questions", [] if kind == "indisponible" else None)
            if not isinstance(questions, list) or not all(isinstance(q, str) and q.strip() for q in questions) or (
                    not questions and (kind == "famille" or "questions" in entry)):
                raise ValueError(f"{where} : « questions » doit être une liste non vide de textes")
            for question in questions:
                if question in seen:
                    raise ValueError(f"{where} : question citée deux fois : {question}")
                seen.add(question)
            for key in ("issues", "messages"):
                if not all(isinstance(value, str) and value for value in entry.get(key, [])):
                    raise ValueError(f"{where} : « {key} » doit être une liste de textes")
            for template in entry.get("modeles", []):
                if not isinstance(template, str) or not any(mark in template for mark in PLACEHOLDERS):
                    raise ValueError(f"{where} : un modèle doit contenir {' ou '.join(PLACEHOLDERS)} : {template}")
            unknown = [q for q in entry.get("en_cours", []) if q not in questions]
            if unknown:
                raise ValueError(f"{where} : « en_cours » cite une question absente de la famille : {unknown[0]}")
    pool = {question for family in families for question in family["questions"]}
    for entry in reasons:
        if entry.get("voisine") is not None and entry["voisine"] not in pool:
            raise ValueError(f"{path.name}, indisponible « {entry['titre']} » : « voisine » n'est dans aucune "
                             f"famille : {entry['voisine']}")
    return guide


def drawable_names(guide: dict, catalogue: list[tuple[str, str, str | None]]) -> list[str]:
    """Noms d'espèces que les modèles de question peuvent tirer : ceux de la base, moins `noms_exclus`."""
    return sorted({species for _, species, _ in catalogue} - set(guide.get("noms_exclus", [])))


def _example(label: str, questions: list[str], templates: list[str] | None = None) -> str:
    """Bouton d'exemple : questions et modèles voyagent dans la page, le tirage se fait dans le navigateur."""
    drawn = f' data-templates="{escape(json.dumps(templates, ensure_ascii=False))}"' if templates else ""
    return (f'<button type="button" class="guide-example" data-questions="'
            f'{escape(json.dumps(questions, ensure_ascii=False))}"{drawn}>{escape(label)}</button>')


def known_failure(guide: dict, trace: dict) -> str | None:
    """Titre de la raison connue pour laquelle une question terminée sort de ce que l'outil sait faire, sinon None.

    Le message d'un refus du guard prime, du plus récent au plus ancien : un même code de refus couvre
    plusieurs raisons, que seul son message distingue. Les messages répertoriés viennent de la lecture de la
    question, pas des arguments du modèle : ils signalent la raison même quand le modèle a ensuite rendu une
    réponse, obtenue par un appel qui a laissé tomber la contrainte. À défaut, l'issue de la trace désigne la
    raison ; une réponse écrite sans aucun appel d'outil a l'issue « unverified », comme dans le graphe.
    """
    outcome, tools = trace.get("outcome"), trace.get("tools") or []
    if outcome == "running":
        return None
    reasons = guide.get("indisponible") or []
    for tool in reversed(tools):
        message = str(tool["result"].get("message", "")) if isinstance(tool.get("result"), dict) else ""
        for reason in reasons:
            if any(message.startswith(start) for start in reason.get("messages", [])):
                return reason["titre"]
    # Une abstention de budget après un appel refusé ou en erreur vient des essais répétés, pas du volume : sans
    # message reconnu, elle est signalée comme une abstention faute de résultat, pas comme une réponse trop longue.
    if outcome in WRITTEN:
        if tools or outcome != "answered":
            return None
        outcome = "unverified"
    elif outcome == "budget_abstention" and any(
            isinstance(tool.get("result"), dict) and tool["result"].get("error") for tool in tools):
        outcome = "tool_failure_abstention"
    return next((reason["titre"] for reason in reasons if outcome in reason.get("issues", [])), None)


def guide_html(guide: dict, notice: str | None = None, names: list[str] | None = None) -> str:
    """Contenu de l'onglet, d'après un guide déjà contrôlé ; `notice` est le titre de la raison à signaler.

    `names` : noms que les modèles de question tirent au hasard. Le navigateur garde les derniers reçus :
    ils ne sont envoyés qu'une fois, à l'ouverture de la page.
    """
    blocks = ['<p class="guide-intro">Ce que vous pouvez demander. Un bouton « Exemple » met une question dans le '
              "champ de saisie : il reste à l'envoyer.</p>"]
    for family in guide["famille"]:
        in_progress = family.get("en_cours") or []
        note = ('<p class="guide-progress">En cours d\'amélioration : '
                + " ; ".join(f"« {escape(q)} »" for q in in_progress) + "</p>") if in_progress else ""
        blocks.append(f'<details class="guide-block" data-key="{escape(family["titre"])}">'
                      f'<summary><span>{escape(family["titre"])}</span>'
                      f'{_example("Exemple", family["questions"], family.get("modeles"))}</summary>'
                      f'<p>{escape(family["phrase"])}</p>{note}</details>')
    reasons = guide.get("indisponible") or []
    if reasons:
        blocks.append('<h4 class="guide-heading">Questions non disponibles</h4>'
                      '<p class="guide-intro">Ce que l\'outil ne sait pas encore faire, et pourquoi.</p>')
    for reason in reasons:
        questions = "".join(f"<li>{escape(q)}</li>" for q in reason.get("questions", []))
        nearby = (f'<p class="guide-nearby">À la place : {_example(reason["voisine"], [reason["voisine"]])}</p>'
                  if reason.get("voisine") else "")
        noticed = reason["titre"] == notice
        blocks.append(f'<details class="guide-block unavailable{" noticed" if noticed else ""}" '
                      f'data-key="{escape(reason["titre"])}"><summary><span>{escape(reason["titre"])}</span>'
                      f'{"<em>Votre dernière question</em>" if noticed else ""}</summary><p>{escape(reason["raison"])}</p>{f"<ul>{questions}</ul>" if questions else ""}{nearby}</details>')
    if names:
        blocks.append(f'<span hidden data-names="{escape(json.dumps(names, ensure_ascii=False))}"></span>')
    return "".join(blocks)


GUIDE_TEMPLATE = '<div class="guide"></div>'
GUIDE_CSS = """
.guide { --ink: var(--body-text-color, #1f2933); --muted: var(--body-text-color-subdued, #8a94a3);
    --line: var(--border-color-primary, #e2e6ec); --surface: var(--background-fill-primary, #fff);
    color: var(--ink); font-size: 13.5px; overflow-wrap: anywhere; }
.guide p { margin: 6px 0 0; }
.guide-intro { color: var(--muted); margin: 4px 0 10px !important; }
.guide-heading { margin: 18px 0 0; font-size: 14px; font-weight: 600; }
.guide-block { border: 1px solid var(--line); border-radius: 12px; background: var(--surface);
    padding: 8px 12px; margin: 0 0 8px; }
/* Une raison d'indisponibilité a le gris du liquide terni, comme un rejet dans le graphe. */
.guide-block.unavailable { border-left: 3px solid var(--spoiled, #9aa3ad); }
.guide summary { cursor: pointer; font-weight: 600; display: flex; align-items: center; gap: 8px; }
.guide summary span { flex: 1; }
.guide summary::before { content: '▸'; color: var(--muted); }
.guide details[open] > summary::before { content: '▾'; }
/* Un exemple est une question du visiteur : jaune, comme les boutons d'exemples sous la conversation. */
.guide-example { font: inherit; font-size: 12.5px; font-weight: 400; color: var(--ink); cursor: pointer;
    text-align: left; padding: 2px 10px; border-radius: 999px; background: var(--surface);
    border: 1px solid color-mix(in srgb, var(--visitor, #eab308) 55%, var(--line)); }
.guide-example:hover { border-color: var(--visitor, #eab308);
    background: color-mix(in srgb, var(--visitor-soft, #facc15) 24%, var(--surface)); }
.guide-progress, .guide-nearby { color: var(--muted); }
/* Raison pour laquelle la dernière question a échoué : signalée au visiteur, donc en jaune. */
.guide-block.noticed { border-color: var(--visitor, #eab308); }
.guide summary em { font-style: normal; font-weight: 400; font-size: 12.5px; padding: 1px 8px; border-radius: 999px;
    background: color-mix(in srgb, var(--visitor-soft, #facc15) 30%, var(--surface)); }
.guide ul { margin: 6px 0 0; padding-left: 18px; }
"""
# Le navigateur redessine l'onglet à chaque valeur reçue : les blocs dépliés par le lecteur le restent, la raison
# signalée est dépliée, et une pastille marque l'onglet jusqu'à ce qu'il soit ouvert (attribut, pas classe : Gradio
# réécrit les classes de ses onglets). Le champ est rempli comme par une frappe (événement « input »), pour que
# Gradio enregistre la valeur.
GUIDE_JS = """
const box = element.querySelector('.guide'), last = new Map(), opened = new Set();
let names = [];
const tab = () => [...document.querySelectorAll('#agent-panel [role=tab]')].find(t => t.textContent.trim() === 'Guide');
const showNotice = () => box.querySelector('.noticed')?.scrollIntoView({ block: 'nearest' });
function render() {
    const panel = element.closest('.tabitem'), top = panel ? panel.scrollTop : 0;
    box.innerHTML = props.value || '';
    const carrier = box.querySelector('[data-names]');
    if (carrier) names = JSON.parse(carrier.dataset.names);
    box.querySelectorAll('details').forEach(block => {
        const key = block.dataset.key, noticed = block.classList.contains('noticed');
        block.open = noticed || opened.has(key);
        block.addEventListener('toggle', () => block.open ? opened.add(key) : opened.delete(key));
    });
    if (panel) panel.scrollTop = top;
    const button = tab(), noticed = box.querySelector('.noticed');
    if (button && noticed && button.getAttribute('aria-selected') !== 'true') button.dataset.notice = '1';
    else if (button) delete button.dataset.notice;
    showNotice();
}
document.addEventListener('click', (event) => {
    const button = tab();
    if (!button || event.target.closest('[role=tab]') !== button) return;
    delete button.dataset.notice;
    setTimeout(showNotice, 80);
});
box.addEventListener('click', (event) => {
    const button = event.target.closest('.guide-example');
    if (!button) return;
    event.preventDefault();  // dans un titre, le clic ne déplie pas la description
    const questions = JSON.parse(button.dataset.questions), key = button.dataset.questions;
    const templates = JSON.parse(button.dataset.templates || '[]'), pick = list => list[Math.floor(Math.random() * list.length)];
    let question;
    do {
        // Une fois sur deux, un modèle rempli d'un nom tiré au hasard : l'exemple précis importe peu.
        if (templates.length && names.length && Math.random() < 0.5) {
            const name = pick(names);
            question = pick(templates).replace('{de_pokemon}', (/^[aeiouyéèêàâîôû]/i.test(name) ? "d'" : 'de ') + name)
                .replace('{pokemon}', name);
        } else question = pick(questions);
    } while (questions.length > 1 && question === last.get(key));
    last.set(key, question);
    const field = document.querySelector('#question-box textarea');
    if (!field) return;
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(field, question);
    field.dispatchEvent(new Event('input', { bubbles: true }));
    field.focus();
});
watch('value', render);
render();
"""
