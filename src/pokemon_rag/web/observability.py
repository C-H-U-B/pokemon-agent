"""Onglet « Observabilité » : la chaîne d'une question en blocs, avec ce que chaque étape a reçu et renvoyé.

`observability_html(trace)` rend une trace de la forme de `_web_trace`, complète ou en cours : un bloc
« Question », un bloc par appel d'outil (proposition du modèle, guard, outil, budget de contexte), un bloc
« Réponse ». La page est publique : tout texte venu de la question, du modèle ou d'un outil est échappé, et le
texte d'exception d'une erreur d'outil n'est pas affiché. Une question en cours ne porte aucune durée qui
change : son rendu ne varie qu'à l'arrivée d'un appel ou d'un retour, et n'est renvoyé au navigateur qu'alors.
"""
import json
from html import escape

from pokemon_rag.web.graph import (LOADING_NOTICE, REJECTIONS, TOOL_ERRORS, TOOL_LABELS, WRITTEN, _arguments,
                                   guard_correction)

EMPTY = '<p class="obs-empty">Posez une question : chaque étape montrera ici ce qu\'elle a reçu et renvoyé.</p>'
STARTUP_STEPS = (("embedding", "modèle d'embedding"), ("reranker", "modèle de reclassement"),
                 ("corpus", "corpus"), ("bm25", "index lexical"))
SEARCH_STEPS = (("vector", "par le sens"), ("bm25", "par les mots"), ("rrf", "fusion"), ("reranker", "reclassement"))
# Le message d'une erreur d'outil se termine par le texte de l'exception, que le modèle lit pour se corriger.
ERROR_DETAIL = " Détail : "


def _seconds(value: float) -> str:
    return f"{value:.2f}".replace(".", ",") + " s"


def _bytes(value) -> str:
    return f"{_size(value):,} octets".replace(",", " ")


def _size(value) -> int:
    """Octets du JSON compact, comme le budget de contexte les compte ; un entier est déjà une taille."""
    if isinstance(value, int):
        return value
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8"))


def _steps(values: dict, labels: tuple) -> str:
    return " · ".join(f"{label} {_seconds(values[key])}" for key, label in labels if key in values)


def _measures(tool: dict) -> list[str]:
    """Temps mesurés par l'outil lui-même : chargement et étapes de la recherche, ou requête SQL."""
    lines = []
    timings = tool.get("timings") or {}
    startup = timings.get("startup")
    if startup:
        lines.append(f"Chargement de la base documentaire (premier appel) : {_seconds(startup.get('total', 0.0))}"
                     f" ({_steps(startup, STARTUP_STEPS)})")
    if "total" in timings:
        steps = _steps(timings, SEARCH_STEPS)
        lines.append(f"Recherche : {_seconds(timings['total'])}" + (f" ({steps})" if steps else "")
                     + f" · {tool.get('passages', 0)} passage(s)")
    if tool.get("execution_time") is not None:
        lines.append(f"Requête SQL : {tool['execution_time'] * 1000:.0f} ms")
    return lines


def _step(title: str, verdict: str, kind: str, *lines: str, extra: str = "") -> str:
    """Une étape de la chaîne : son nom, son verdict, puis ses données, une ligne par élément."""
    body = "".join(f"<div>{escape(line)}</div>" for line in lines if line)
    return (f'<div class="obs-step {kind}"><div class="obs-step-title">{escape(title)}'
            f'<span class="obs-verdict">{escape(verdict)}</span></div>{body}{extra}</div>')


def _raw(label: str, value, key: str) -> str:
    """Bloc repliable : le texte exact d'une étape, en JSON. `key` le distingue pour qu'il reste déplié."""
    shown = escape(json.dumps(value, ensure_ascii=False, indent=2, default=str))
    return f'<details data-key="{escape(key)}"><summary>{escape(label)}</summary><pre>{shown}</pre></details>'


def _call(tool: dict, index: int, key: str, loading: bool) -> str:
    """Bloc d'un appel d'outil : la chaîne s'arrête à l'étape qui l'a refusé ou qui a échoué."""
    name = tool["name"]
    result = tool["result"] if isinstance(tool.get("result"), dict) else {}
    error = result.get("error")
    key = f"{key}:{index}"
    proposed = tool.get("proposed_arguments", tool["arguments"])
    steps = [_step("Modèle", "choisit l'outil", "", f"Outil appelé : {name}",
                   f"Arguments proposés : {_arguments(proposed)}",
                   extra=_raw("Appel émis par le modèle", {"name": name, "args": proposed}, f"{key}:model"))]
    if tool.get("seconds") is None and not result:
        steps.append(_step("Guard, outil", "en cours…", "pending", LOADING_NOTICE if loading else ""))
    elif error and error not in TOOL_ERRORS:
        required = result.get("required_arguments")
        steps.append(_step("Guard", "refuse l'appel", "refused", result.get("message", error),
                           f"Arguments exigés : {_arguments(required)}" if required else "",
                           extra=_raw("Refus rendu au modèle par le guard", result, f"{key}:guard")))
    else:
        passed = _raw("Appel transmis à l'outil par le guard", {"name": name, "args": tool["arguments"]},
                      f"{key}:guard")
        if tool.get("proposed_arguments") is None:
            steps.append(_step("Guard", "conforme", "", "Appel exécuté sans changement.", extra=passed))
        else:
            steps.append(_step("Guard", "corrige", "changed", guard_correction(tool).removeprefix(" — "),
                               extra=passed))
        raw = f"Retour de l'outil : {_bytes(tool['raw_bytes'])}" if tool.get("raw_bytes") is not None \
            else "Taille du retour de l'outil : non mesurée"
        received = f"{name} a reçu : {_arguments(tool['arguments'])}"
        if error == "mcp_tool_error":
            # Le texte de l'exception reste dans la trace : il peut nommer un fichier ou une adresse.
            steps.append(_step("Outil", "en erreur", "refused", received,
                               result.get("message", error).split(ERROR_DETAIL)[0]))
        else:
            steps.append(_step("Outil", "exécuté", "", received, *_measures(tool), raw))
            if error:
                steps.append(_step("Budget de contexte", "ne transmet rien", "refused", result.get("message", error)))
            else:
                verdict, kind = (("tronque", "changed") if result.get("context_truncated")
                                 else ("réduit aux champs utiles", "changed") if result.get("context_compacted")
                                 else ("transmet en entier", ""))
                steps.append(_step("Budget de contexte", verdict, kind, f"Transmis au modèle : {_bytes(result)}",
                                   extra=_raw("Retour transmis au modèle", result, f"{key}:result")))
    duration = f'<span class="obs-time">{_seconds(tool["seconds"])}</span>' if tool.get("seconds") is not None else ""
    return (f'<section class="obs-block"><h4>Appel {index + 1} · {escape(TOOL_LABELS.get(name, name))} '
            f'<code>{escape(name)}</code>{duration}</h4>{"".join(steps)}</section>')


def _summary(trace: dict) -> str:
    tools = trace.get("tools") or []
    if trace["outcome"] == "running":
        return f"Réponse en cours… · {len(tools)} appel(s) d'outil"
    seconds, tokens = trace.get("seconds") or {}, trace.get("tokens") or {}
    parts = [f"{len(tools)} appel(s) d'outil"]
    if "total" in seconds:
        parts.insert(0, f"{_seconds(seconds['total'])} au total")
        parts.append(f"choix des outils {_seconds(seconds.get('analysis', 0.0))} · outils "
                     f"{_seconds(seconds.get('tools', 0.0))} · rédaction {_seconds(seconds.get('generation', 0.0))}")
    if tokens.get("prompt") or tokens.get("output"):
        parts.append(f"{tokens.get('prompt', 0)} tokens lus, {tokens.get('output', 0)} générés"
                     + (f", {tokens['thinking']} de réflexion" if tokens.get("thinking") else "")
                     + (" (limite de sortie atteinte)" if tokens.get("output_limit_reached") else ""))
    return " · ".join(parts)


def observability_html(trace: dict | None, key: str = "") -> str:
    """Blocs de la chaîne d'une trace Web ; `key` distingue deux questions pour les blocs dépliés par le lecteur."""
    if not trace:
        return EMPTY
    outcome, tools = trace["outcome"], trace.get("tools") or []
    blocks = [f'<div class="obs-summary">{escape(_summary(trace))}</div>',
              f'<section class="obs-block"><h4>Question</h4><div>{escape(trace["question"])}</div></section>']
    blocks += [_call(tool, index, key, bool(trace.get("loading"))) for index, tool in enumerate(tools)]
    if outcome != "running":
        answered = outcome in WRITTEN and (tools or outcome != "answered")
        verdict = WRITTEN[outcome] if answered else REJECTIONS.get(
            "unverified" if outcome == "answered" else outcome, REJECTIONS["error"])
        blocks.append(f'<section class="obs-block{"" if answered else " refused"}"><h4>Réponse</h4>'
                      f'<div>{escape(verdict)}</div></section>')
    return "".join(blocks)


OBSERVABILITY_TEMPLATE = '<div class="obs"></div>'
OBSERVABILITY_CSS = """
.obs { --ink: var(--body-text-color, #1f2933); --muted: var(--body-text-color-subdued, #8a94a3);
    --line: var(--border-color-primary, #e2e6ec); --surface: var(--background-fill-primary, #fff);
    color: var(--ink); font-size: 13.5px; overflow-wrap: anywhere; }
.obs-empty, .obs-summary { color: var(--muted); margin: 4px 0 10px; }
.obs-block { border: 1px solid var(--line); border-radius: 12px; background: var(--surface);
    padding: 10px 12px; margin: 0 0 10px; }
.obs-block h4 { margin: 0 0 6px; font-size: 14px; font-weight: 600; display: flex; flex-wrap: wrap;
    align-items: baseline; gap: 6px; }
/* Identifiant de l'outil appelé : en pastille, lisible d'un coup d'œil dans le titre du bloc. */
.obs-block h4 code { font-size: 12.5px; font-weight: 600; color: var(--ink); padding: 1px 6px; border-radius: 6px;
    background: var(--background-fill-secondary, #f0f2f5); border: 1px solid var(--line); }
.obs-time { margin-left: auto; color: var(--muted); font-weight: 400; font-variant-numeric: tabular-nums; }
/* Une étape : un filet à gauche, dont la couleur dit si l'étape a laissé passer, modifié ou arrêté l'appel. */
.obs-step { border-left: 3px solid var(--line); padding: 2px 0 2px 10px; margin: 6px 0 0; }
.obs-step.changed { border-left-color: #d97706; }
.obs-step.refused, .obs-block.refused { border-left: 3px solid #dc2626; }
.obs-step.pending { border-left-style: dashed; }
.obs-step-title { font-weight: 600; }
.obs-verdict { font-weight: 400; color: var(--muted); margin-left: 6px; }
.obs summary { cursor: pointer; color: var(--muted); margin-top: 2px; }
/* Hauteur bornée : un long retour défile dans son bloc, sans allonger ni élargir le panneau. */
.obs pre { margin: 4px 0 0; padding: 8px; max-height: 240px; overflow: auto; border-radius: 8px;
    background: var(--background-fill-secondary, #f8f9fb); font-size: 12px; white-space: pre-wrap; }
"""
# Le navigateur remplace les blocs à chaque valeur reçue ; les retours dépliés par le lecteur le restent,
# et l'onglet garde sa position de défilement.
OBSERVABILITY_JS = """
const opened = new Set();
function render() {
    const panel = element.closest('.tabitem'), top = panel ? panel.scrollTop : 0;
    const box = element.querySelector('.obs');
    box.innerHTML = props.value || '';
    box.querySelectorAll('details').forEach(block => {
        const key = block.dataset.key;
        block.open = opened.has(key);
        block.addEventListener('toggle', () => block.open ? opened.add(key) : opened.delete(key));
    });
    if (panel) panel.scrollTop = top;
}
watch('value', render);
render();
"""
