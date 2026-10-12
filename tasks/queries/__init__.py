"""Query tasks: SQL questions on SQLite databases, assessed in the sandbox on the client's
example rows and on the full database, and their provider.

Banks are converted from Spider into a data directory outside the repository by
`python -m tasks.queries.fetch`, and calibrated against a model by `python -m tasks.calibrate`.
"""

from tasks.queries.provider import QueryProvider, QueryTask, load_bank

__all__ = ["QueryProvider", "QueryTask", "load_bank"]
