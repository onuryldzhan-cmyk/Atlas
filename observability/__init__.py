"""Read-only observability sources for the lightweight Atlas panel.

Nothing in this package starts Atlas runtime services, connects to an
exchange, writes runtime state, or triggers a test run. Every module here
reads already-produced artifacts and reports "unavailable" when they are
missing or unparseable, rather than inventing a value.
"""
