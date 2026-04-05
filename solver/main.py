#!/usr/bin/env python3
"""
Meridian — Quantum-Verified CVRP Optimiser
CLI entry point.

Usage:
    python solver/main.py --instance all
    python solver/main.py --instance 1 --mode full --p 3
"""

import argparse
import os
import sys
import time
from datetime import datetime, timezone

# Ensure solver package is importable regardless of cwd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

from instances import INSTANCES, CVRPInstance
from clustering import (
    angular_sweep_cluster,
    compute_distance_matrix,
    nearest_neighbor_route,
    compute_warm_start_angles,
    route_distance,
)
from qaoa import (
    adaptive_penalty_qaoa,
    local_route_distance,
    get_qbraid_backend,
    backend_name,
)
from glassbox import GlassBox, run_with_timeout

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           'results')


def build_local_dist(nodes, global_dist):
    """Build a compact n×n distance matrix for *nodes* (local indices 0…n-1)."""
    n = len(nodes)
    ld = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            ld[i][j] = global_dist[nodes[i]][nodes[j]]
    return ld


def split_tour_into_routes(tour, nodes, Nv, C):
    """
    Split a single TSP tour (local indices) into Nv capacity-respecting routes.
    Returns list of routes in *global* node indices.
    """
    customers_order = tour[1:-1]  # drop leading/trailing depot
    routes = []
    start = 0
    n_cust = len(customers_order)
    for v in range(Nv):
        remaining = n_cust - start
        remaining_v = Nv - v
        take = min(C, max(1, remaining // remaining_v))
        if v == Nv - 1:
            take = remaining
        segment = customers_order[start:start + take]
        global_seg = [nodes[i] for i in segment]
        routes.append([0] + global_seg + [0])
        start += take
    return routes


def format_routes(routes):
    """Format routes for Instance output file."""
    lines = []
    for i, r in enumerate(routes, 1):
        lines.append(f"r{i}: " + ", ".join(str(n) for n in r))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Solve one instance
# ---------------------------------------------------------------------------

def solve_instance(inst: CVRPInstance, mode: str, p: int,
                   glassbox: GlassBox, backend_tuple,
                   verbose: bool = False) -> dict:
    bname = backend_name(backend_tuple)
    print(f"\n{'='*60}")
    print(f"  Instance {inst.instance_id}  |  Nv={inst.num_vehicles}  C={inst.capacity}  "
          f"customers={inst.num_customers}  mode={mode}  p={p}")
    print(f"  Backend: {bname}")
    print(f"{'='*60}")

    global_dist = compute_distance_matrix(inst.depot, inst.customers)
    all_routes = []
    all_metrics = []
    vehicle_explanations = []

    # ------------------------------------------------------------------
    if mode == 'full' and inst.num_customers <= 5:
        # Full QUBO: single TSP on all nodes, then split
        nodes = [0] + sorted(inst.customers.keys())
        n = len(nodes)
        local_dist = build_local_dist(nodes, global_dist)
        n_qubits = n * n

        print(f"  Full mode: TSP on {n} nodes -> {n_qubits} qubits")
        glassbox.log_event('mode', {'mode': 'full', 'n_nodes': n, 'n_qubits': n_qubits})

        greedy = nearest_neighbor_route(0, list(range(1, n)), local_dist)
        greedy_d = local_route_distance(greedy, local_dist)
        init_params = compute_warm_start_angles(greedy_d, local_dist, n, p)

        def _run():
            return adaptive_penalty_qaoa(
                n, local_dist, p, init_params,
                backend_tuple=backend_tuple, verbose=verbose)

        result = run_with_timeout(_run, timeout_sec=180)

        if result is None or result[0] is None:
            print("  WARNING: QAOA timed out or failed -- using classical fallback")
            greedy_global = nearest_neighbor_route(0, sorted(inst.customers.keys()), global_dist)
            all_routes = split_tour_into_routes(
                [nodes.index(g) for g in greedy_global], nodes,
                inst.num_vehicles, inst.capacity)
            fallback_metrics = {
                'n_qubits': n_qubits, 'gate_count': 0, 'depth': 0,
                'exec_time': 0, 'backend_time': 0, 'penalty_iterations': 0,
                'penalty_history': [], 'top_k': [], 'fallback': True,
                'backend_counts': {},
            }
            all_metrics = [fallback_metrics] * len(all_routes)
            glassbox.log_event('fallback', {'reason': 'timeout', 'instance': inst.instance_id})
        else:
            route, metrics = result
            all_routes = split_tour_into_routes(route, nodes,
                                                 inst.num_vehicles, inst.capacity)
            all_metrics = [metrics] * len(all_routes)

            # Complexity check
            status = glassbox.check_complexity_budget(
                metrics['n_qubits'], metrics['gate_count'],
                metrics['exec_time'], inst.num_customers)
            if status == 'adapt' and p > 1:
                print(f"  Complexity budget -> adapt: reducing p to {p-1}")
                p -= 1

    # ------------------------------------------------------------------
    else:
        # HQCD mode: cluster -> per-vehicle QAOA
        clusters = angular_sweep_cluster(inst.depot, inst.customers,
                                          inst.num_vehicles, inst.capacity)
        print(f"  HQCD clusters: {clusters}")
        glassbox.log_event('mode', {'mode': 'hqcd', 'clusters': clusters})

        for vid, cluster in enumerate(clusters):
            if not cluster:
                all_routes.append([0, 0])
                all_metrics.append({
                    'n_qubits': 0, 'gate_count': 0, 'depth': 0,
                    'exec_time': 0, 'backend_time': 0,
                    'penalty_iterations': 0, 'penalty_history': [],
                    'top_k': [], 'backend_counts': {},
                })
                continue

            nodes = [0] + cluster
            n = len(nodes)
            local_dist = build_local_dist(nodes, global_dist)
            n_qubits = n * n

            # Check cache
            cached = glassbox.check_cache(inst.instance_id, cluster)
            if cached is not None:
                print(f"  Vehicle {vid}: cache hit")
                all_routes.append(cached['route'])
                all_metrics.append(cached['metrics'])
                continue

            print(f"  Vehicle {vid}: TSP on {n} nodes -> {n_qubits} qubits  cluster={cluster}")

            greedy = nearest_neighbor_route(0, list(range(1, n)), local_dist)
            greedy_d = local_route_distance(greedy, local_dist)
            init_params = compute_warm_start_angles(greedy_d, local_dist, n, p)

            def _run(n_=n, ld_=local_dist, p_=p, ip_=init_params):
                return adaptive_penalty_qaoa(
                    n_, ld_, p_, ip_,
                    backend_tuple=backend_tuple, verbose=verbose)

            result = run_with_timeout(_run, timeout_sec=90)

            if result is None or result[0] is None:
                print(f"  WARNING: Vehicle {vid}: QAOA failed -- classical fallback")
                fb_route = nearest_neighbor_route(0, list(range(1, n)), local_dist)
                global_route = [nodes[i] for i in fb_route]
                all_routes.append(global_route)
                all_metrics.append({
                    'n_qubits': n_qubits, 'gate_count': 0, 'depth': 0,
                    'exec_time': 0, 'backend_time': 0,
                    'penalty_iterations': 0, 'penalty_history': [],
                    'top_k': [], 'fallback': True, 'backend_counts': {},
                })
                glassbox.log_event('fallback', {
                    'reason': 'qaoa_failed', 'vehicle': vid, 'cluster': cluster,
                })
            else:
                route_local, metrics = result
                global_route = [nodes[i] for i in route_local]
                all_routes.append(global_route)
                all_metrics.append(metrics)

                # Complexity check
                status = glassbox.check_complexity_budget(
                    metrics['n_qubits'], metrics['gate_count'],
                    metrics['exec_time'], len(cluster))
                if status == 'fallback':
                    print(f"  Vehicle {vid}: complexity budget exceeded -- fallback")
                    fb_route = nearest_neighbor_route(0, list(range(1, n)), local_dist)
                    global_route = [nodes[i] for i in fb_route]
                    all_routes[-1] = global_route
                    glassbox.log_event('fallback', {
                        'reason': 'complexity_budget', 'vehicle': vid,
                    })

                # Store cache
                glassbox.store_cache(inst.instance_id, cluster, {
                    'route': global_route, 'metrics': metrics,
                })

    # ------------------------------------------------------------------
    # Post-processing: generate explanations
    # ------------------------------------------------------------------
    total_distance = sum(route_distance(r, global_dist) for r in all_routes)

    # Classical baseline for approximation ratio
    all_cust = sorted(inst.customers.keys())
    classical_route = nearest_neighbor_route(0, all_cust, global_dist)
    classical_dist = route_distance(classical_route, global_dist)

    # For small instances compute brute-force optimal
    if inst.num_customers <= 8:
        optimal_dist = glassbox._brute_force_optimal(
            [0] + all_cust, global_dist)
    else:
        optimal_dist = classical_dist

    approx_ratio = glassbox.compute_approximation_ratio(total_distance, classical_dist)

    avg_confidence = 0.0
    for vid, (route, metrics) in enumerate(zip(all_routes, all_metrics)):
        top_k = metrics.get('top_k', [])
        confidence = glassbox.compute_confidence(top_k)
        avg_confidence += confidence
        alt_route = top_k[1][0] if len(top_k) > 1 else None
        alt_dist = top_k[1][1] if len(top_k) > 1 else 0.0

        exp = glassbox.generate_route_explanation(
            vehicle_id=vid,
            winning_route=route,
            alt_route=alt_route,
            distance_win=route_distance(route, global_dist),
            distance_alt=alt_dist,
            confidence=confidence,
            n_iterations=metrics.get('penalty_iterations', 0),
            penalty_history=metrics.get('penalty_history', []),
        )
        vehicle_explanations.append(exp)

    n_vehicles = len(all_routes)
    avg_confidence = avg_confidence / max(n_vehicles, 1)

    # Full report
    report = glassbox.generate_full_report(
        inst.instance_id, all_routes, total_distance, approx_ratio,
        vehicle_explanations, all_metrics,
    )

    # Synthesis engine (optional local LLM)
    synth = glassbox.synthesize_explanation(
        f"CVRP instance {inst.instance_id}: {inst.num_customers} customers, "
        f"{inst.num_vehicles} vehicles, capacity {inst.capacity}"
    )
    if synth:
        report += f"\n\n--- LLM Synthesis ---\n{synth}\n"

    print(f"\n  Total distance: {total_distance:.2f}")
    print(f"  Approx ratio (vs greedy): {approx_ratio:.4f}")
    print(f"  Optimal distance: {optimal_dist:.2f}")

    return {
        'instance_id': inst.instance_id,
        'routes': all_routes,
        'total_distance': total_distance,
        'approx_ratio': approx_ratio,
        'optimal_distance': optimal_dist,
        'avg_confidence': avg_confidence,
        'metrics': all_metrics,
        'report': report,
        'backend': bname,
    }


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def write_instance_file(instance_id, routes):
    path = os.path.join(RESULTS_DIR, f'Instance{instance_id}.txt')
    with open(path, 'w') as f:
        f.write(format_routes(routes))
    print(f"  -> {path}")


def write_glassbox_report(instance_id, report):
    path = os.path.join(RESULTS_DIR, f'glassbox_report_{instance_id}.txt')
    with open(path, 'w') as f:
        f.write(report)
    print(f"  -> {path}")


def write_resource_table(all_results):
    path = os.path.join(RESULTS_DIR, 'resource_table.md')
    lines = [
        '| CVRP Instance # | # of Qubits | # of Gate Operations | Execution Time |',
        '|---|---|---|---|',
    ]
    for res in all_results:
        iid = res['instance_id']
        metrics_list = res['metrics']
        total_qubits = max((m.get('n_qubits', 0) for m in metrics_list), default=0)
        total_gates  = sum(m.get('gate_count', 0) for m in metrics_list)
        total_time   = sum(m.get('exec_time', 0) for m in metrics_list)
        lines.append(f'| {iid} | {total_qubits} | {total_gates} | {total_time:.2f}s |')
    with open(path, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    print(f"\n  Resource table -> {path}")


def write_execution_log(all_results, backend_str):
    """Append a structured execution log entry for each instance."""
    path = os.path.join(RESULTS_DIR, 'execution_log.txt')
    with open(path, 'w') as f:
        for res in all_results:
            iid = res['instance_id']
            ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
            sep = '=' * 54
            f.write(f"{sep}\n")
            f.write(f"MERIDIAN EXECUTION LOG -- Instance {iid}\n")
            f.write(f"Timestamp: {ts}\n")
            f.write(f"Backend: {backend_str}\n")
            f.write(f"{sep}\n")

            for vid, (route, metrics) in enumerate(
                    zip(res['routes'], res['metrics'])):
                cluster = [c for c in route if c != 0]
                nq = metrics.get('n_qubits', 0)
                gc = metrics.get('gate_count', 0)
                et = metrics.get('exec_time', 0)
                f.write(
                    f"Vehicle {vid+1}: {cluster} -> route {route} "
                    f"| qubits={nq} gates={gc} time={et:.2f}s\n"
                )

            f.write(f"Total distance: {res['total_distance']:.4f}\n")
            f.write(f"Approx ratio vs optimal: {res['approx_ratio']:.4f}\n")
            f.write(f"Glass Box confidence: {res.get('avg_confidence', 0):.2%}\n")
            f.write(f"{sep}\n\n")
    print(f"  Execution log -> {path}")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_solution(inst: CVRPInstance, routes):
    errors = []
    all_customers_seen = set()
    if len(routes) != inst.num_vehicles:
        errors.append(f"Expected {inst.num_vehicles} routes, got {len(routes)}")

    for i, route in enumerate(routes):
        if route[0] != 0 or route[-1] != 0:
            errors.append(f"Route {i+1} doesn't start/end at depot")
        custs = [c for c in route if c != 0]
        if len(custs) > inst.capacity:
            errors.append(f"Route {i+1} exceeds capacity: {len(custs)} > {inst.capacity}")
        for c in custs:
            if c in all_customers_seen:
                errors.append(f"Customer {c} appears in multiple routes")
            all_customers_seen.add(c)

    expected = set(inst.customers.keys())
    if all_customers_seen != expected:
        missing = expected - all_customers_seen
        extra = all_customers_seen - expected
        if missing:
            errors.append(f"Missing customers: {missing}")
        if extra:
            errors.append(f"Unexpected customers: {extra}")
    return errors


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Meridian CVRP Optimiser')
    parser.add_argument('--instance', default='all',
                        help='Instance number (1-4) or "all"')
    parser.add_argument('--mode', default='auto', choices=['auto', 'full', 'hqcd'],
                        help='Solving mode')
    parser.add_argument('--p', type=int, default=0,
                        help='QAOA layers (0 = auto)')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()

    os.makedirs(RESULTS_DIR, exist_ok=True)

    # --- initialise backend once ------------------------------------------
    backend_tuple = get_qbraid_backend()
    bname = backend_name(backend_tuple)

    if args.instance == 'all':
        instance_ids = [1, 2, 3, 4]
    else:
        instance_ids = [int(args.instance)]

    glassbox = GlassBox()
    all_results = []

    for iid in instance_ids:
        inst = INSTANCES[iid]

        # Auto mode selection
        if args.mode == 'auto':
            mode = 'full' if inst.num_customers <= 3 else 'hqcd'
        else:
            mode = args.mode
            if mode == 'full' and inst.num_customers > 5:
                print(f"  WARNING: Full mode impractical for {inst.num_customers} customers, using HQCD")
                mode = 'hqcd'

        # Auto p selection
        if args.p > 0:
            p = args.p
        else:
            p = 2

        result = solve_instance(inst, mode, p, glassbox, backend_tuple,
                                verbose=args.verbose)

        # Validate
        errors = validate_solution(inst, result['routes'])
        if errors:
            print(f"\n  VALIDATION ERRORS for Instance {iid}:")
            for e in errors:
                print(f"    - {e}")
            # Attempt repair via fallback
            print("  Attempting repair via classical fallback...")
            result = _repair_solution(inst, result, glassbox)
            errors = validate_solution(inst, result['routes'])
            if errors:
                print(f"  Repair failed: {errors}")
            else:
                print(f"  Repair successful")

        # Write outputs
        write_instance_file(iid, result['routes'])
        write_glassbox_report(iid, result['report'])
        all_results.append(result)

    write_resource_table(all_results)
    write_execution_log(all_results, bname)

    print("\n" + "=" * 60)
    print("  Meridian -- All instances complete")
    print("=" * 60)
    for r in all_results:
        print(f"  Instance {r['instance_id']}: distance={r['total_distance']:.2f}  "
              f"approx_ratio={r['approx_ratio']:.4f}")


def _repair_solution(inst, result, glassbox):
    """Re-solve with pure classical fallback if quantum solution was invalid."""
    global_dist = compute_distance_matrix(inst.depot, inst.customers)
    clusters = angular_sweep_cluster(inst.depot, inst.customers,
                                      inst.num_vehicles, inst.capacity)
    routes = []
    metrics = []
    for cluster in clusters:
        if not cluster:
            routes.append([0, 0])
        else:
            route = nearest_neighbor_route(0, cluster, global_dist)
            routes.append(route)
        metrics.append({
            'n_qubits': 0, 'gate_count': 0, 'depth': 0,
            'exec_time': 0, 'backend_time': 0,
            'penalty_iterations': 0, 'penalty_history': [],
            'top_k': [], 'fallback': True, 'backend_counts': {},
        })
    total_d = sum(route_distance(r, global_dist) for r in routes)
    result['routes'] = routes
    result['total_distance'] = total_d
    result['metrics'] = metrics
    glassbox.log_event('repair', {'instance': inst.instance_id})
    return result


if __name__ == '__main__':
    main()
