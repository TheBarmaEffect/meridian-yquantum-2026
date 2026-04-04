"""
CVRP Instance Definitions — yQuantum 2026
All 4 hackathon instances with depot at origin.
"""

from dataclasses import dataclass, field
from typing import Dict, Tuple


@dataclass
class CVRPInstance:
    instance_id: int
    num_vehicles: int   # Nv
    capacity: int       # C (max customers per vehicle)
    depot: Tuple[int, int]
    customers: Dict[int, Tuple[int, int]]

    @property
    def num_customers(self) -> int:
        return len(self.customers)


INSTANCES: Dict[int, CVRPInstance] = {
    1: CVRPInstance(
        instance_id=1, num_vehicles=2, capacity=5,
        depot=(0, 0),
        customers={1: (-2, 2), 2: (-5, 8), 3: (2, 3)},
    ),
    2: CVRPInstance(
        instance_id=2, num_vehicles=2, capacity=2,
        depot=(0, 0),
        customers={1: (-2, 2), 2: (-5, 8), 3: (2, 3)},
    ),
    3: CVRPInstance(
        instance_id=3, num_vehicles=3, capacity=2,
        depot=(0, 0),
        customers={
            1: (-2, 2), 2: (-5, 8), 3: (2, 3),
            4: (5, 7), 5: (2, 4), 6: (2, -3),
        },
    ),
    4: CVRPInstance(
        instance_id=4, num_vehicles=4, capacity=3,
        depot=(0, 0),
        customers={
            1: (-2, 2), 2: (-5, 8), 3: (6, 3), 4: (4, 4),
            5: (3, 2), 6: (0, 2), 7: (-2, 3), 8: (-4, 3),
            9: (2, 3), 10: (2, 7), 11: (-2, 5), 12: (-1, 4),
        },
    ),
}
