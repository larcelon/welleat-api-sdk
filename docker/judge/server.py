#!/usr/bin/env python3
"""Juge : serveur HTTP interne qui lance ``uv run poe check`` sur le projet et renvoie le résultat.

Le projet est monté en lecture seule sur ``/workspace``. Chaque demande exporte l'état à juger
(index git ou arbre de travail) dans un dossier de travail propre, puis y lance la procédure.
Les demandes sont traitées une par une. Bibliothèque standard uniquement.
"""

import json
import os
import shutil
import signal
import subprocess
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WORKSPACE = Path("/workspace")
RUN_DIR = Path("/var/cache/judge/run")
PORT = 8080
TIMEOUT_SECONDS = 900
MAX_OUTPUT_CHARS = 30_000
LOCK = threading.Lock()


def _git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[bytes]:
    """Lance une commande git.

    Args:
        *args: Arguments de git.
        cwd: Dossier d'exécution (``/workspace`` par défaut).

    Returns:
        Le processus terminé, sortie capturée.
    """
    return subprocess.run(  # noqa: S603 - arguments fixes, exécutable git
        ["git", *args],  # noqa: S607 - git est résolu via le PATH de l'image
        cwd=cwd or WORKSPACE,
        capture_output=True,
        check=True,
        env={
            **os.environ,
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "safe.directory",
            "GIT_CONFIG_VALUE_0": "*",
        },
    )


def export_snapshot(source: str) -> None:
    """Copie l'état à juger dans ``RUN_DIR`` et en fait un dépôt git (pour ``detect-secrets``).

    Args:
        source: ``index`` pour le contenu indexé, ``worktree`` pour l'arbre de travail.
    """
    shutil.rmtree(RUN_DIR, ignore_errors=True)
    RUN_DIR.mkdir(parents=True)
    if source == "index":
        _git("checkout-index", "--all", f"--prefix={RUN_DIR}/")
    else:
        listing = _git("ls-files", "-z", "--cached", "--others", "--exclude-standard").stdout
        for raw in filter(None, listing.split(b"\0")):
            relative = Path(raw.decode())
            origin = WORKSPACE / relative
            if origin.is_file():
                (RUN_DIR / relative).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(origin, RUN_DIR / relative)
    _git("init", "--quiet", cwd=RUN_DIR)
    _git("add", "--all", cwd=RUN_DIR)


def run_check(source: str) -> dict[str, object]:
    """Exporte l'état demandé puis lance ``uv run poe check``.

    Args:
        source: ``index`` ou ``worktree``.

    Returns:
        Le verdict : ``passed``, ``exit_code`` et ``output`` (fin de la sortie).
    """
    with LOCK:
        export_snapshot(source)
        process = subprocess.Popen(
            ["uv", "run", "poe", "check"],  # noqa: S607 - uv est résolu via le PATH de l'image
            cwd=RUN_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        try:
            output, _ = process.communicate(timeout=TIMEOUT_SECONDS)
            exit_code = process.returncode
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            output, _ = process.communicate()
            output += f"\nDélai de {TIMEOUT_SECONDS} s dépassé : procédure interrompue.\n"
            exit_code = 124
    return {"passed": exit_code == 0, "exit_code": exit_code, "output": output[-MAX_OUTPUT_CHARS:]}


class Handler(BaseHTTPRequestHandler):
    """Routes ``GET /health`` et ``POST /check``."""

    def _reply(self, status: HTTPStatus, body: dict[str, object]) -> None:
        """Envoie une réponse JSON.

        Args:
            status: Code HTTP.
            body: Contenu sérialisé en JSON.
        """
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        """Répond à la sonde de santé."""
        if self.path == "/health":
            self._reply(HTTPStatus.OK, {"status": "ok"})
        else:
            self._reply(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        """Lance la procédure de qualité sur l'état demandé."""
        if self.path != "/check":
            self._reply(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            request = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._reply(HTTPStatus.BAD_REQUEST, {"error": "JSON invalide"})
            return
        source = request.get("source", "worktree") if isinstance(request, dict) else None
        if source not in {"index", "worktree"}:
            self._reply(HTTPStatus.BAD_REQUEST, {"error": "source: index ou worktree"})
            return
        try:
            self._reply(HTTPStatus.OK, run_check(source))
        except (subprocess.CalledProcessError, OSError) as error:
            self._reply(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"export impossible : {error}"})


def main() -> None:
    """Démarre le serveur sur toutes les interfaces du réseau interne."""
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()  # noqa: S104 - réseau interne


if __name__ == "__main__":
    main()
