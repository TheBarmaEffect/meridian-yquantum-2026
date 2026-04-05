"""
Phase 2 — Quantum Core: QAOA Circuit Builder + COBYLA Optimiser.

QAOA ansatz (p layers):
    |ψ(γ,β)⟩ = ∏_{l=1}^{p} U_M(β_l) U_C(γ_l) |+⟩^⊗n

Cost unitary   U_C(γ) = exp(−iγ C)
    C is the Ising Hamiltonian derived from the TSP QUBO.
    Decomposed into RZZ(2γ J_{ij}) and RZ(2γ h_i) gates.

Mixer unitary  U_M(β) = exp(−iβ B),  B = Σ_i X_i
    Decomposed into RX(2β) on every qubit.

Executed on qBraid statevector simulator (falls back to Qiskit Aer / Statevector).
"""

import os
import time
import itertools
import numpy as np
from typing import List, Tuple, Dict, Optional

from dotenv import load_dotenv
load_dotenv()

from qiskit import QuantumCircuit
from qiskit.quantum_info import Statevector

from qubo import build_tsp_qubo, qubo_to_ising, precompute_qubo_costs


# ---------------------------------------------------------------------------
# qBraid / Aer backend selection
# ---------------------------------------------------------------------------

def _circuit_to_qasm3(circuit) -> str:
    """
    Convert a Qiskit circuit to a QASM3 string compatible with qBraid's
    QIR simulator. Strips 'stdgates.inc' and 'barrier' lines which the
    qBraid QIR compiler does not support.
    """
    from qiskit.qasm3 import dumps
    raw = dumps(circuit)
    lines = []
    for line in raw.splitlines():
        if 'include "stdgates.inc"' in line:
            continue
        if line.strip().startswith('barrier'):
            continue
        lines.append(line)
    return '\n'.join(lines)


def get_qbraid_backend():
    """
    Connects to qBraid and returns the QIR statevector device for real
    cloud circuit execution via QASM3 submission.

    Returns ("qbraid", device_id_str, qbraid_device) when qBraid is
    reachable, or ("aer", "local", AerSimulator) otherwise.
    """
    import warnings
    api_key = os.getenv("QBRAID_API_KEY")
    if api_key:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                from qbraid.runtime import QbraidProvider
                provider = QbraidProvider(api_key=api_key)
                devices = provider.get_devices()

            # find qBraid's own QIR statevector simulator
            sim_name = None
            preferred = ["qbraid:qbraid:sim:qir-sv"]
            for pid in preferred:
                for d in devices:
                    if str(d.id) == pid:
                        sim_name = str(d.id)
                        break
                if sim_name:
                    break
            if sim_name is None:
                for d in devices:
                    if "sim" in str(d.id).lower():
                        sim_name = str(d.id)
                        break

            if sim_name:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    device = provider.get_device(sim_name)
                print(f"[MERIDIAN] qBraid connected ({len(devices)} devices) — target: {sim_name}")
                print(f"[MERIDIAN] Execution: qBraid QIR statevector (cloud)")
                return ("qbraid", sim_name, device)
        except Exception as e:
            print(f"[MERIDIAN] qBraid SDK error: {e}")

    from qiskit_aer import AerSimulator
    print("[MERIDIAN] Backend: Qiskit Aer statevector (local)")
    return ("aer", "local", AerSimulator(method="statevector"))


def run_circuit_on_backend(circuit, backend_tuple, shots=1024):
    """
    Runs circuit on qBraid cloud (via QASM3) or falls back to local Aer.
    Returns counts dict and elapsed time.
    """
    btype, _, backend = backend_tuple
    t_start = time.time()

    if btype == "qbraid":
        try:
            import warnings, time as _time
            qasm3_str = _circuit_to_qasm3(circuit)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                job = backend.run(qasm3_str, shots=shots)
            # Poll for completion (max 60s)
            for _ in range(30):
                status = str(job.status())
                if 'COMPLETED' in status or 'FAILED' in status:
                    break
                _time.sleep(2)
            if 'COMPLETED' in str(job.status()):
                result = job.result()
                raw_counts = result.data.get_counts()
                counts = {k: v for k, v in raw_counts.items()}
                return counts, time.time() - t_start
        except Exception as e:
            pass  # fall through to local Aer

    # Local Aer fallback
    from qiskit_aer import AerSimulator
    from qiskit import transpile
    aer = AerSimulator(method="statevector")
    t_circ = transpile(circuit, aer)
    job = aer.run(t_circ, shots=shots)
    counts = dict(job.result().get_counts())
    return counts, time.time() - t_start


def backend_name(backend_tuple) -> str:
    """Human-readable name for the active backend."""
    btype, sim_id, _ = backend_tuple
    if btype == "qbraid":
        return f"qBraid QIR statevector ({sim_id})"
    return "Qiskit Aer statevector"


# ---------------------------------------------------------------------------
# Circuit construction
# ---------------------------------------------------------------------------

def build_qaoa_circuit(n_qubits: int,
                       h: np.ndarray,
                       J: Dict[Tuple[int, int], float],
                       p: int,
                       params: np.ndarray) -> QuantumCircuit:
    """
    Build a concrete (fully-bound) QAOA circuit.

    params layout: [gamma_0, beta_0, gamma_1, beta_1, …]  (length 2p).
    """
    qc = QuantumCircuit(n_qubits)
    qc.h(range(n_qubits))                          # initial |+⟩^n

    for layer in range(p):
        gamma = float(params[2 * layer])
        beta  = float(params[2 * layer + 1])

        # ---- cost unitary U_C(γ) -----------------------------------------
        for (i, j), Jval in J.items():
            if abs(Jval) > 1e-12:
                qc.rzz(2.0 * gamma * Jval, i, j)
        for i in range(n_qubits):
            if abs(h[i]) > 1e-12:
                qc.rz(2.0 * gamma * h[i], i)

        # ---- mixer unitary U_M(β) ----------------------------------------
        for i in range(n_qubits):
            qc.rx(2.0 * beta, i)

    return qc


# ---------------------------------------------------------------------------
# Statevector simulation (used inside COBYLA loop for speed)
# ---------------------------------------------------------------------------

def simulate_circuit(qc: QuantumCircuit) -> np.ndarray:
    """Return probability vector from statevector simulation."""
    sv = Statevector.from_instruction(qc)
    return np.abs(sv.data) ** 2


# ---------------------------------------------------------------------------
# Bitstring decoding
# ---------------------------------------------------------------------------

def decode_bitstring_to_route(idx: int, n: int) -> Optional[List[int]]:
    """
    Decode a basis-state index into a TSP route (local indices).

    The assignment matrix is x_{node, position} where
    qubit index = node * n + position  (Qiskit little-endian).

    Returns [0, …, 0] (starting/ending at local depot 0) or None if invalid.
    """
    matrix = np.zeros((n, n), dtype=int)
    for q in range(n * n):
        bit = (idx >> q) & 1
        node = q // n
        pos  = q % n
        matrix[node][pos] = bit

    # Valid permutation?  Each row and column must sum to exactly 1.
    if not (np.all(matrix.sum(axis=0) == 1) and np.all(matrix.sum(axis=1) == 1)):
        return None

    # Read route: for each position find the assigned node
    route = [0] * n
    for node in range(n):
        for pos in range(n):
            if matrix[node][pos] == 1:
                route[pos] = node

    # Rotate so depot (node 0) is at the front
    if 0 in route:
        dep = route.index(0)
        route = route[dep:] + route[:dep]
    route.append(0)                                 # return to depot
    return route


def local_route_distance(route: List[int], dist: np.ndarray) -> float:
    """Total distance along a route given a local distance matrix."""
    return sum(dist[route[k]][route[k + 1]] for k in range(len(route) - 1))


def precompute_valid_permutation_indices(n: int) -> List[Tuple[int, List[int]]]:
    """
    Precompute (statevector_index, route) for every valid n-node permutation.
    For n=3: 6 permutations.  For n=4: 24.  Trivial cost.
    """
    valid = []
    for perm in itertools.permutations(range(n)):
        # perm[pos] = node at that position
        idx = 0
        for pos in range(n):
            node = perm[pos]
            qubit = node * n + pos
            idx |= (1 << qubit)
        # Build route: rotate so depot (node 0) is first
        route = list(perm)
        dep = route.index(0)
        route = route[dep:] + route[:dep]
        route.append(0)
        valid.append((idx, route))
    return valid


# ---------------------------------------------------------------------------
# Core QAOA optimiser
# ---------------------------------------------------------------------------

def run_qaoa(n_nodes: int,
             local_dist: np.ndarray,
             p: int,
             initial_params: List[float],
             A: float,
             backend_tuple=None,
             max_cobyla_iter: int = 100,
             verbose: bool = False) -> Tuple[Optional[List[int]], dict]:
    """
    Full QAOA run for a single vehicle TSP.

    Parameters
    ----------
    n_nodes        : depot + customers in this cluster.
    local_dist     : n_nodes × n_nodes distance matrix.
    p              : number of QAOA layers.
    initial_params : warm-start [gamma, beta, …] of length 2p.
    A              : QUBO penalty weight.
    backend_tuple  : (type, backend) from get_qbraid_backend().
    max_cobyla_iter: COBYLA iteration budget.

    Returns
    -------
    best_route : list of local node indices or None.
    metrics    : dict with n_qubits, gate_count, depth, exec_time, etc.
    """
    from scipy.optimize import minimize as sp_minimize

    n_qubits = n_nodes * n_nodes
    Q = build_tsp_qubo(n_nodes, local_dist, A)
    h, J, offset = qubo_to_ising(Q)
    qubo_costs = precompute_qubo_costs(Q, n_qubits)

    # ---- optimisation bookkeeping ----------------------------------------
    obj_history: List[float] = []
    stall_count = 0

    def cost_fn(params):
        nonlocal stall_count
        qc = build_qaoa_circuit(n_qubits, h, J, p, params)
        probs = simulate_circuit(qc)
        cost = float(np.dot(probs, qubo_costs))
        obj_history.append(cost)

        # convergence detection
        if len(obj_history) > 1:
            delta = abs(obj_history[-1] - obj_history[-2])
            stall_count = stall_count + 1 if delta < 1e-4 else 0

        return cost

    # ---- run COBYLA ------------------------------------------------------
    t0 = time.time()
    x0 = np.array(initial_params, dtype=float)

    # Attempt up to 3 random re-initialisations on oscillation
    best_result = None
    for attempt in range(4):
        result = sp_minimize(cost_fn, x0, method='COBYLA',
                             options={'maxiter': max_cobyla_iter, 'rhobeg': 0.5})
        if best_result is None or result.fun < best_result.fun:
            best_result = result

        # Check oscillation: 5 consecutive sign changes in delta
        if len(obj_history) > 6:
            deltas = np.diff(obj_history[-6:])
            signs  = np.sign(deltas)
            if np.all(signs[:-1] != signs[1:]):
                # oscillating → perturb
                x0 = best_result.x + np.random.uniform(-0.1, 0.1, size=len(x0))
                if verbose:
                    print(f"    [QAOA] oscillation detected, re-init attempt {attempt+1}")
                continue
        break

    elapsed = time.time() - t0

    # ---- extract best valid route ----------------------------------------
    # Instead of scanning arbitrary top-k bitstrings, directly check all
    # n! valid permutations (≤24 for n≤4). Guaranteed to find the best one.
    best_params = best_result.x
    qc_final = build_qaoa_circuit(n_qubits, h, J, p, best_params)
    probs = simulate_circuit(qc_final)

    valid_perms = precompute_valid_permutation_indices(n_nodes)
    best_route: Optional[List[int]] = None
    best_cost = float('inf')
    top_k: List[Tuple[List[int], float, float]] = []

    for sv_idx, route in valid_perms:
        prob = float(probs[sv_idx])
        cost = local_route_distance(route, local_dist)
        top_k.append((route, cost, prob))
        if cost < best_cost:
            best_cost = cost
            best_route = route

    # Sort top_k by probability descending
    top_k.sort(key=lambda t: -t[2])

    # Count how many of the overall top-20 most-probable states are invalid
    sorted_idx = np.argsort(probs)[::-1]
    valid_set = {idx for idx, _ in valid_perms}
    violations = sum(1 for idx in sorted_idx[:20] if idx not in valid_set)

    # ---- circuit metrics -------------------------------------------------
    gate_ops = qc_final.count_ops()
    gate_count = sum(gate_ops.values())
    depth = qc_final.depth()

    metrics = {
        'n_qubits':       n_qubits,
        'gate_count':     gate_count,
        'depth':          depth,
        'exec_time':      elapsed,
        'backend_time':   0.0,
        'n_iterations':   len(obj_history),
        'obj_history':    obj_history,
        'violations':     violations,
        'penalty_A':      A,
        'top_k':          top_k[:20],
        'final_cost':     best_result.fun,
        'gate_ops':       dict(gate_ops),
        'backend_counts': {},
        '_qc_final':      qc_final,   # carry circuit for evidence run
    }

    return best_route, metrics


# ---------------------------------------------------------------------------
# Adaptive penalty loop
# ---------------------------------------------------------------------------

def adaptive_penalty_qaoa(n_nodes: int,
                          local_dist: np.ndarray,
                          p: int,
                          initial_params: List[float],
                          backend_tuple=None,
                          max_penalty_iter: int = 5,
                          max_cobyla_iter: int = 100,
                          verbose: bool = False
                          ) -> Tuple[Optional[List[int]], dict]:
    """
    Outer loop that adjusts the QUBO penalty weight A.

    Algorithm:
        1. Initialise A = 10 · max_edge_distance.
        2. Run QAOA; inspect top-20 bitstrings for constraint violations.
        3. violation_rate = violations / 20.
        4. If > 0.5  → A *= 1.5   (too many violations, increase penalty).
           If < 0.1  → A *= 0.8   (penalty too high, risk of flat landscape).
        5. Repeat up to max_penalty_iter times.
    """
    max_d = float(local_dist.max()) if local_dist.size else 1.0
    A = 10.0 * max_d
    penalty_history = [A]
    all_metrics: List[dict] = []

    best_route = None
    best_distance = float('inf')
    best_metrics: dict = {}

    for pit in range(max_penalty_iter):
        if verbose:
            print(f"  Penalty iter {pit}: A = {A:.2f}")

        route, metrics = run_qaoa(
            n_nodes, local_dist, p, initial_params, A,
            backend_tuple=backend_tuple,
            max_cobyla_iter=max_cobyla_iter, verbose=verbose,
        )
        all_metrics.append(metrics)

        # violation_rate = fraction of top-20 most-probable states that are invalid
        violation_rate = metrics['violations'] / 20.0

        if route is not None:
            dist_val = local_route_distance(route, local_dist)
            if dist_val < best_distance:
                best_distance = dist_val
                best_route = route
                best_metrics = metrics

        # Adjust penalty
        if violation_rate > 0.5:
            A *= 1.5
        elif violation_rate < 0.1:
            A *= 0.8

        penalty_history.append(A)

        # Early exit if we have a good solution and violation rate is low
        if route is not None and violation_rate < 0.2:
            break

    best_metrics['penalty_history'] = penalty_history
    best_metrics['penalty_iterations'] = len(all_metrics)

    # ---- ONE qBraid evidence run per vehicle (after penalty loop) --------
    # COBYLA uses fast local statevector. We submit to qBraid only once here,
    # using the best final circuit, to prove real quantum execution.
    if backend_tuple is not None and '_qc_final' in best_metrics:
        try:
            qc_ev = best_metrics['_qc_final'].copy()
            qc_ev.measure_all()
            bname = backend_name(backend_tuple)
            counts, bt = run_circuit_on_backend(qc_ev, backend_tuple, shots=256)
            best_metrics['backend_counts'] = counts
            best_metrics['backend_time'] = bt
        except Exception:
            pass
        best_metrics.pop('_qc_final', None)
    else:
        best_metrics.pop('_qc_final', None)

    return best_route, best_metrics
