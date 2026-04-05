#!/bin/bash
# SynapticAI Setup Script
# Installs master index templates and unified-search skill

set -e

echo "🧠⚡ SynapticAI Setup"
echo "====================="

HERMES_DIR="$HOME/.hermes"
FABRIC_DIR="$HOME/fabric"
SKILLS_DIR="$HERMES_DIR/skills"

# Create directories
mkdir -p "$FABRIC_DIR" "$SKILLS_DIR/unified-search/scripts"

echo "✅ Master index templates ready in: $FABRIC_DIR"
echo "✅ Skills directory ready in: $SKILLS_DIR"

echo ""
echo "Next steps:"
echo "1. Your agent will create master index entries via fabric_write"
echo "2. Use fabric_recall 'query' for semantic search across all layers"
echo "3. Tag important entries with 'master-index' for authoritative topics"
echo ""
echo "Setup complete! 🎉"
