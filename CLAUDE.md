# welleat-api-sdk

Module Python servant de wrapper à l'API Welleat. Elle est utile à l'implémentation des applications de la flotte IoT.

## Qualité : une seule commande

`uv run poe check` enchaîne, dans cet ordre, et s'arrête au premier échec :

1. `lint` : ruff (annotations, docstrings Google, sécurité, imports)
2. `format` : `ruff format --check`
3. `typecheck` : mypy en mode strict
4. `suppressions` : refuse `noqa` / `type: ignore` sans raison (` - raison`)
5. `secrets` : detect-secrets sur les fichiers suivis par git
6. `test` : pytest, couverture de `src/` d'au moins 90 %

## Valider son travail : le juge

Tu travailles dans un conteneur Docker (`docker compose run --rm agent`) sans accès direct à Internet :
seuls les hôtes de `docker/proxy/allowed_hosts.txt` sont joignables, via un proxy.

- **Avant tout commit, et chaque fois que tu veux valider ton travail, interroge le juge** : `ask-judge`
  (arbre de travail) ou `ask-judge --index` (contenu indexé). Le juge est un serveur interne
  (`http://judge:8080`) qui lance `uv run poe check` sur une copie du projet et renvoie le verdict et la sortie.
  Code de sortie 0 = accepté ; sinon corrige puis recommence.
- Le hook git `pre-commit` appelle le juge : **un commit n'est possible que si le juge accepte**. Ne jamais
  contourner le hook (`--no-verify`, `SKIP=`, modification de `.git/hooks`). Un hook Claude Code
  (`.claude/hooks/block-hook-bypass.py`) refuse ces commandes.
- Tu peux lancer `uv run poe check` (ou `lint`, `typecheck`, `test`...) toi-même pour itérer vite, mais seul
  le verdict du juge compte.
- Fichiers en **lecture seule** pour toi : `.claude/`, `CLAUDE.md`, `ruff.toml`, `mypy.ini`, `pytest.ini`,
  `poe_tasks.toml`, `scripts/`, `.pre-commit-config.yaml`, `.secrets.baseline`, `docker-compose.yml`, `docker/`,
  `.git/hooks` et `.git/config`. Ne cherche pas à les modifier ni à assouplir les règles : si une règle te
  bloque, explique pourquoi dans ta réponse et laisse l'humain trancher.

`uv run poe check` enchaîne, dans cet ordre, et s'arrête au premier échec :

1. `lint` : ruff (annotations, docstrings Google, sécurité, imports)
2. `format` : `ruff format --check`
3. `typecheck` : mypy en mode strict
4. `suppressions` : refuse `noqa` / `type: ignore` sans ` -- raison`
5. `secrets` : detect-secrets sur les fichiers suivis par git
6. `test` : pytest, couverture de `src/` d'au moins 90 %

## Règles

- Pas de `cast`, de `Any`, ni de `pytest.mark.skip` (ruff les refuse). Une suppression `# noqa: CODE` ou
  `# type: ignore[code]` doit se terminer par ` - raison`. Complexité cyclomatique maximale : 10.
Les règles de code sont dans `.claude/rules/` (typage strict, docstrings). Les lire avant d'écrire du code.

## Organisation

- `src/welleat_api_sdk/` : code du projet
- `tests/` : tests pytest
- `scripts/` : outils de contrôle du projet (lecture seule pour l'agent)
- `docs/` : documentation Sphinx (`uv run poe docs`)
- `.claude/agents/`, `.claude/skills/` : agents et skills du projet
- `docker-compose.yml`, `docker/` : environnement de l'agent (proxy, juge, agent)
