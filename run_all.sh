#!/bin/bash
set -e
echo "============================================"
echo "  Meridian — Running all CVRP instances"
echo "============================================"
python solver/main.py --instance all
echo ""
echo "Results written to results/"
echo "Done."
