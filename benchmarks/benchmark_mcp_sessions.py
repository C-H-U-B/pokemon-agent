"""Compare les sessions MCP ponctuelles et partagées avec les vrais modèles.

À lancer par l'utilisateur dans langgraph-agent, avec LM Studio et les données
locales disponibles. --help n'importe pas le client et n'effectue aucune inférence.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter


ROOT = Path(__file__).resolve().parents[1]


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=int, default=2, help="Questions par mode (minimum 2).")
    parser.add_argument("--question", default="Décris le comportement de Pikachu dans la nature.")
    parser.add_argument("--reverse", action="store_true", help="Mesurer la session partagée en premier.")
    parser.add_argument("--output", type=Path, help="Rapport JSON ; par défaut dans traces/, horodaté.")
    args = parser.parse_args()
    if args.questions < 2 or not args.question.strip():
        parser.error("Il faut au moins deux questions par mode et une question non vide.")
    return args


async def compare(args, report):
    from tqdm import tqdm
    from pokemon_rag.client.mcp_client import ask, open_client

    modes = ["ponctuelle", "partagée"]
    if args.reverse:
        modes.reverse()
    report["order"] = modes
    with tqdm(total=2 * args.questions, desc="Comparaison MCP", unit="question") as progress:
        for mode in modes:
            entry = {"mode": mode, "questions": []}
            report["sessions"].append(entry)
            start = perf_counter()

            async def measure(call):
                for index in range(args.questions):
                    progress.set_postfix_str(f"{mode} {index + 1}/{args.questions}")
                    item = {"number": index + 1}
                    entry["questions"].append(item)
                    question_start = perf_counter()
                    try:
                        item["answer"] = await call(args.question)
                    finally:
                        item["seconds"] = perf_counter() - question_start
                    progress.update(1)
                    tqdm.write(f"{mode} — question {index + 1} : {item['seconds']:.2f} s")

            try:
                if mode == "ponctuelle":
                    await measure(ask)
                else:
                    async with open_client() as conversation:
                        entry["opening_seconds"] = perf_counter() - start
                        await measure(conversation.ask)
                entry["status"] = "success"
            except BaseException as exc:
                entry["status"] = "error"
                entry["error"] = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                # Inclut ouverture et fermeture pour comparer les deux modes.
                entry["total_seconds"] = perf_counter() - start
                tqdm.write(f"{mode} — total : {entry['total_seconds']:.2f} s")


def main():
    args = parse_args()
    timestamp = datetime.now(timezone.utc)
    output = args.output or ROOT / "traces" / f"mcp-sessions-{timestamp:%Y%m%d-%H%M%S-%f}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "timestamp": timestamp.isoformat(),
        "question": args.question,
        "questions_per_mode": args.questions,
        "sessions": [],
    }
    # Réserver le fichier avant les appels coûteux ; ne jamais écraser un rapport.
    with output.open("x", encoding="utf-8") as handle:
        print("Mesure réelle : LM Studio, Qwen et index local requis.", flush=True)
        try:
            asyncio.run(compare(args, report))
        finally:
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            print(f"Rapport : {output.resolve()}", flush=True)


if __name__ == "__main__":
    main()
