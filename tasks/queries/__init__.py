"""Query tasks: SQL questions on SQLite databases, assessed in the sandbox on the client's
example rows and on the full database, and their provider.

The built-in bank is `BANK`, a few questions on two small databases kept as SQL scripts.
Larger banks are converted from Spider into a data directory outside the repository by
`python -m tasks.queries.fetch`, and calibrated against a model by `python -m tasks.calibrate`.
"""

from pathlib import Path

from tasks.queries.provider import QueryProvider, QueryTask, load_bank

BANK = Path(__file__).with_name("bank")
"""The built-in query bank."""

__all__ = ["BANK", "QueryProvider", "QueryTask", "load_bank"]
