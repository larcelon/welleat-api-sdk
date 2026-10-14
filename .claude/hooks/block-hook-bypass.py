#!/usr/bin/env python3
"""Hook Claude Code PreToolUse (Bash) : refuse les contournements du hook pre-commit.

Lit sur l'entrée standard le JSON fourni par Claude Code, analyse la commande Bash avec ``shlex``
(les messages de commit ne sont donc jamais pris pour des options) et sort avec le code 2, message
sur stderr, si la commande contourne ``poe check``. Une entrée illisible est refusée (fail-closed).
Bibliothèque standard uniquement.
"""

import json
import re
import shlex
import sys
from pathlib import PurePath

BLOCK_EXIT = 2
MAX_DEPTH = 3
SEPARATORS = frozenset({";", "&&", "||", "|", "|&", "&", "(", ")"})
REDIRECTIONS = frozenset({">", ">>", ">|"})
SHELLS = frozenset({"bash", "sh", "zsh", "dash", "ksh"})
READ_ONLY = frozenset({"ls", "cat", "head", "tail", "grep", "rg", "stat", "file", "wc", "less"})
BLOCKED_ENV = frozenset({"SKIP", "GIT_DIR", "GIT_WORK_TREE"})
BLOCKED_ENV_PREFIXES = ("PRE_COMMIT_", "GIT_CONFIG")
GLOBAL_OPTIONS_WITH_VALUE = frozenset({"-c", "-C", "--namespace", "--exec-path"})
LONG_OPTIONS_WITH_VALUE = frozenset({
    "message",
    "file",
    "author",
    "date",
    "template",
    "reuse-message",
    "reedit-message",
    "fixup",
})
SHORT_OPTIONS_WITH_VALUE = "mFCct"
SHORT_OPTIONS_WITH_ATTACHED_VALUE = "Su"
ENV_ASSIGNMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=")
HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1")
RAW_FALLBACK = re.compile(
    r"--no-v|pre[-_]commit\s+uninstall|core\.hookspath|(?:^|\s)(?:SKIP|GIT_DIR)=", re.IGNORECASE
)


def strip_heredocs(text: str) -> str:
    """Retire les corps de heredoc, qui sont des données et non des commandes.

    Args:
        text: La commande Bash complète.

    Returns:
        La commande sans les lignes situées entre un ``<<DELIM`` et son délimiteur de fin.
    """
    kept: list[str] = []
    delimiter: str | None = None
    for line in text.split("\n"):
        if delimiter is not None:
            if line.strip() == delimiter:
                delimiter = None
            continue
        kept.append(line)
        match = HEREDOC.search(line)
        if match:
            delimiter = match.group(2)
    return "\n".join(kept)


def newlines_to_semicolons(text: str) -> str:
    """Remplace les sauts de ligne hors guillemets par des points-virgules.

    Args:
        text: La commande Bash.

    Returns:
        La commande où chaque ligne non citée devient une commande distincte.
    """
    result: list[str] = []
    quote = ""
    escaped = False
    for char in text:
        if escaped:
            escaped = False
        elif char == "\\" and quote != "'":
            escaped = True
        elif quote:
            quote = "" if char == quote else quote
        elif char in "'\"":
            quote = char
        elif char == "\n":
            char = " ; "  # noqa: PLW2901  # remplacement local du caractère courant
        result.append(char)
    return "".join(result)


def tokenize(command: str) -> list[str]:
    """Découpe une commande en mots, séparateurs et redirections.

    Args:
        command: La commande Bash.

    Returns:
        Les jetons, guillemets retirés (``--no-ver""ify`` devient ``--no-verify``). ``shlex`` lève
        ``ValueError`` si les guillemets sont déséquilibrés.
    """
    lexer = shlex.shlex(
        newlines_to_semicolons(strip_heredocs(command)), posix=True, punctuation_chars=True
    )
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def split_segments(tokens: list[str]) -> list[list[str]]:
    """Découpe les jetons en commandes simples.

    Args:
        tokens: Les jetons de la commande.

    Returns:
        Une liste de commandes simples, séparées aux opérateurs ``;``, ``&&``, ``|``, etc.
    """
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token in SEPARATORS:
            segments.append([])
        else:
            segments[-1].append(token)
    return [segment for segment in segments if segment]


def is_no_verify(argument: str) -> bool:
    """Indique si un argument est ``--no-verify`` ou une abréviation acceptée par git.

    Args:
        argument: Un argument de ligne de commande.

    Returns:
        ``True`` pour ``--no-verify`` et ses préfixes non ambigus (``--no-v``, ``--no-verif``...).
    """
    name = argument.split("=", 1)[0]
    return name.startswith("--no-v") and "--no-verify".startswith(name)


def scan_cluster(flags: str) -> tuple[bool, bool]:
    """Analyse un groupe d'options courtes de ``git commit`` (ex. ``am`` pour ``-am``).

    Args:
        flags: Les lettres qui suivent le tiret.

    Returns:
        Un couple : ``-n`` est présent ; la valeur de la dernière option est le jeton suivant.
    """
    for index, flag in enumerate(flags):
        if flag == "n":
            return True, False
        if flag in SHORT_OPTIONS_WITH_ATTACHED_VALUE:
            return False, False
        if flag in SHORT_OPTIONS_WITH_VALUE:
            return False, index == len(flags) - 1
    return False, False


def scan_options(arguments: list[str], *, short_n: bool) -> str | None:
    """Cherche ``--no-verify`` (et ``-n`` pour ``git commit``) parmi les vraies options.

    Les valeurs d'options (``-m "message"``) sont ignorées : un message qui cite ``-n`` ou
    ``--no-verify`` n'est pas un contournement.

    Args:
        arguments: Les arguments qui suivent la sous-commande git.
        short_n: ``True`` pour traiter ``-n`` comme un alias de ``--no-verify`` (``git commit``).

    Returns:
        Le motif du refus, ou ``None``.
    """
    skip_next = False
    for argument in arguments:
        if skip_next:
            skip_next = False
        elif argument == "--":
            break
        elif argument.startswith("--"):
            if is_no_verify(argument):
                return "--no-verify"
            skip_next = "=" not in argument and argument[2:] in LONG_OPTIONS_WITH_VALUE
        elif argument.startswith("-") and len(argument) > 1:
            found, skip_next = scan_cluster(argument[1:])
            if found and short_n:
                return "git commit -n (équivalent de --no-verify)"
    return None


def split_git(arguments: list[str]) -> tuple[list[str], str, list[str]]:
    """Sépare options globales, sous-commande et arguments d'un appel à git.

    Args:
        arguments: Les arguments qui suivent ``git``.

    Returns:
        Les options globales (valeurs comprises), la sous-commande (vide si absente) et le reste.
    """
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument in GLOBAL_OPTIONS_WITH_VALUE:
            index += 2
        elif argument.startswith("-"):
            index += 1
        else:
            return arguments[:index], argument, arguments[index + 1 :]
    return arguments, "", []


def check_git_configuration(arguments: list[str]) -> str | None:
    """Refuse les réglages git qui désactivent les hooks, y compris via un alias.

    Args:
        arguments: Les arguments à examiner (options globales ou arguments de ``git config``).

    Returns:
        Le motif du refus, ou ``None``.
    """
    for argument in arguments:
        if "core.hookspath" in argument.lower():
            return "modification de core.hooksPath"
        if argument.startswith(("--git-dir", "--work-tree")):
            return "redirection de GIT_DIR / --git-dir"
        if "--no-verify" in argument:
            return "--no-verify dans un alias ou une configuration"
    return None


def check_git_arguments(arguments: list[str]) -> str | None:
    """Vérifie les arguments d'un appel à git.

    Args:
        arguments: Les arguments qui suivent ``git``.

    Returns:
        Le motif du refus, ou ``None`` si l'appel est autorisé.
    """
    global_arguments, subcommand, rest = split_git(arguments)
    reason = check_git_configuration(global_arguments)
    if reason is None and subcommand == "config":
        reason = check_git_configuration(rest)
    if reason is None:
        reason = scan_options(rest, short_n=subcommand == "commit")
    return reason


def check_git(tokens: list[str]) -> str | None:
    """Vérifie chaque appel à git d'une commande simple.

    Args:
        tokens: Les jetons de la commande simple.

    Returns:
        Le motif du refus, ou ``None``.
    """
    for index, token in enumerate(tokens):
        if PurePath(token).name == "git":
            reason = check_git_arguments(tokens[index + 1 :])
            if reason is not None:
                return reason
    return None


def check_env(tokens: list[str]) -> str | None:
    """Refuse les variables d'environnement qui désactivent ou détournent les hooks.

    Args:
        tokens: Les jetons de la commande simple.

    Returns:
        Le motif du refus, ou ``None``.
    """
    for token in tokens:
        match = ENV_ASSIGNMENT.match(token)
        if match:
            name = match.group(1)
            if name in BLOCKED_ENV or name.startswith(BLOCKED_ENV_PREFIXES):
                return f"variable d'environnement {name}"
    return None


def check_precommit(tokens: list[str]) -> str | None:
    """Refuse la désinstallation du hook pre-commit.

    Args:
        tokens: Les jetons de la commande simple.

    Returns:
        Le motif du refus, ou ``None``.
    """
    for index, token in enumerate(tokens):
        if PurePath(token).name in {"pre-commit", "pre_commit"} and "uninstall" in tokens[index:]:
            return "pre-commit uninstall"
    return None


def command_name(tokens: list[str]) -> str:
    """Retourne le nom de la commande, après d'éventuelles affectations de variables.

    Args:
        tokens: Les jetons de la commande simple.

    Returns:
        Le nom de base du premier mot qui n'est pas une affectation, ou une chaîne vide.
    """
    for token in tokens:
        if not ENV_ASSIGNMENT.match(token):
            return PurePath(token).name
    return ""


def check_hook_files(tokens: list[str]) -> str | None:
    """Refuse l'écriture dans ``.git/hooks`` ; sa lecture reste autorisée.

    Args:
        tokens: Les jetons de la commande simple.

    Returns:
        Le motif du refus, ou ``None``.
    """
    for index, token in enumerate(tokens[:-1]):
        if token in REDIRECTIONS and ".git/hooks" in tokens[index + 1]:
            return "écriture dans .git/hooks"
    touches_hooks = any(".git/hooks" in token for token in tokens)
    destructive_find = command_name(tokens) == "find" and bool({"-delete", "-exec"} & set(tokens))
    if touches_hooks and (command_name(tokens) not in READ_ONLY or destructive_find):
        return "modification de .git/hooks"
    return None


def check_nested(tokens: list[str], depth: int) -> str | None:
    """Analyse les commandes passées à un shell (``bash -c``) ou à ``eval``.

    Args:
        tokens: Les jetons de la commande simple.
        depth: La profondeur d'imbrication courante.

    Returns:
        Le motif du refus, ou ``None``.
    """
    for index, token in enumerate(tokens):
        name = PurePath(token).name
        rest = tokens[index + 1 :]
        if name == "eval":
            return analyze(" ".join(rest), depth + 1)
        if name in SHELLS:
            for position, option in enumerate(rest[:-1]):
                if option.startswith("-") and option.endswith("c"):
                    return analyze(rest[position + 1], depth + 1)
    return None


def check_segment(tokens: list[str], depth: int) -> str | None:
    """Applique toutes les vérifications à une commande simple.

    Args:
        tokens: Les jetons de la commande simple.
        depth: La profondeur d'imbrication courante.

    Returns:
        Le motif du refus, ou ``None``.
    """
    for check in (check_env, check_precommit, check_hook_files, check_git):
        reason = check(tokens)
        if reason is not None:
            return reason
    return check_nested(tokens, depth)


def analyze(command: str, depth: int = 0) -> str | None:
    """Analyse une commande Bash.

    Args:
        command: La commande à analyser.
        depth: La profondeur d'imbrication courante (``bash -c``, ``eval``).

    Returns:
        Le motif du refus, ou ``None`` si la commande est autorisée.
    """
    if depth > MAX_DEPTH:
        return "commandes imbriquées trop profondément"
    try:
        tokens = tokenize(command)
    except ValueError:
        return (
            "motif de contournement dans une commande illisible"
            if RAW_FALLBACK.search(command)
            else None
        )
    for segment in split_segments(tokens):
        reason = check_segment(segment, depth)
        if reason is not None:
            return reason
    return None


def main() -> int:
    """Point d'entrée du hook.

    Returns:
        0 si la commande est autorisée, 2 si elle est refusée ou si l'entrée est illisible.
    """
    try:
        command = json.load(sys.stdin)["tool_input"]["command"]
    except (ValueError, KeyError, TypeError):
        print("Bloqué : entrée du hook illisible.", file=sys.stderr)
        return BLOCK_EXIT
    if not isinstance(command, str):
        print("Bloqué : commande Bash absente.", file=sys.stderr)
        return BLOCK_EXIT
    reason = analyze(command)
    if reason is None:
        return 0
    print(
        f"Bloqué : {reason}. Le commit doit passer par 'poe check' (pre-commit).", file=sys.stderr
    )
    return BLOCK_EXIT


if __name__ == "__main__":
    sys.exit(main())
