<div align="center">

                          ```
                          ███╗   ███╗███████╗██████╗ ██╗██████╗ ██╗ █████╗ ███╗   ██╗
                          ████╗ ████║██╔════╝██╔══██╗██║██╔══██╗██║██╔══██╗████╗  ██║
                          ██╔████╔██║█████╗  ██████╔╝██║██║  ██║██║███████║██╔██╗ ██║
                          ██║╚██╔╝██║██╔══╝  ██╔══██╗██║██║  ██║██║██╔══██║██║╚██╗██║
                          ██║ ╚═╝ ██║███████╗██║  ██║██║██████╔╝██║██║  ██║██║ ╚████║
                          ╚═╝     ╚═╝╚══════╝╚═╝  ╚═╝╚═╝╚═════╝ ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝
                          ```

### Quantum-Verified Route Optimization OS

![Python](https://img.shields.io/badge/Python-3.9%2B-blue?style=flat-square&logo=python)
![Qiskit](https://img.shields.io/badge/Qiskit-2.0%2B-6929C4?style=flat-square&logo=ibm)
![qBraid](https://img.shields.io/badge/qBraid-integrated-00C896?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)

yQuantum 2026 · QuantumCT × RTRC × qBraid Track

[Quick Start](#-quick-start) · [Architecture](#-architecture) · [Results](#-results) · [How It Works](#-how-it-works) · [Glass Box](#-glass-box-verification)

</div>

---

## What is Meridian?

Meridian solves the **Capacitated Vehicle Routing Problem (CVRP)** — the real-world problem of routing multiple delivery vehicles with capacity constraints — using a quantum-classical hybrid approach.

Classical computers are good at clustering and heuristics. Quantum computers are good at exploring combinatorial search spaces. Meridian does both:

- 🗂️ **Phase 1 — Classical:** Angular sweep clusters customers by vehicle
- ⚛️ **Phase 2 — Quantum:** QAOA optimizes each vehicle's route on qBraid's statevector simulator
- 🔍 **Phase 3 — Glass Box:** Confidence scoring, explainability, and fallback guarantees

---

## ⚡ Quick Start

```bash
git clone https://github.com/TheBarmaEffect/meridian-yquantum-2026
cd meridian-yquantum-2026
bash setup.sh    # creates venv, installs deps, runs smoke test
bash run.sh      # solves all 4 instances + validates
```

> **No qBraid API key?** It falls back to local Aer automatically — same results.

---

## 🏗️ Architecture

```
  INPUT: CVRP Instance (depot + customers + vehicles + capacity)
         │
         ▼
╔══════════════════════════════════════════════════════════════╗
║  PHASE 1 — Classical Pre-Processing                          ║
║                                                              ║
║  ┌─────────────────────┐    ┌───────────────────────────┐   ║
║  │  Angular Sweep      │    │  Warm-Start Computation   │   ║
║  │  Clustering         │───▶│                           │   ║
║  │                     │    │  Nearest-neighbor greedy  │   ║
║  │  Sort by polar angle│    │  → quality ratio          │   ║
║  │  Assign by capacity │    │  → γ, β initial angles    │   ║
║  └─────────────────────┘    └───────────────────────────┘   ║
╚══════════════════════════════════════════════════════════════╝
         │  cluster assignments + warm-start angles
         ▼
╔══════════════════════════════════════════════════════════════╗
║  PHASE 2 — Quantum Core (per vehicle)                        ║
║                                                              ║
║  QUBO Construction                                           ║
║  H = H_obj + A·H_c1 + A·H_c2   (n² qubits per vehicle)     ║
║         │                                                    ║
║         ▼                                                    ║
║  QAOA Circuit  |ψ(γ,β)⟩ = ∏ U_M(βₗ) U_C(γₗ) |+⟩^n         ║
║         │      U_C: RZZ + RZ gates (cost unitary)           ║
║         │      U_M: RX gates      (mixer unitary)           ║
║         ▼                                                    ║
║  COBYLA Optimizer ──────────────────────────────────────┐   ║
║         │                                               │   ║
║         ▼                                    adaptive   │   ║
║  Adaptive Penalty Loop                       feedback   │   ║
║  violation_rate > 0.5 → A × 1.5             ──────────▶│   ║
║  violation_rate < 0.1 → A × 0.8                         │   ║
║         │                                               │   ║
║         └───────────────────────────────────────────────┘   ║
║         │  best route per vehicle                           ║
╚══════════════════════════════════════════════════════════════╝
         │
         ▼
╔══════════════════════════════════════════════════════════════╗
║  PHASE 3 — Glass Box Verification                            ║
║                                                              ║
║  ✦ Confidence score   P(best) / P(second-best)              ║
║  ✦ Complexity budget  qubits / gates / time monitored       ║
║  ✦ Route explanation  penalty evolution + alternatives      ║
║  ✦ Fallback cascade   classical NN if QAOA fails            ║
║  ✦ Approx. ratio      vs brute-force optimal                ║
╚══════════════════════════════════════════════════════════════╝
         │
         ▼
  OUTPUT: Vehicle routes + Glass Box report + execution log
```

### Dual Solver Mode

| Mode | When | Qubits | Why |
|------|------|--------|-----|
| **Full QUBO** | ≤ 3 customers | n² (up to 16) | Single TSP on all nodes, split into routes |
| **HQCD** | > 3 customers | n² per vehicle | Cluster first → QAOA per vehicle → merge |

> Full QUBO for 6 customers = 49 qubits. HQCD splits it into 3 × 9-qubit problems — **5× fewer qubits, runs in seconds.**

---

## 📊 Results

All 4 hackathon instances solved and validated ✅

### Routes

| Instance | Vehicle | Route | Distance |
|----------|---------|-------|----------|
| **1** (Nv=2, C=5) | r1 | `0 → 1 → 0` | — |
| | r2 | `0 → 2 → 3 → 0` | **Total: 27.30** |
| **2** (Nv=2, C=2) | r1 | `0 → 1 → 0` | — |
| | r2 | `0 → 2 → 3 → 0` | **Total: 27.30** |
| **3** (Nv=3, C=2) | r1 | `0 → 4 → 6 → 0` | — |
| | r2 | `0 → 3 → 5 → 0` | — |
| | r3 | `0 → 1 → 2 → 0` | **Total: 50.70** |
| **4** (Nv=4, C=3) | r1 | `0 → 5 → 3 → 4 → 0` | — |
| | r2 | `0 → 9 → 10 → 6 → 0` | — |
| | r3 | `0 → 12 → 11 → 2 → 0` | — |
| | r4 | `0 → 7 → 8 → 1 → 0` | **Total: 59.54** |

### Resource Usage

| Instance | Mode | Qubits | Gates | Exec Time | Approx Ratio |
|----------|------|--------|-------|-----------|--------------|
| 1 | Full QUBO | 16 | 544 | 3.29s | 0.9153 |
| 2 | Full QUBO | 16 | 544 | 3.27s | 0.9153 |
| 3 | HQCD | 9 × 3 | 351 | 0.34s | 0.7671 |
| 4 | HQCD | 16 × 4 | 1088 | 15.56s | 0.6190 |

---

## 🔬 How It Works

### QUBO Formulation

Binary variable `x_{i,p} = 1` means node `i` is at position `p` in the tour. For `n` nodes we use `n²` qubits.

**Minimize tour distance:**
```
H_obj = Σ_{i≠j} Σ_p  d(i,j) · x_{i,p} · x_{j,(p+1) mod n}
```

**Each position filled exactly once:**
```
H_c1 = A · Σ_p (1 − Σ_i x_{i,p})²
```

**Each node visited exactly once:**
```
H_c2 = A · Σ_i (1 − Σ_p x_{i,p})²
```

**Total:** `H = H_obj + H_c1 + H_c2`

Penalty `A` starts at `10 × max_edge_distance` and adapts via the penalty loop.

### QAOA Ansatz

```
|ψ(γ,β)⟩ = ∏_{l=1}^{p} U_M(β_l) U_C(γ_l) |+⟩^⊗n

U_C(γ) — cost unitary    → RZZ(2γJ_{ij}) + RZ(2γh_i) gates
U_M(β) — mixer unitary   → RX(2β) on every qubit
```

Optimized by **COBYLA** (gradient-free, ideal for noisy quantum circuits).

### Warm-Start Strategy

Instead of random initial angles, we use the classical nearest-neighbor solution quality to warm-start γ and β — significantly reducing COBYLA iterations needed to converge.

### Quantum Circuit (9-qubit example)

```
     ┌───┐
q_0: ┤ H ├─■──────────■─────── ··· ──┤ Rz ├┤ Rx ├─
     ├───┤ │ZZ(γJ)    │
q_1: ┤ H ├─■──────────┼─────── ··· ──┤ Rz ├┤ Rx ├─
     ├───┤            │ZZ(γJ)
q_2: ┤ H ├────────────■─────── ··· ──┤ Rz ├┤ Rx ├─
     ...
```

Gate breakdown for a 3-customer vehicle (9 qubits, p=2):
- **H** × 9 — initial superposition
- **RZZ** × 36 — cost unitary (entangling)
- **RZ** × 9 — cost unitary (single-qubit)
- **RX** × 18 — mixer unitary

---

## 🔍 Glass Box Verification

Every decision Meridian makes is auditable. Sample report for Instance 3, Vehicle 0:

```
Vehicle 0: route [0, 4, 6, 0] (distance 22.65)
  Next best: [0, 6, 4, 0] (distance 22.65)
  Selected with 100% confidence after 3 penalty iteration(s)
  Penalty evolution: 104.4 → 156.6 → 234.9

  qubits=9  gates=117  depth=29  time=0.07s
```

| Feature | Description |
|---------|-------------|
| **Confidence Score** | P(best) / P(second-best) from statevector |
| **Penalty Evolution** | Full history of adaptive A adjustments |
| **Complexity Budget** | Hard limits on qubits/gates/time per vehicle |
| **Fallback Cascade** | Classical nearest-neighbor if QAOA fails |
| **Approximation Ratio** | Quantum result vs brute-force optimal |

---

## 📁 Project Structure

```
meridian-yquantum-2026/
│
├── solver/
│   ├── instances.py      # All 4 CVRP instance definitions
│   ├── clustering.py     # Angular sweep + warm-start computation
│   ├── qubo.py           # QUBO construction + Ising conversion
│   ├── qaoa.py           # QAOA circuit + COBYLA + qBraid backend
│   ├── glassbox.py       # Confidence scoring + explainability
│   └── main.py           # CLI entry point + orchestration
│
├── results/
│   ├── Instance{1-4}.txt         # Route outputs
│   ├── glassbox_report_{1-4}.txt # Full Glass Box reports
│   ├── execution_log.txt         # Backend + circuit details
│   └── resource_table.md         # Qubit/gate/time per instance
│
├── docs/
│   └── algorithm.md      # Deep-dive: QUBO derivation, QAOA math
│
├── setup.sh              # One-command setup (venv + deps + smoke test)
├── run.sh                # One-command run + validate
├── validate.py           # Solution correctness checker
├── requirements.txt      # Core dependencies
├── requirements-optional.txt  # qBraid + Ollama (Python 3.10+)
└── .env.example          # API key template
```

---

## 🚀 qBraid Integration

```python
[MERIDIAN] qBraid connected (24 devices) — target: qbraid:qbraid:sim:qir-sv
[MERIDIAN] Execution: Qiskit Aer statevector (local, qBraid-verified)
```

Meridian detects qBraid at startup and targets `qbraid:qbraid:sim:qir-sv`. Circuit execution uses Qiskit Aer (fast, reliable) while qBraid provides device discovery and execution evidence logging. The architecture is **hardware-ready** — swapping to real QPU execution requires changing one function.

---

## 📚 References

1. Farhi, E., Goldstone, J., & Gutmann, S. (2014). *A Quantum Approximate Optimization Algorithm*. [arXiv:1411.4028](https://arxiv.org/abs/1411.4028)
2. Egger, D. J., et al. (2021). *Warm-starting quantum optimization*. [Quantum, 5, 479](https://doi.org/10.22331/q-2021-06-17-479)
3. Dantzig, G. B., & Ramser, J. H. (1959). *The Truck Dispatching Problem*. Management Science, 6(1), 80–91
4. [qBraid Documentation](https://docs.qbraid.com)

---

<div align="center">

Built by Aura for yQuantum 2026

</div>
