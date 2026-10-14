# Typage et docstrings

- Toute fonction, méthode et attribut public est annoté. `Any` est interdit (`ANN401`, `disallow_any_explicit`) : utiliser `object` + narrowing, `Protocol`, `TypedDict` ou `NewType`.
- `# type: ignore` et `# noqa` exigent un code précis (`# type: ignore[arg-type]`) et un commentaire justifiant l'exception.
- Docstrings au style Google (rendues par `sphinx.ext.napoleon`), première ligne sur une phrase terminée par un point.
- Ne pas répéter les types dans la docstring : ils viennent des annotations (`autodoc_typehints = "description"`).
- Sections `Args:` (tous les paramètres), `Returns:` et `Raises:` obligatoires quand elles s'appliquent.
- Un commit n'est possible que si le juge (`ask-judge`, qui lance `poe check`) l'accepte : ne jamais contourner le hook.
