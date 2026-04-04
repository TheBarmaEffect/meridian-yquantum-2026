"""
QUBO Formulation for the Travelling Salesman Problem (TSP).

Variables
---------
x_{i,p} ∈ {0, 1}  —  1 iff node i is at position p in the tour.
  i ∈ {0, …, n−1}  (0 = depot)
  p ∈ {0, …, n−1}
Total qubits per vehicle: n².

Objective — minimise total tour distance:
    H_obj = Σ_{i≠j} Σ_p  d(i,j) · x_{i,p} · x_{j, (p+1) mod n}

Constraint 1 — each position filled by exactly one node:
    H_c1 = A · Σ_p (1 − Σ_i x_{i,p})²

Constraint 2 — each node appears at exactly one position:
    H_c2 = A · Σ_i (1 − Σ_p x_{i,p})²

Full QUBO:  H = H_obj + H_c1 + H_c2
Penalty weight A initialised as  10 · max_edge_distance.
"""

import numpy as np
from typing import Dict, Tuple


def _qubit_index(node: int, position: int, n: int) -> int:
    """Map (node, position) pair to a flat qubit index."""
    return node * n + position


def build_tsp_qubo(n: int, dist: np.ndarray, A: float) -> np.ndarray:
    """
    Construct the upper-triangular QUBO matrix Q  (N×N where N = n²).

    Parameters
    ----------
    n    : number of TSP nodes (depot + customers in this vehicle cluster).
    dist : n×n distance matrix (local indices 0 … n−1).
    A    : penalty weight for constraint terms.

    Returns
    -------
    Q : np.ndarray of shape (N, N), upper-triangular.
    """
    N = n * n
    Q = np.zeros((N, N))

    # --- Constraint 1: each position has exactly one node ----------------
    # H_c1 = A Σ_p (Σ_i x_{i,p} − 1)²
    #       = A Σ_p [ −Σ_i x_{i,p} + 2 Σ_{i<j} x_{i,p} x_{j,p} + 1 ]
    for p in range(n):
        for i in range(n):
            qi = _qubit_index(i, p, n)
            Q[qi, qi] -= A                       # linear −A
            for j in range(i + 1, n):
                qj = _qubit_index(j, p, n)
                Q[qi, qj] += 2.0 * A             # quadratic +2A

    # --- Constraint 2: each node at exactly one position -----------------
    # H_c2 = A Σ_i (Σ_p x_{i,p} − 1)²
    for i in range(n):
        for p in range(n):
            qi = _qubit_index(i, p, n)
            Q[qi, qi] -= A
            for r in range(p + 1, n):
                qr = _qubit_index(i, r, n)
                Q[qi, qr] += 2.0 * A

    # --- Objective: minimise tour distance -------------------------------
    # H_obj = Σ_{i≠j} Σ_p d(i,j) x_{i,p} x_{j,(p+1)%n}
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            d = dist[i][j]
            if d == 0:
                continue
            for p in range(n):
                p_next = (p + 1) % n
                qi = _qubit_index(i, p, n)
                qj = _qubit_index(j, p_next, n)
                if qi <= qj:
                    Q[qi, qj] += d
                else:
                    Q[qj, qi] += d

    return Q


def qubo_to_ising(Q: np.ndarray) -> Tuple[np.ndarray, Dict[Tuple[int, int], float], float]:
    """
    Convert upper-triangular QUBO matrix to Ising (h, J, offset).

    Substitution:  x_i = (1 − z_i) / 2   with z_i ∈ {−1, +1}.

    Returns
    -------
    h      : np.ndarray — linear coefficients (one per qubit).
    J      : dict {(i, j): value} — coupling coefficients (i < j).
    offset : float — constant energy offset.
    """
    N = Q.shape[0]
    h = np.zeros(N)
    J: Dict[Tuple[int, int], float] = {}
    offset = 0.0

    for i in range(N):
        # diagonal: Q_ii x_i = Q_ii (1−z_i)/2
        offset += Q[i, i] / 2.0
        h[i] -= Q[i, i] / 2.0

    for i in range(N):
        for j in range(i + 1, N):
            qij = Q[i, j]
            if abs(qij) < 1e-12:
                continue
            # Q_ij x_i x_j = Q_ij (1−z_i)(1−z_j)/4
            offset += qij / 4.0
            h[i] -= qij / 4.0
            h[j] -= qij / 4.0
            J[(i, j)] = qij / 4.0

    return h, J, offset


def precompute_qubo_costs(Q: np.ndarray, n_qubits: int) -> np.ndarray:
    """
    Evaluate QUBO cost f(x) = xᵀQx for every computational-basis state.

    Uses Qiskit little-endian convention: qubit q → bit position q.
    Returns array of length 2^n_qubits.  Fully vectorised with numpy.
    """
    n_states = 1 << n_qubits
    indices = np.arange(n_states, dtype=np.int64)
    # bits[state, qubit] — little-endian bit extraction
    bits = ((indices[:, None] >> np.arange(n_qubits, dtype=np.int64)[None, :]) & 1).astype(np.float64)
    # costs[i] = bits[i] @ Q @ bits[i]  —  vectorised via einsum
    Qx = bits @ Q                        # (n_states, n_qubits)
    costs = np.einsum('ij,ij->i', Qx, bits)
    return costs


def evaluate_qubo_bitstring(Q: np.ndarray, idx: int, n_qubits: int) -> float:
    """Evaluate QUBO cost for a single basis-state index."""
    x = np.array([(idx >> q) & 1 for q in range(n_qubits)], dtype=float)
    return float(x @ Q @ x)
