"""Coordinate, graph, baseline aggregation, and loop-closure helpers."""
import math
from typing import Any, Dict, Iterable, List, Optional

def _is_usable_llh(llh: Optional[tuple[float, float, float]]) -> bool:
    if llh is None:
        return False
    lat, lon, height = llh
    if not all(math.isfinite(value) for value in (lat, lon, height)):
        return False
    # UM980 uses 0,0,0 when no base coordinate is available.  It is not useful
    # for converting an N/E/U vector into ECEF in this workflow.
    if abs(lat) < 1e-12 and abs(lon) < 1e-12 and abs(height) < 1e-12:
        return False
    return -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0


def _llh_horizontal_distance_m(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
) -> float:
    """Horizontal separation used to identify a correction BASE.

    AGRICA and GGA heights may use ellipsoidal and MSL datums respectively;
    their geoid-sized height difference must not make the same BASE look like a
    different station.
    """

    mean_latitude = math.radians((float(first[0]) + float(second[0])) / 2.0)
    north = math.radians(float(first[0]) - float(second[0])) * 6378137.0
    east = (
        math.radians(float(first[1]) - float(second[1]))
        * 6378137.0
        * math.cos(mean_latitude)
    )
    return math.hypot(north, east)


def _ecef_to_llh(x: float, y: float, z: float) -> tuple[float, float, float]:
    """Convert WGS84 ECEF metres to latitude, longitude and ellipsoidal height."""

    a = 6378137.0
    f = 1 / 298.257223563
    e2 = 2 * f - f**2
    lon = math.atan2(y, x)
    p = math.hypot(x, y)
    lat = math.atan2(z, p * (1 - e2))
    height = 0.0
    for _ in range(8):
        sin_lat = math.sin(lat)
        n = a / math.sqrt(1 - e2 * sin_lat**2)
        height = p / max(math.cos(lat), 1e-15) - n
        next_lat = math.atan2(z, p * (1 - e2 * n / (n + height)))
        if abs(next_lat - lat) < 1e-13:
            lat = next_lat
            break
        lat = next_lat
    return math.degrees(lat), math.degrees(lon), height


def _neu_to_ecef_delta(
    latitude_deg: float,
    longitude_deg: float,
    north: float,
    east: float,
    up: float,
) -> tuple[float, float, float]:
    """Rotate a local N/E/U baseline into the ECEF frame at its base point."""

    lat = math.radians(latitude_deg)
    lon = math.radians(longitude_deg)
    sin_lat, cos_lat = math.sin(lat), math.cos(lat)
    sin_lon, cos_lon = math.sin(lon), math.cos(lon)
    return (
        -sin_lat * cos_lon * north - sin_lon * east + cos_lat * cos_lon * up,
        -sin_lat * sin_lon * north + cos_lon * east + cos_lat * sin_lon * up,
        cos_lat * north + sin_lat * up,
    )


def _vector_length(vector: Any) -> float:
    """Return a 3-D vector length without involving the adjustment engine."""

    return math.sqrt(sum(float(value) ** 2 for value in vector))


def _canonical_baseline(
    start: str,
    end: str,
    vector: Any,
) -> tuple[tuple[str, str], tuple[float, float, float], int]:
    """Return a stable undirected edge key and a consistently signed vector."""

    start, end = str(start), str(end)
    values = tuple(float(value) for value in vector)
    if start == "BASE" or (end != "BASE" and start <= end):
        return (start, end), values, 1
    return (end, start), tuple(-value for value in values), -1


def _graph_components(
    nodes: Iterable[str],
    edges: Iterable[tuple[str, str]],
) -> list[set[str]]:
    """Return case-insensitive connected components using configured node names."""

    name_by_key = {str(node).casefold(): str(node) for node in nodes}
    adjacency = {key: set() for key in name_by_key}
    for start, end in edges:
        start_key = str(start).casefold()
        end_key = str(end).casefold()
        if start_key not in adjacency or end_key not in adjacency or start_key == end_key:
            continue
        adjacency[start_key].add(end_key)
        adjacency[end_key].add(start_key)

    components: list[set[str]] = []
    remaining = set(adjacency)
    while remaining:
        seed = next(iter(remaining))
        pending = [seed]
        component_keys: set[str] = set()
        while pending:
            key = pending.pop()
            if key in component_keys:
                continue
            component_keys.add(key)
            pending.extend(adjacency[key] - component_keys)
        remaining -= component_keys
        components.append({name_by_key[key] for key in component_keys})
    return components


def _average_row_metrics(rows: list[tuple[dict, int]], item: dict) -> None:
    for key in ("observed_xyz", "adjusted_xyz", "residual_xyz"):
        if all(row.get(key) is not None for row, _ in rows):
            item[key] = tuple(
                sum(direction * float(row[key][axis]) for row, direction in rows)
                / len(rows)
                for axis in range(3)
            )
    if all(row.get("standard_deviation_xyz") is not None for row, _ in rows):
        item["standard_deviation_xyz"] = tuple(
            sum(float(row["standard_deviation_xyz"][axis]) for row, _ in rows)
            / len(rows)
            for axis in range(3)
        )
    for key in ("velocity_up_std", "ratio"):
        values = [float(row[key]) for row, _ in rows if row.get(key) is not None]
        if values:
            item[key] = sum(values) / len(values)
    if item.get("observed_xyz") is not None:
        item["observed_length"] = _vector_length(item["observed_xyz"])
    if item.get("adjusted_xyz") is not None:
        item["adjusted_length"] = _vector_length(item["adjusted_xyz"])


def _aggregate_parallel_baselines(baselines: List[dict]) -> List[dict]:
    """Collapse repeated/reverse report rows to one arithmetic mean per edge."""
    groups: Dict[tuple[str, str], list[tuple[dict, int]]] = {}
    for baseline in baselines:
        key, _, direction = _canonical_baseline(
            baseline["from"], baseline["to"], baseline["observed_xyz"]
        )
        groups.setdefault(key, []).append((baseline, direction))

    averaged = []
    for (start, end), rows in groups.items():
        item = dict(rows[0][0])
        item["from"], item["to"] = start, end
        item["observation_count"] = len(rows)
        _average_row_metrics(rows, item)
        averaged.append(item)
    return averaged


def _sum_cycle_vectors(
    steps: List[tuple[int, int]], baselines: List[dict], vector_key: str
) -> tuple[float, float, float]:
    total = [0.0, 0.0, 0.0]
    for edge_index, direction in steps:
        vector = baselines[edge_index][vector_key]
        for component in range(3):
            total[component] += direction * float(vector[component])
    return total[0], total[1], total[2]


def _find_tree_path(
    tree: Dict[str, List[tuple[str, int, int]]], start: str, end: str
) -> tuple[List[str], List[tuple[int, int]]]:
    pending = [(end, [end], [])]
    visited = set()
    while pending:
        node, points, steps = pending.pop()
        if node == start:
            return points, steps
        if node in visited:
            continue
        visited.add(node)
        for neighbor, edge_index, direction in reversed(tree.get(node, [])):
            if neighbor not in visited:
                pending.append((neighbor, points + [neighbor], steps + [(edge_index, direction)]))
    return [], []


def _build_single_loop(
    loop_number: int,
    chord_index: int,
    start: str,
    end: str,
    path_points: List[str],
    path_steps: List[tuple[int, int]],
    baselines: List[dict],
) -> dict | None:
    cycle_steps = [(chord_index, 1)] + path_steps
    cycle_points = [start, end] + path_points[1:]
    if len(set(cycle_points)) < 3:
        return None

    observed = _sum_cycle_vectors(cycle_steps, baselines, "observed_xyz")
    adjusted = _sum_cycle_vectors(cycle_steps, baselines, "adjusted_xyz")
    total_length = sum(
        float(baselines[index]["observed_length"]) for index, _ in cycle_steps
    )
    observed_closure = _vector_length(observed)
    adjusted_closure = _vector_length(adjusted)
    return {
        "loop": loop_number,
        "points": cycle_points,
        "baseline_indices": [index for index, _ in cycle_steps],
        "baseline_directions": [direction for _, direction in cycle_steps],
        "observed_misclosure_xyz": observed,
        "observed_closure": observed_closure,
        "adjusted_misclosure_xyz": adjusted,
        "adjusted_closure": adjusted_closure,
        "total_length": total_length,
        "observed_relative_precision": (
            total_length / observed_closure if observed_closure > 1e-15 else None
        ),
        "adjusted_relative_precision": (
            total_length / adjusted_closure if adjusted_closure > 1e-15 else None
        ),
    }


def _build_fundamental_loops(baselines: List[dict]) -> List[dict]:
    """Find a deterministic independent cycle basis for a baseline multigraph."""
    parent: Dict[str, str] = {}
    tree: Dict[str, List[tuple[str, int, int]]] = {}
    chords: List[int] = []

    def find(name: str) -> str:
        parent.setdefault(name, name)
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name

    def tree_edge_order(edge_index: int) -> tuple[int, str, str, int]:
        baseline = baselines[edge_index]
        start, end = str(baseline["from"]), str(baseline["to"])
        normalized = tuple(sorted((start, end), key=str.casefold))
        touches_base = any(point.casefold() == "base" for point in normalized)
        return int(touches_base), normalized[0].casefold(), normalized[1].casefold(), edge_index

    for edge_index in sorted(range(len(baselines)), key=tree_edge_order):
        baseline = baselines[edge_index]
        start, end = str(baseline["from"]), str(baseline["to"])
        root_start, root_end = find(start), find(end)
        tree.setdefault(start, [])
        tree.setdefault(end, [])
        if root_start == root_end:
            chords.append(edge_index)
            continue
        parent[root_end] = root_start
        tree[start].append((end, edge_index, 1))
        tree[end].append((start, edge_index, -1))

    loops: List[dict] = []
    for loop_number, chord_index in enumerate(chords, start=1):
        chord = baselines[chord_index]
        start, end = str(chord["from"]), str(chord["to"])
        path_points, path_steps = _find_tree_path(tree, start, end)
        if not path_points:
            continue
        loop_item = _build_single_loop(
            loop_number, chord_index, start, end, path_points, path_steps, baselines
        )
        if loop_item is not None:
            loops.append(loop_item)
    return loops

