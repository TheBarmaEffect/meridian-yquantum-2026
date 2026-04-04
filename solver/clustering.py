"""
Phase 1 — Classical Pre-Processing
Angular sweep capacitated clustering, nearest-neighbor warm-start,
and QAOA angle initialization.
"""

import math
import numpy as np
from typing import List, Tuple, Dict


# ---------------------------------------------------------------------------
# Distance helpers
# ---------------------------------------------------------------------------

def compute_distance_matrix(depot: Tuple[int, int],
                            customers: Dict[int, Tuple[int, int]]) -> np.ndarray:
    """Return a distance matrix indexed by node id (0 = depot)."""
    nodes: Dict[int, Tuple[int, int]] = {0: depot}
    nodes.update(customers)
    max_id = max(nodes.keys())
    dist = np.zeros((max_id + 1, max_id + 1))
    for i, (xi, yi) in nodes.items():
        for j, (xj, yj) in nodes.items():
            dist[i][j] = math.sqrt((xi - xj) ** 2 + (yi - yj) ** 2)
    return dist


def route_distance(route: List[int], dist: np.ndarray) -> float:
    """Total Euclidean distance of an ordered route (including return)."""
    return sum(dist[route[k]][route[k + 1]] for k in range(len(route) - 1))


# ---------------------------------------------------------------------------
# Angular-sweep capacitated clustering
# ---------------------------------------------------------------------------

def angular_sweep_cluster(depot: Tuple[int, int],
                          customers: Dict[int, Tuple[int, int]],
                          Nv: int, C: int) -> List[List[int]]:
    """
    Cluster customers into Nv groups of at most C using polar-angle sweep.

    1. Convert each customer to polar angle from depot.
    2. Sort by angle.
    3. Fill vehicles in order: first C customers → vehicle 0, next C → vehicle 1 …
    4. Overflow customers go to the vehicle with fewest assignments.
    5. Rebalance so every vehicle has ≥ 1 customer (when possible).
    """
    customer_ids = list(customers.keys())
    angles = {}
    for cid in customer_ids:
        cx, cy = customers[cid]
        dx, dy = cx - depot[0], cy - depot[1]
        angles[cid] = math.atan2(dy, dx)

    sorted_ids = sorted(customer_ids, key=lambda c: angles[c])

    clusters: List[List[int]] = [[] for _ in range(Nv)]
    for i, cid in enumerate(sorted_ids):
        vid = i // C
        if vid >= Nv:
            # Overflow → vehicle with fewest customers
            vid = min(range(Nv), key=lambda v: len(clusters[v]))
        clusters[vid].append(cid)

    # Rebalance: move from largest cluster to empty ones
    for v in range(Nv):
        if len(clusters[v]) == 0 and sum(len(c) for c in clusters) > Nv:
            # Find the largest cluster with > 1 customer
            donor = max(range(Nv), key=lambda x: len(clusters[x]))
            if len(clusters[donor]) > 1:
                clusters[v].append(clusters[donor].pop())

    return clusters


# ---------------------------------------------------------------------------
# Nearest-neighbour greedy route
# ---------------------------------------------------------------------------

def nearest_neighbor_route(depot_idx: int, cluster: List[int],
                           dist: np.ndarray) -> List[int]:
    """
    Greedy nearest-neighbour TSP starting and ending at depot_idx.
    Returns ordered route [depot, …, depot].
    """
    if not cluster:
        return [depot_idx, depot_idx]

    route = [depot_idx]
    remaining = set(cluster)
    current = depot_idx
    while remaining:
        nearest = min(remaining, key=lambda c: dist[current][c])
        route.append(nearest)
        remaining.remove(nearest)
        current = nearest
    route.append(depot_idx)
    return route


# ---------------------------------------------------------------------------
# Warm-start angle computation
# ---------------------------------------------------------------------------

def compute_warm_start_angles(greedy_distance: float,
                              local_dist: np.ndarray,
                              n_nodes: int,
                              p_layers: int) -> List[float]:
    """
    Map classical greedy quality to initial QAOA (gamma, beta) angles.

    quality ∈ [0, 1] — higher means the greedy solution is closer to optimal.
    Uses the Egger et al. 2021 interpolation:
        gamma = π/4 · quality
        beta  = π/4 · (1 − quality)

    Returns flat list [gamma_0, beta_0, gamma_1, beta_1, …].
    """
    # Lower bound: sum of n_nodes shortest outgoing edges / 2
    flat = local_dist[local_dist > 0]
    if len(flat) == 0:
        quality = 0.5
    else:
        sorted_edges = np.sort(flat)
        lb = sum(sorted_edges[:n_nodes]) / 2.0
        quality = float(np.clip(lb / greedy_distance, 0.0, 1.0)) if greedy_distance > 0 else 0.5

    angles: List[float] = []
    for _ in range(p_layers):
        angles.append(math.pi / 4.0 * quality)          # gamma
        angles.append(math.pi / 4.0 * (1.0 - quality))  # beta
    return angles
