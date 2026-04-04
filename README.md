# Meridian — Quantum-Verified Route Optimization

**Team Viking Cheetahs** | yQuantum 2026 | QuantumCT x RTRC x qBraid Track

---

## Overview

Meridian is a hierarchical quantum-classical optimizer for the Capacitated Vehicle Routing Problem (CVRP). It combines classical angular-sweep clustering with warm-started QAOA circuits running on qBraid's statevector simulator, wrapped in a **Glass Box** verification layer that provides confidence scores, route explainability, complexity budgeting, and fallback guarantees. The result is a system that produces verifiable, explainable quantum-optimized routes for any CVRP instance.

## Architecture

Meridian operates in three phases:

```
┌────────────────────┐     ┌──────────────────────┐     ┌────────────────────┐
│  Phase 1: Classical│     │  Phase 2: Quantum     │     │  Phase 3: Glass Box│
│  Pre-Processing    │────▶│  Core (QAOA)          │────▶│  Verification      │
│                    │     │                       │     │                    │
│  • Angular sweep   │     │  • QUBO formulation   │     │  • Confidence score│
│    clustering      │     │  • Adaptive penalty   │     │  • Route explain.  │
│  • Nearest-neighbor│     │  • Warm-start QAOA    │     │  • Complexity check│
│    warm-start      │     │  • Convergence detect. │     │  • Fallback cascade│
│  • Angle init.     │     │  • Statevector sim.   │     │  • Approx. ratio   │
└────────────────────┘     └──────────────────────┘     └────────────────────┘
```

**Dual Mode:**
- **Full QUBO** (Instances 1–2, ≤3 customers): Single TSP QUBO on all customers, split into vehicle routes.
- **HQCD** (Instances 3–4, >3 customers): Hierarchical Quantum-Classical Decomposition — cluster first, then QAOA per vehicle.

## QUBO Formulation

Binary variables: `x_{i,p} ∈ {0,1}` — node `i` is at position `p` in the tour.

For `n` nodes (depot + customers), we use `n²` qubits per vehicle.

**Objective — minimize tour distance:**

```
H_obj = Σ_{i≠j} Σ_p  d(i,j) · x_{i,p} · x_{j,(p+1) mod n}
```

**Constraint 1 — each position filled exactly once:**

```
H_c1 = A · Σ_p (1 − Σ_i x_{i,p})²
```

**Constraint 2 — each node visited exactly once:**

```
H_c2 = A · Σ_i (1 − Σ_p x_{i,p})²
```

**Total QUBO:**

```
H = H_obj + H_c1 + H_c2
```

Penalty weight `A` is initialized as `10 · max_edge_distance` and adapted via the penalty loop.

## How to Run

```bash
pip install -r requirements.txt
python solver/main.py --instance all
```

Or individual instances:

```bash
python solver/main.py --instance 1 --mode full --p 3
python solver/main.py --instance 3 --mode hqcd --p 2
```

Or use the shell script:

```bash
chmod +x run_all.sh
./run_all.sh
```

## Results

| Instance | Nv | C | Customers | Mode | Qubits/Vehicle | Total Qubits |
|---|---|---|---|---|---|---|
| 1 | 2 | 5 | 3 | Full | 16 | 16 |
| 2 | 2 | 2 | 3 | Full | 16 | 16 |
| 3 | 3 | 2 | 6 | HQCD | 9 | 9 × 3 |
| 4 | 4 | 3 | 12 | HQCD | 16 | 16 × 4 |

Detailed results including distances and approximation ratios are in `results/resource_table.md`.

## Glass Box Verification

The Glass Box layer provides:

1. **Confidence Scoring**: Ratio of the best solution's probability to the second-best. Higher confidence means the quantum optimizer clearly distinguished the optimal route.

2. **Route Explainability**: For each vehicle, the Glass Box reports the winning route, next-best alternative, selection confidence, and penalty evolution history.

3. **Complexity Budgeting**: Monitors qubit count, gate count, and wall-clock time against instance-size-dependent budgets. Triggers adaptation (reduce QAOA depth) or fallback (classical solver) when budgets are exceeded.

4. **Fallback Cascade**: If QAOA times out, produces low-confidence results, or exceeds complexity budgets, the system falls back to classical nearest-neighbor routing. Every fallback is logged with its reason.

5. **Approximation Ratio**: Compares quantum solution distance to classical baselines (brute-force optimal for small instances, nearest-neighbor for larger ones).

6. **LLM Synthesis Engine** (optional): Local Ollama/codellama integration for generating human-readable explanations of QUBO formulations. Demonstrates future extensibility — the synthesis engine can handle problem classes not yet built into the solver.

## Scalability Analysis

| Instance | Customers | Vehicle Clusters | Qubits per Vehicle | Total QAOA Runs |
|---|---|---|---|---|
| 1 | 3 | 1 (full) | 16 | 1 |
| 2 | 3 | 1 (full) | 16 | 1 |
| 3 | 6 | 3 × 2 customers | 9 | 3 |
| 4 | 12 | 4 × 3 customers | 16 | 4 |

**HQCD vs Full QUBO**: Full QUBO for 6 customers would require 49 qubits (7² nodes) — impractical for statevector simulation. HQCD decomposes this into 3 independent 9-qubit problems, each solvable in seconds. This demonstrates the scaling advantage of hierarchical decomposition.

## Dependencies

- Qiskit ≥ 1.0 (quantum circuits)
- Qiskit Aer (statevector simulation)
- qBraid ≥ 0.6 (quantum cloud runtime)
- SciPy (COBYLA optimizer)
- NumPy (linear algebra)
- Ollama (optional, local LLM synthesis)

## References

1. Farhi, E., Goldstone, J., & Gutmann, S. (2014). *A Quantum Approximate Optimization Algorithm*. arXiv:1411.4028.
2. Egger, D. J., et al. (2021). *Warm-starting quantum optimization*. Quantum, 5, 479.
3. qBraid Documentation — qbraid.com/docs
4. Dantzig, G. B., & Ramser, J. H. (1959). *The Truck Dispatching Problem*. Management Science, 6(1), 80–91.
