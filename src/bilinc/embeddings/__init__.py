"""Persisted semantic vectors for local recall.

One process (the embedding daemon, ``python -m bilinc.embeddings serve``)
owns the model. It is the only writer of the ``memory_embeddings`` table and
encodes queries for every MCP process over a unix socket, so the MCP
processes never load a model. Recall uses the vectors when the table holds
rows for the daemon's model and the socket answers; otherwise the semantic
signal is simply absent. Internal to the local runtime; not part of the
public package.
"""
