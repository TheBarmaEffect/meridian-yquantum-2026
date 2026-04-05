#!/usr/bin/env python3
"""
Meridian — Solution Validator
Checks all 4 instance output files for correctness.
Run from the project root: python3 validate.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'solver'))
from instances import INSTANCES

RESULTS_DIR = os.path.join(os.path.dirname(__file__), 'results')


def parse_routes(filepath):
    routes = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or not line.startswith('r'):
                continue
            # e.g. "r1: 0, 1, 3, 0"
            nodes = list(map(int, line.split(':', 1)[1].split(',')))
            routes.append(nodes)
    return routes


def validate_instance(inst_id):
    inst = INSTANCES[inst_id]
    fpath = os.path.join(RESULTS_DIR, f'Instance{inst_id}.txt')

    if not os.path.exists(fpath):
        return False, f'File not found: {fpath}'

    try:
        routes = parse_routes(fpath)
    except Exception as e:
        return False, f'Parse error: {e}'

    # Check number of routes
    if len(routes) != inst.num_vehicles:
        return False, (f'Expected {inst.num_vehicles} routes, '
                       f'got {len(routes)}')

    all_customers = set(inst.customers.keys())
    visited = []

    for i, route in enumerate(routes):
        # Must start and end at depot (0)
        if route[0] != 0 or route[-1] != 0:
            return False, f'Route r{i+1} does not start/end at depot 0: {route}'

        # Capacity check (customers only, not depot)
        customers_in_route = [n for n in route if n != 0]
        if len(customers_in_route) > inst.capacity:
            return False, (f'Route r{i+1} exceeds capacity '
                           f'({len(customers_in_route)} > {inst.capacity}): {route}')

        # All nodes must be valid customers or depot
        for n in customers_in_route:
            if n not in all_customers:
                return False, f'Route r{i+1} contains unknown node {n}'

        visited.extend(customers_in_route)

    # Every customer visited exactly once
    if set(visited) != all_customers:
        missing = all_customers - set(visited)
        extra   = set(visited) - all_customers
        msg = []
        if missing:
            msg.append(f'missing customers: {missing}')
        if extra:
            msg.append(f'unknown nodes: {extra}')
        return False, '; '.join(msg)

    if len(visited) != len(all_customers):
        dupes = [n for n in visited if visited.count(n) > 1]
        return False, f'Customers visited more than once: {set(dupes)}'

    return True, 'OK'


def main():
    print('\n========================================')
    print('  Meridian — Solution Validator')
    print('========================================\n')

    all_pass = True
    for inst_id in [1, 2, 3, 4]:
        ok, msg = validate_instance(inst_id)
        status = '✅ PASS' if ok else '❌ FAIL'
        print(f'  Instance {inst_id}: {status}  —  {msg}')
        if not ok:
            all_pass = False

    print()
    if all_pass:
        print('  All instances valid ✅')
    else:
        print('  Some instances FAILED ❌')
    print()

    sys.exit(0 if all_pass else 1)


if __name__ == '__main__':
    main()
