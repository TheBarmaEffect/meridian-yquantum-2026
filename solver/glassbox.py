"""
Phase 3 — Glass Box Verification Layer.

Provides:
  - Solution caching
  - Confidence scoring
  - Complexity-budget monitoring
  - Route explainability
  - Approximation-ratio reporting
  - Timeout handling & fallback cascade
  - Optional LLM synthesis via local Ollama / codellama
"""

import hashlib
import itertools
import json
import signal
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from clustering import nearest_neighbor_route, route_distance


# ---------------------------------------------------------------------------
# Timeout decorator (Unix only; safe no-op elsewhere)
# ---------------------------------------------------------------------------

class QAOATimeoutError(Exception):
    pass


def run_with_timeout(func, timeout_sec: int = 30):
    """Execute *func()* with a wall-clock timeout. Returns None on timeout."""
    def _handler(signum, frame):
        raise QAOATimeoutError("QAOA exceeded time budget")

    old = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(timeout_sec)
    try:
        return func()
    except QAOATimeoutError:
        return None
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


# ---------------------------------------------------------------------------
# Glass Box
# ---------------------------------------------------------------------------

class GlassBox:

    def __init__(self):
        self.event_log: List[Dict[str, Any]] = []
        self.cache: Dict[str, Any] = {}
        self.algo_scores: Dict[str, float] = {}
        self.run_metrics: List[dict] = []

    # ---- logging ----------------------------------------------------------

    def log_event(self, event_type: str, data: Any) -> None:
        self.event_log.append({
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'event_type': event_type,
            'data': data,
        })

    # ---- caching ----------------------------------------------------------

    @staticmethod
    def _problem_hash(instance_id: int, cluster: List[int]) -> str:
        raw = f"{instance_id}:{sorted(cluster)}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def check_cache(self, instance_id: int, cluster: List[int]):
        h = self._problem_hash(instance_id, cluster)
        return self.cache.get(h)

    def store_cache(self, instance_id: int, cluster: List[int], solution):
        h = self._problem_hash(instance_id, cluster)
        self.cache[h] = solution
        self.log_event('cache_store', {'hash': h})

    # ---- confidence scoring -----------------------------------------------

    def compute_confidence(self, top_k: List[Tuple]) -> float:
        """
        confidence = P(best) / P(second_best).
        If only one unique route: confidence = 1.0.
        """
        if not top_k:
            return 0.0
        if len(top_k) == 1:
            return 1.0

        probs = [t[2] for t in top_k]
        best = probs[0]
        second = probs[1] if len(probs) > 1 and probs[1] > 1e-15 else 1e-15
        return min(best / second, 100.0)

    # ---- complexity budget ------------------------------------------------

    def check_complexity_budget(self, n_qubits: int, n_gates: int,
                                elapsed: float, n_customers: int) -> str:
        """
        Returns 'ok', 'warn', 'adapt', or 'fallback' depending on resource usage.
        """
        if n_customers <= 4:
            max_q, max_g, max_t = 16, 500, 60
        elif n_customers <= 8:
            max_q, max_g, max_t = 32, 500, 90
        else:
            max_q, max_g, max_t = 64, 1000, 120

        over_q = n_qubits > max_q
        over_g = n_gates > max_g
        over_t = elapsed > max_t

        if over_q or (over_g and over_t):
            status = 'fallback'
        elif over_g or over_t:
            status = 'adapt'
        elif n_qubits > max_q * 0.8 or n_gates > max_g * 0.8:
            status = 'warn'
        else:
            status = 'ok'

        self.log_event('complexity_check', {
            'n_qubits': n_qubits, 'n_gates': n_gates,
            'elapsed': elapsed, 'status': status,
        })
        return status

    # ---- route explanation ------------------------------------------------

    def generate_route_explanation(self, vehicle_id: int,
                                   winning_route: List[int],
                                   alt_route: Optional[List[int]],
                                   distance_win: float,
                                   distance_alt: float,
                                   confidence: float,
                                   n_iterations: int,
                                   penalty_history: List[float]) -> str:
        ph = ' → '.join(f'{a:.1f}' for a in penalty_history)
        lines = [
            f"Vehicle {vehicle_id}: route {winning_route} (distance {distance_win:.2f})",
        ]
        if alt_route is not None:
            lines.append(f"  Next best: {alt_route} (distance {distance_alt:.2f})")
        lines.append(f"  Selected with {confidence:.0%} confidence after {n_iterations} penalty iteration(s)")
        lines.append(f"  Penalty evolution: {ph}")
        return '\n'.join(lines)

    # ---- approximation ratio ----------------------------------------------

    def compute_approximation_ratio(self, quantum_distance: float,
                                     classical_baseline: float) -> float:
        """ratio = classical_baseline / quantum_distance  (higher ⇒ quantum did better)."""
        if quantum_distance <= 0:
            return 0.0
        return classical_baseline / quantum_distance

    def _brute_force_optimal(self, nodes: List[int],
                              dist: np.ndarray) -> float:
        """Exact optimal for small TSP (≤ 8 nodes) via permutation enumeration."""
        depot = nodes[0]
        customers = nodes[1:]
        best = float('inf')
        for perm in itertools.permutations(customers):
            route = [depot] + list(perm) + [depot]
            d = route_distance(route, dist)
            if d < best:
                best = d
        return best

    # ---- full report ------------------------------------------------------

    def generate_full_report(self, instance_id: int,
                              all_routes: List[List[int]],
                              total_distance: float,
                              approx_ratio: float,
                              vehicle_explanations: List[str],
                              resource_metrics: List[dict]) -> str:
        sep = '=' * 60
        lines = [
            sep,
            f"  GLASS BOX REPORT — Instance {instance_id}",
            sep, '',
            f"Total distance : {total_distance:.2f}",
            f"Approx. ratio  : {approx_ratio:.4f}",
            f"Routes         : {len(all_routes)}", '',
        ]
        for r in all_routes:
            lines.append(f"  {r}")
        lines.append('')

        lines.append('--- Vehicle Explanations ---')
        for exp in vehicle_explanations:
            lines.append(exp)
            lines.append('')

        lines.append('--- Resource Usage ---')
        for m in resource_metrics:
            lines.append(
                f"  qubits={m.get('n_qubits','?')}  "
                f"gates={m.get('gate_count','?')}  "
                f"depth={m.get('depth','?')}  "
                f"time={m.get('exec_time',0):.2f}s  "
                f"penalty_iters={m.get('penalty_iterations','?')}"
            )

        lines.append('')
        lines.append('--- Event Log (last 20) ---')
        for ev in self.event_log[-20:]:
            lines.append(f"  [{ev['timestamp']}] {ev['event_type']}: {ev['data']}")

        lines.append(sep)
        return '\n'.join(lines)

    # ---- fallback cascade -------------------------------------------------

    def get_fallback_route(self, depot_idx: int, cluster: List[int],
                           dist: np.ndarray, reason: str) -> List[int]:
        """
        Classical nearest-neighbour fallback.
        Logs the reason (timeout | low_confidence | complexity_budget | qaoa_failed).
        """
        route = nearest_neighbor_route(depot_idx, cluster, dist)
        self.log_event('fallback', {'reason': reason, 'cluster': cluster, 'route': route})
        return route

    # ---- optional LLM synthesis (Ollama / codellama) ----------------------

    def synthesize_explanation(self, problem_schema: str) -> Optional[str]:
        """
        Use local Ollama codellama to generate a human-readable explanation
        of the QUBO formulation.  Falls through silently if Ollama is not running.
        """
        try:
            import ollama
            response = ollama.chat(model='codellama', messages=[{
                'role': 'user',
                'content': (
                    'Write a concise QUBO formulation and QAOA circuit '
                    f'explanation for the following problem:\n{problem_schema}'
                ),
            }])
            return response['message']['content']
        except Exception:
            return None
