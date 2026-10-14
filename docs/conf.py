"""Configuration Sphinx."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

project = "welleat-api-sdk"
author = "Louis A."

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
]
napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_use_ivar = True
autodoc_typehints = "description"
nitpicky = True
intersphinx_mapping = {"python": ("https://docs.python.org/3", None)}
default_role = "literal"
nitpick_ignore = [
    # Paramètres de type PEP 695 (`class WelleatClient[C: Credentials]`), sans cible documentable.
    ("py:class", "C"),
    ("py:class", "T"),
    # httpx ne publie pas d'inventaire Sphinx (documentation MkDocs).
    ("py:class", "httpx.Client"),
    ("py:class", "httpx.AsyncClient"),
]
