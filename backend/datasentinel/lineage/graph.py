"""Directed lineage graph algorithms (pure functions, no database).

Pipeline semantics: lineage is a DAG — data flows from sources through transformations to derived
datasets, reports and models. Creating an edge that would close a cycle is therefore rejected by
the API, with the offending path in the error. Every traversal here is nevertheless cycle-safe
(visited sets) so a graph imported or edited outside the API can never hang the service; any
cycles that do exist are reported by ``find_cycles``. Disconnected nodes are valid.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class Graph:
    nodes: dict[str, dict] = field(default_factory=dict)
    out: dict[str, list[str]] = field(default_factory=dict)
    inc: dict[str, list[str]] = field(default_factory=dict)
    edge_labels: dict[tuple[str, str], str] = field(default_factory=dict)

    def add_node(self, node_id: str, **attrs) -> None:
        self.nodes[node_id] = {"id": node_id, **attrs}
        self.out.setdefault(node_id, [])
        self.inc.setdefault(node_id, [])

    def add_edge(self, source: str, target: str, label: str = "") -> None:
        if source not in self.nodes or target not in self.nodes:
            raise KeyError("Both endpoints must be nodes of the graph")
        if target not in self.out[source]:
            self.out[source].append(target)
            self.inc[target].append(source)
        self.edge_labels[(source, target)] = label


def _bfs(adjacency: dict[str, list[str]], start: str) -> dict[str, dict]:
    """Shortest paths from ``start``. Returns {node: {"distance": d, "path": [start, ..., node]}}."""
    parents: dict[str, str | None] = {start: None}
    distance = {start: 0}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        for nxt in sorted(adjacency.get(node, [])):
            if nxt not in parents:
                parents[nxt] = node
                distance[nxt] = distance[node] + 1
                queue.append(nxt)
    result = {}
    for node in parents:
        if node == start:
            continue
        path, cursor = [], node
        while cursor is not None:
            path.append(cursor)
            cursor = parents[cursor]
        result[node] = {"distance": distance[node], "path": list(reversed(path))}
    return result


def downstream(graph: Graph, start: str) -> dict[str, dict]:
    return _bfs(graph.out, start)


def upstream(graph: Graph, start: str) -> dict[str, dict]:
    """Upstream nodes; each path is listed in data-flow order (ancestor → ... → start)."""
    found = _bfs(graph.inc, start)
    return {node: {"distance": info["distance"], "path": list(reversed(info["path"]))} for node, info in found.items()}


def path_to(graph: Graph, source: str, target: str) -> list[str] | None:
    if source == target:
        return [source]
    info = downstream(graph, source).get(target)
    return info["path"] if info else None


def would_create_cycle(graph: Graph, source: str, target: str) -> list[str] | None:
    """If adding source→target closes a cycle, return the cycle as a node path ending where it starts."""
    if source == target:
        return [source, source]
    back = path_to(graph, target, source)
    return [*back, target] if back else None


def strongly_connected_components(graph: Graph) -> list[list[str]]:
    """Tarjan's algorithm, iterative (no recursion limit issues)."""
    index_of: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    components: list[list[str]] = []
    counter = 0
    for root in sorted(graph.nodes):
        if root in index_of:
            continue
        work = [(root, iter(sorted(graph.out[root])))]
        index_of[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            node, children = work[-1]
            advanced = False
            for child in children:
                if child not in index_of:
                    index_of[child] = low[child] = counter
                    counter += 1
                    stack.append(child)
                    on_stack.add(child)
                    work.append((child, iter(sorted(graph.out[child]))))
                    advanced = True
                    break
                if child in on_stack:
                    low[node] = min(low[node], index_of[child])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index_of[node]:
                component = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                components.append(sorted(component))
    return components


def find_cycles(graph: Graph) -> list[list[str]]:
    cycles = [c for c in strongly_connected_components(graph) if len(c) > 1]
    cycles += [[n] for n in graph.nodes if n in graph.out[n]]
    return cycles


def layered_layout(graph: Graph, x_gap: int = 280, y_gap: int = 120) -> dict[str, dict[str, int]]:
    """Left-to-right layering by longest path from the roots (Kahn's algorithm).

    Nodes that sit on a cycle cannot be ordered topologically; they are placed in a final column.
    """
    indegree = {node: len(graph.inc[node]) for node in graph.nodes}
    level = dict.fromkeys(graph.nodes, 0)
    queue = deque(sorted(n for n, d in indegree.items() if d == 0))
    placed = set()
    while queue:
        node = queue.popleft()
        placed.add(node)
        for nxt in graph.out[node]:
            level[nxt] = max(level[nxt], level[node] + 1)
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    if len(placed) < len(graph.nodes):
        last = max((level[n] for n in placed), default=-1) + 1
        for node in graph.nodes:
            if node not in placed:
                level[node] = last
    columns: dict[int, list[str]] = {}
    for node, lvl in level.items():
        columns.setdefault(lvl, []).append(node)
    positions = {}
    for lvl, members in columns.items():
        members.sort(key=lambda n: (graph.nodes[n].get("kind", ""), graph.nodes[n].get("name", n)))
        for row, node in enumerate(members):
            positions[node] = {"x": lvl * x_gap, "y": row * y_gap}
    return positions
