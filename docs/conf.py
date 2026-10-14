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
