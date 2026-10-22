# Local semantic recall: the embedding daemon

The local (self-hosted) runtime can add a semantic signal to recall with
persisted vectors from `intfloat/multilingual-e5-small`, run as an int8 ONNX
graph. One process owns the model; every MCP process sharing the database
uses its vectors without loading a model itself.

## How it works

- `python -m bilinc.embeddings serve` loads the model once and keeps the
  `memory_embeddings` table of the SQLite database current. It is the only
  process that writes the table.
- Each memory is embedded from its key words and the strings in its value,
  with the real letters (no folding), in chunks of 180 words. A memory scores
  as its best chunk.
- The daemon re-embeds a memory when its text changes. It removes the vectors
  of memories that are forgotten, out of scope, or embedded with another model
  or revision. Forget also deletes a memory's vectors immediately.
- Recall asks the daemon to encode the query over a unix socket that only the
  user can open (`~/.bilinc/embed.sock`, or `BILINC_EMBED_SOCKET`). If the table has no vectors for the
  daemon's model, or the socket does not answer, recall runs without the
  semantic signal.
- The signal's fusion weight is `INTELLIGENT_RECALL_INDEXED_SEMANTIC_WEIGHT`.
  `BILINC_SEMANTIC_RRF_WEIGHT` overrides it.

## Install

The daemon runs best in its own virtual environment, so the model's
dependencies stay out of the interpreter the MCP server uses:

```bash
python3 -m venv ~/.bilinc-embed/venv
~/.bilinc-embed/venv/bin/pip install -e '/path/to/Bilinc[internal,embeddings]'
~/.bilinc-embed/venv/bin/python -m bilinc.embeddings serve --db ~/bilinc.db
```

The MCP server's interpreter needs `numpy` (in the `internal` extra) to score
the vectors; it never imports the model.

The first start downloads the pinned model and tokenizer revisions from
Hugging Face into the local cache. Later starts can run offline with
`HF_HUB_OFFLINE=1`.

## Options

- `--exclude-prefix PREFIX` (repeatable): key prefixes left out of the vectors.
  The default leaves out `session_archive:` and `hermes_turn_`: raw
  transcripts are long and noisy, and they stay in full-text search.
- `--threads N`: encoder threads (default 2).
- `--batch N`, `--poll SECONDS`: indexing batch size and pause between passes.
- `python -m bilinc.embeddings status` prints the running daemon's model and
  indexing state.

## Running it as a macOS login service

A launchd agent keeps the daemon running. Replace the paths with yours:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>local.bilinc-embed</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/YOU/.bilinc-embed/venv/bin/python</string>
    <string>-m</string><string>bilinc.embeddings</string><string>serve</string>
    <string>--db</string><string>/Users/YOU/bilinc.db</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict><key>HF_HUB_OFFLINE</key><string>1</string></dict>
  <key>KeepAlive</key><true/>
  <key>RunAtLoad</key><true/>
  <key>ProcessType</key><string>Background</string>
  <key>StandardErrorPath</key><string>/Users/YOU/.bilinc-embed/daemon.log</string>
</dict>
</plist>
```

## Privacy

Vectors are derived from memory values and stay in the same database file.
The table is not synced anywhere by Bilinc. Forgetting a memory deletes its
vectors along with the row.
