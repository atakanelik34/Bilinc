"""``python -m bilinc.embeddings serve|status`` for the local embedding daemon."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from bilinc.embeddings import client
from bilinc.embeddings.daemon import RECOMMENDED_EXCLUDE_PREFIXES, EmbeddingDaemon


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bilinc.embeddings")
    sub = parser.add_subparsers(dest="cmd", required=True)
    serve = sub.add_parser("serve", help="run the daemon")
    serve.add_argument("--db", default=os.environ.get("BILINC_DB_PATH", str(Path.home() / "bilinc.db")))
    serve.add_argument("--socket", default=str(client.socket_path()))
    serve.add_argument(
        "--encoder", choices=("onnx-e5", "workers-ai"), default="onnx-e5",
        help="onnx-e5 runs the model here; workers-ai calls Cloudflare (memory text leaves this machine)",
    )
    serve.add_argument("--model", default=None, help="Workers AI model (default @cf/baai/bge-m3)")
    serve.add_argument("--threads", type=int, default=2)
    serve.add_argument("--batch", type=int, default=None, help="texts per encoder call (default 4 local, 32 Workers AI)")
    serve.add_argument("--poll", type=float, default=10.0)
    serve.add_argument(
        "--exclude-prefix", action="append", default=None,
        help=f"key prefix to leave out of the vectors (repeatable; default {', '.join(RECOMMENDED_EXCLUDE_PREFIXES)})",
    )
    sub.add_parser("status", help="ask a running daemon for its state")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.cmd == "status":
        reply = client.request({"op": "health"})
        print(json.dumps(reply or {"running": False}, indent=2))
        return 0 if reply else 1

    if args.encoder == "workers-ai":
        from bilinc.embeddings.encoder import WORKERS_AI_DEFAULT_MODEL, WorkersAIEncoder

        encoder = WorkersAIEncoder(args.model or WORKERS_AI_DEFAULT_MODEL)
        batch = args.batch or 32
    else:
        if args.model:
            parser.error("--model applies to --encoder workers-ai only")
        from bilinc.embeddings.encoder import OnnxE5Encoder

        encoder = OnnxE5Encoder(threads=args.threads)
        batch = args.batch or 4
    daemon = EmbeddingDaemon(
        args.db,
        encoder,
        socket_path=args.socket,
        exclude_prefixes=RECOMMENDED_EXCLUDE_PREFIXES if args.exclude_prefix is None else args.exclude_prefix,
        batch_size=batch,
        poll_seconds=args.poll,
    )
    asyncio.run(daemon.serve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
