#!/bin/bash
# Quick launcher for the LoreKit TUI
ROOT="$(cd "$(dirname "$0")" && pwd)"
source "$ROOT/.venv/bin/activate"
cd "$ROOT/examples/tui" && npx tsx src/index.tsx
