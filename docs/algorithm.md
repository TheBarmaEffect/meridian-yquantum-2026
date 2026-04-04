# Meridian — Algorithm Documentation

## 1. CVRP Problem Formulation

The **Capacitated Vehicle Routing Problem (CVRP)** asks: given a depot, a set of customers with unit demands, and a fleet of `Nv` vehicles each with capacity `C`, find routes for all vehicles such that:

- Every customer is visited exactly once.
- Each route starts and ends at the depot.
- No vehicle visits more than `C` customers.
- Total travel distance is minimized.

Formally, let `G = (V, E)` where `V = {0, 1, …, n}` (0 = depot) and `d(i,j)` is the Euclidean distance between nodes `i` and `j`.

## 2. Decomposition Strategy: HQCD

**Hierarchical Quantum-Classical Decomposition** splits the CVRP into:

1. **Classical clustering** (Phase 1): Assign customers to vehicles using angular-sweep heuristic.
2. **Quantum routing** (Phase 2): Solve the TSP for each vehicle's cluster independently via QAOA.

**Why HQCD beats full QUBO for instances 3–4:**

A full CVRP QUBO for `n` customers requires `O(n²)` qubits (TSP encoding). For 6 customers (Instance 3), that's `7² = 49` qubits — the statevector has `2^49 ≈ 562 × 10¹²` amplitudes, far exceeding available memory.

HQCD decomposes Instance 3 into three 2-customer TSPs, each needing only `3² = 9` qubits. The statevector is just 512 amplitudes — solvable in milliseconds.

| Instance | Full QUBO Qubits | HQCD Qubits (max per vehicle) |
|---|---|---|
| 1 | 16 | 16 (single run) |
| 2 | 16 | 16 (single run) |
| 3 | 49 (infeasible) | 9 |
| 4 | 169 (infeasible) | 16 |

## 3. QUBO Derivation

### Variables

`x_{i,p} ∈ {0, 1}` — 1 iff node `i` is at position `p` in the tour.

For `n` nodes: `n²` binary variables (qubits).

### Objective: Minimize Tour Distance

```
H_obj = Σ_{i≠j} Σ_{p=0}^{n-1}  d(i,j) · x_{i,p} · x_{j, (p+1) mod n}
```

This sums the distance between consecutive nodes in the tour.

### Constraint 1: Each Position Filled Exactly Once

```
H_c1 = A · Σ_{p=0}^{n-1} (1 − Σ_{i=0}^{n-1} x_{i,p})²
```

Expanding: `H_c1 = A · Σ_p [ −Σ_i x_{i,p} + 2 Σ_{i<j} x_{i,p} x_{j,p} + 1 ]`

### Constraint 2: Each Node Visited Exactly Once

```
H_c2 = A · Σ_{i=0}^{n-1} (1 − Σ_{p=0}^{n-1} x_{i,p})²
```

Expanding: `H_c2 = A · Σ_i [ −Σ_p x_{i,p} + 2 Σ_{p<q} x_{i,p} x_{i,q} + 1 ]`

### Full QUBO Hamiltonian

```
H = H_obj + H_c1 + H_c2
```

The QUBO matrix `Q` is `n² × n²` (upper triangular), encoding all linear and quadratic terms.

### Penalty Weight

`A` is initialized as `10 · max(d(i,j))` — large enough to enforce constraints, but not so large as to flatten the optimization landscape.

## 4. QAOA Ansatz

The Quantum Approximate Optimization Algorithm prepares the state:

```
|ψ(γ,β)⟩ = ∏_{l=1}^{p} U_M(β_l) · U_C(γ_l) · |+⟩^⊗n²
```

### Cost Unitary U_C(γ)

```
U_C(γ) = exp(−iγ · C_Ising)
```

where `C_Ising` is the Ising Hamiltonian obtained from the QUBO via substitution `x_i = (1 − Z_i) / 2`.

**Decomposition into gates:**
- **RZZ(2γ · J_{ij})** for each coupling term `J_{ij} · Z_i Z_j`.
- **RZ(2γ · h_i)** for each local field `h_i · Z_i`.

### Mixer Unitary U_M(β)

```
U_M(β) = exp(−iβ · B),  where  B = Σ_i X_i
```

**Decomposition:** `RX(2β)` on every qubit.

### Layer Count

- Instances 1–2 (≤3 customers): `p = 3` layers.
- Instances 3–4 (>3 customers): `p = 2` layers (for circuit depth management).

## 5. Warm-Start Strategy

Following Egger et al. (2021), we initialize QAOA angles from a classical nearest-neighbor solution.

1. Run greedy nearest-neighbor on the vehicle's cluster.
2. Compute solution quality:
   ```
   quality = lower_bound / greedy_distance,  clamped to [0, 1]
   ```
   where `lower_bound` is estimated from the shortest edges.
3. Initialize angles:
   ```
   γ_l = (π/4) · quality
   β_l = (π/4) · (1 − quality)
   ```

High quality (greedy close to optimal) → larger γ (stronger cost drive), smaller β (less mixing).

## 6. Adaptive Penalty Algorithm

```
FUNCTION adaptive_penalty_qaoa(n, dist, p, init_params):
    A ← 10 · max_edge_distance
    FOR iter = 1 TO 5:
        route, metrics ← run_qaoa(n, dist, p, init_params, A)
        violation_rate ← metrics.violations / max(20, total_sampled)
        IF violation_rate > 0.5:
            A ← A × 1.5          # too many violations
        ELIF violation_rate < 0.1:
            A ← A × 0.8          # penalty too strong, landscape flattening
        IF route is valid AND violation_rate < 0.2:
            BREAK
    RETURN best_route, metrics
```

The penalty history is tracked and reported by Glass Box for convergence analysis.

## 7. Glass Box Verification

### Confidence Score

```
confidence = P(best_bitstring) / P(second_best_bitstring)
```

A confidence of 2.0 means the quantum solver found the best route with twice the probability of the runner-up. Higher is better.

### Route Explanation

For each vehicle, the Glass Box reports:
- Winning route and its distance.
- Next-best alternative and its distance.
- Selection confidence.
- Number of penalty iterations.
- Penalty weight evolution.

### Complexity Budget

| Instance Size | Max Qubits | Max Gates | Max Time |
|---|---|---|---|
| n ≤ 4 | 16 | 200 | 30s |
| n ≤ 8 | 32 | 500 | 90s |
| n ≤ 12 | 64 | 1000 | 120s |

Exceeding these triggers adaptation (reduce p) or fallback (classical solver).

## 8. Scalability Table

| Instance | Customers | Vehicles | Customers/Vehicle | Nodes/Vehicle | Qubits/Vehicle | Total QAOA Runs |
|---|---|---|---|---|---|---|
| 1 | 3 | 2 | all (full) | 4 | 16 | 1 |
| 2 | 3 | 2 | all (full) | 4 | 16 | 1 |
| 3 | 6 | 3 | 2 | 3 | 9 | 3 |
| 4 | 12 | 4 | 3 | 4 | 16 | 4 |

## 9. Results

Results including distances, approximation ratios, and resource usage are generated at runtime and stored in `results/resource_table.md` and `results/glassbox_report_{1,2,3,4}.txt`.
