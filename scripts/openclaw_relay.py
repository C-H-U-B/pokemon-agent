"""Relais HTTP entre un client compatible OpenAI (OpenClaw) et LM Studio, pour voir ce que reçoit le modèle.

Chaque requête est enregistrée telle quelle (`<n>.json`), puis transmise sans modification ; la réponse
est enregistrée (`<n>.resp.txt`) avec le délai du premier token et la durée de la génération.
`--capture-only` ne transmet rien et répond 503 : la requête est capturée sans aucune inférence.

Le client doit viser le relais (`models.providers.lmstudio.baseUrl` = http://localhost:1235/v1).

    python scripts/openclaw_relay.py traces/openclaw
    python scripts/openclaw_relay.py traces/openclaw --capture-only
"""
import argparse
import http.server
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

SKIP = {"host", "content-length", "transfer-encoding", "connection"}


def summarize(body: bytes) -> str:
    try:
        d = json.loads(body)
    except ValueError:
        return f"{len(body)} octets"
    msgs, tools = d.get("messages", []), d.get("tools", [])
    return (f"messages {len(json.dumps(msgs, ensure_ascii=False))} car., "
            f"{len(tools)} outils {len(json.dumps(tools, ensure_ascii=False))} car.")


def make_handler(out_dir: Path, upstream: str, capture_only: bool):
    count = 0

    class Relay(http.server.BaseHTTPRequestHandler):
        def _relay(self):
            nonlocal count
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            out = None
            if body:
                count += 1
                out = out_dir / f"{count:03d}.json"
                out.write_bytes(body)
                print(f"{self.path} : {summarize(body)} -> {out}", flush=True)
            if capture_only:
                self.send_error(503, "capture seule : rien n'est transmis au modèle")
                return
            req = urllib.request.Request(
                upstream + self.path, data=body or None, method=self.command,
                headers={k: v for k, v in self.headers.items() if k.lower() not in SKIP})
            try:
                resp = urllib.request.urlopen(req)
            except urllib.error.HTTPError as e:
                resp = e
            except urllib.error.URLError as e:
                print(f"  <- {upstream} injoignable : {e.reason}", flush=True)
                self.send_error(502, f"{upstream} injoignable")
                return
            self.send_response(resp.status)
            for k, v in resp.headers.items():
                if k.lower() not in SKIP:
                    self.send_header(k, v)
            self.end_headers()  # HTTP/1.0 : la réponse se termine à la fermeture, le streaming passe tel quel
            received, t0, t_first = b"", time.monotonic(), None
            while chunk := resp.read1(8192):
                if t_first is None and (b'"content":"' in chunk or b'"arguments":"' in chunk):
                    t_first = time.monotonic()
                received += chunk
                self.wfile.write(chunk)
                self.wfile.flush()
            if out is not None:
                out.with_suffix(".resp.txt").write_bytes(received)
                end = time.monotonic()
                first = (t_first or end) - t0
                print(f"  <- HTTP {resp.status}, premier token {first:.1f} s, génération {end - t0 - first:.1f} s",
                      flush=True)

        do_GET = do_POST = _relay

    return Relay


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out_dir", type=Path, help="dossier des requêtes et réponses enregistrées")
    parser.add_argument("--port", type=int, default=1235)
    parser.add_argument("--upstream", default="http://localhost:1234")
    parser.add_argument("--capture-only", action="store_true", help="ne rien transmettre, répondre 503")
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    mode = "capture seule" if args.capture_only else f"-> {args.upstream}"
    print(f"Relais sur http://127.0.0.1:{args.port} {mode}, enregistrement dans {args.out_dir}", flush=True)
    handler = make_handler(args.out_dir, args.upstream, args.capture_only)
    http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler).serve_forever()


if __name__ == "__main__":
    main()
