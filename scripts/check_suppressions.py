"""Refuse les suppressions de lint ou de typage sans justification écrite.

Une suppression (`noqa`, `type: ignore`, `pyright: ignore`) doit être suivie d'une raison introduite
par ` - `, ` -- ` ou ` # `, par exemple `# noqa: S101 - assert de test`.
"""

import io
import re
import subprocess
import sys
import tokenize
from pathlib import Path

SUPPRESSION = re.compile(r"(?:noqa|type:\s*ignore|pyright:\s*ignore)", re.IGNORECASE)
JUSTIFICATION = re.compile(r"\s(?:--?|#)\s+\S")


def find_violations(path: str, source: str) -> list[str]:
    """Liste les commentaires de suppression sans justification.

    Args:
        path: Chemin affiché dans les messages.
        source: Contenu du fichier Python.

    Returns:
        Une ligne `chemin:ligne: commentaire` par suppression non justifiée.
    """
    violations: list[str] = []
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return [f"{path}: fichier non analysable"]
    for token in tokens:
        if token.type != tokenize.COMMENT:
            continue
        match = SUPPRESSION.search(token.string)
        if match and not JUSTIFICATION.search(token.string[match.end() :]):
            violations.append(f"{path}:{token.start[0]}: {token.string.strip()}")
    return violations


def tracked_python_files() -> list[str]:
    """Liste les fichiers `.py` suivis par git ou non ignorés.

    Returns:
        Les chemins relatifs des fichiers Python du dépôt.
    """
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "*.py"],  # noqa: S607 -- git du PATH
        capture_output=True,
        check=True,
        text=True,
    )
    return [name for name in result.stdout.split("\0") if name]


def main() -> int:
    """Analyse les fichiers Python du dépôt.

    Returns:
        0 si toutes les suppressions sont justifiées, 1 sinon.
    """
    violations: list[str] = []
    for name in tracked_python_files():
        file = Path(name)
        if file.is_file():
            violations.extend(find_violations(name, file.read_text(encoding="utf-8")))
    for violation in violations:
        print(violation)
    if violations:
        print("Suppression sans justification : ajouter ` - raison` après le code.")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
