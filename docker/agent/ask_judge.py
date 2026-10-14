#!/usr/bin/env python3
"""Client du juge : demande la validation du projet et sort en erreur si elle est refusée.

Usage : ``ask-judge`` (arbre de travail) ou ``ask-judge --index`` (contenu indexé, utilisé par le
hook pre-commit). Code de sortie : 0 accepté, 1 refusé, 2 juge injoignable ou réponse invalide
(refus par défaut). Bibliothèque standard uniquement.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_URL = "http://judge:8080"
TIMEOUT_SECONDS = 1000


def ask(url: str, source: str) -> tuple[bool, str]:
    """Interroge le juge.

    Args:
        url: Adresse du juge.
        source: ``index`` ou ``worktree``.

    Returns:
        Le verdict et la sortie de la procédure.

    Raises:
        ValueError: Si la réponse du juge n'a pas la forme attendue.
    """
    request = urllib.request.Request(  # noqa: S310 - URL interne fixée par la configuration
        f"{url}/check",
        data=json.dumps({"source": source}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
        body = json.loads(response.read())
    if not isinstance(body, dict):
        msg = "réponse du juge invalide"
        raise ValueError(msg)
    passed, output = body.get("passed"), body.get("output")
    if not isinstance(passed, bool) or not isinstance(output, str):
        msg = "réponse du juge invalide"
        raise ValueError(msg)
    return passed, output


def main() -> int:
    """Point d'entrée.

    Returns:
        Le code de sortie du processus.
    """
    parser = argparse.ArgumentParser(description="Demande son verdict au juge.")
    parser.add_argument("--index", action="store_true", help="juger le contenu indexé")
    source = "index" if parser.parse_args().index else "worktree"
    url = os.environ.get("JUDGE_URL", DEFAULT_URL)
    try:
        passed, output = ask(url, source)
    except urllib.error.HTTPError as error:
        sys.stderr.write(f"Le juge a répondu {error.code} : {error.read().decode()} Refusé.\n")
        return 2
    except (urllib.error.URLError, OSError, ValueError) as error:
        sys.stderr.write(f"Juge injoignable ou réponse invalide ({error}) : refusé.\n")
        return 2
    sys.stdout.write(output)
    sys.stdout.write("\nJUGE : accepté.\n" if passed else "\nJUGE : refusé.\n")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
