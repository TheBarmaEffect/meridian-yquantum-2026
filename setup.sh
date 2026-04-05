#!/bin/bash
set -e

echo ""
echo "========================================"
echo "  Meridian — Setup"
echo "========================================"
echo ""

# Check Python version
PY=$(python3 --version 2>&1 | awk '{print $2}')
MAJOR=$(echo $PY | cut -d. -f1)
MINOR=$(echo $PY | cut -d. -f2)

echo "Python version: $PY"

if [ "$MAJOR" -lt 3 ] || ([ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 9 ]); then
  echo ""
  echo "ERROR: Python 3.9 or higher is required (you have $PY)"
  echo "Download from https://www.python.org/downloads/"
  exit 1
fi

echo "Python OK ✅"
echo ""

# Create venv
if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
else
  echo "Virtual environment already exists, reusing..."
fi

# Activate
source .venv/bin/activate
echo "Venv activated ✅"
echo ""

# Upgrade pip silently
pip install --upgrade pip --quiet

# Install core requirements
echo "Installing dependencies (this takes ~1 minute)..."
pip install -r requirements.txt --quiet
echo "Core dependencies installed ✅"

# Try optional deps (qbraid, ollama) — not critical
if [ "$MINOR" -ge 10 ]; then
  echo "Installing optional packages (qBraid, Ollama)..."
  pip install -r requirements-optional.txt --quiet 2>/dev/null && \
    echo "Optional dependencies installed ✅" || \
    echo "Optional dependencies skipped (non-critical) ⚠️"
else
  echo "Python < 3.10 — skipping qBraid/Ollama (not needed, runs on local Aer) ⚠️"
fi
echo ""

# Set up .env if missing
if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "Created .env from template"
  echo "  → If you have a qBraid API key, paste it into .env"
  echo "  → Otherwise, it will run with local Aer simulator (still works)"
  echo ""
fi

# Quick smoke test
echo "Running smoke test..."
python3 -c "
import sys, os
sys.path.insert(0, os.path.join(os.getcwd(), 'solver'))
from qaoa import build_qaoa_circuit, simulate_circuit
from qubo import build_tsp_qubo, qubo_to_ising
import numpy as np
dist = np.array([[0,5],[5,0]], dtype=float)
Q = build_tsp_qubo(2, dist, 10.0)
h, J, off = qubo_to_ising(Q)
qc = build_qaoa_circuit(4, h, J, 2, [0.5, 0.3, 0.5, 0.3])
probs = simulate_circuit(qc)
assert len(probs) == 16
print('Smoke test passed ✅')
"

echo ""
echo "========================================"
echo "  Setup complete! Now run:"
echo ""
echo "  bash run.sh"
echo ""
echo "  (run.sh auto-activates the venv)"
echo "========================================"
echo ""
