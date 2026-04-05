#!/bin/bash
set -e

# Auto-activate venv if not already active
if [ -z "$VIRTUAL_ENV" ]; then
  if [ -d ".venv" ]; then
    source .venv/bin/activate
  else
    echo "ERROR: Run ./setup.sh first"
    exit 1
  fi
fi

# Default: run all instances
INSTANCE=${1:-all}

echo ""
echo "========================================"
echo "  Meridian — CVRP Quantum Solver"
echo "========================================"
echo ""

python3 solver/main.py --instance "$INSTANCE"

echo ""
echo "--- Validating solutions ---"
python3 validate.py
