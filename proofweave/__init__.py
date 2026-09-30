"""ProofWeave -- reproducible supply-chain & partnership graph.

The package version lives here and nowhere else: ``pyproject.toml`` reads it
via ``[tool.setuptools.dynamic]`` and the FastAPI app reports it, so the two can
never disagree.
"""

__version__ = "0.2.0"

__all__ = ["__version__"]
