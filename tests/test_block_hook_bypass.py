import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

HOOK = Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "block-hook-bypass.py"


def load_hook() -> ModuleType:
    spec = importlib.util.spec_from_file_location("block_hook_bypass", HOOK)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hook = load_hook()

BLOCKED = [
    "git commit --no-verify -m x",
    "git commit -nm x",
    "git commit -n -m x",
    "git commit --no-ver''ify -m x",
    "git commit --no-verif -m x",
    "git push --no-verify",
    "SKIP=poe-check git commit -m x",
    "env GIT_DIR=/tmp/x git commit -m x",
    "PRE_COMMIT_ALLOW_NO_CONFIG=1 git commit -m x",
    "git -c core.hooksPath=/dev/null commit -m x",
    "git config core.hooksPath /dev/null",
    "git -c alias.ci='commit --no-verify' ci",
    "uv run pre-commit uninstall",
    "python -m pre_commit uninstall",
    "rm .git/hooks/pre-commit",
    "echo x > .git/hooks/pre-commit",
    "chmod -x .git/hooks/pre-commit",
    "cd .git/hooks && ls",
    "find .git/hooks -delete",
    "bash -c 'git commit --no-verify -m x'",
    "eval 'git commit -n -m x'",
    "echo ok && git commit --no-verify -m x",
    "echo ok\ngit commit --no-verify -m x",
]

ALLOWED = [
    "git commit -m 'fix: handle -run flag'",
    "git commit -m 'feat: add -n option'",
    'git commit -am "message avec -n et --no-verify"',
    "git commit --amend --no-edit",
    "git commit -S -m x",
    "git log -n 5",
    "ls .git/hooks",
    "cat .git/hooks/pre-commit",
    "uv run pre-commit install",
    "uv run poe check",
    "git commit -F - <<'EOF'\nfeat: l'analyseur\n\nmention de --no-verify dans le corps\nEOF",
]


@pytest.mark.parametrize("command", BLOCKED)
def test_bypass_is_blocked(command: str) -> None:
    assert hook.analyze(command) is not None


@pytest.mark.parametrize("command", ALLOWED)
def test_legitimate_command_is_allowed(command: str) -> None:
    assert hook.analyze(command) is None


@pytest.mark.parametrize(
    ("stdin", "expected"),
    [
        (json.dumps({"tool_input": {"command": "git commit --no-verify"}}), 2),
        (json.dumps({"tool_input": {"command": "git status"}}), 0),
        ("pas du json", 2),
        (json.dumps({"tool_input": {}}), 2),
    ],
)
def test_script_exit_code(stdin: str, expected: int) -> None:
    result = subprocess.run(  # noqa: S603  # commande fixe : interpréteur courant et hook du dépôt
        [sys.executable, str(HOOK)], input=stdin, text=True, capture_output=True, check=False
    )
    assert result.returncode == expected
