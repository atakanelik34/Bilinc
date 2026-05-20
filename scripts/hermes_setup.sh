#!/usr/bin/env bash
set -euo pipefail

cat >&2 <<'EOF'
[bilinc] scripts/hermes_setup.sh is a legacy local-runtime helper.
[bilinc] Bilinc 2.0 on PyPI is cloud-only and does not ship the old Hermes bootstrap command.
[bilinc] Use the hosted MCP adapter instead:

  export BILINC_API_KEY=bil_live_...
  python3 -m bilinc.cloud_mcp

EOF

exit 1
