"""Pure, dependency-free graph helpers for planning-control dependencies."""
from __future__ import annotations

from collections import deque
from typing import Any

PREREQUISITE_TYPES = {"requires", "precedes", "enables", "reveals", "pays_off"}


def node_key(node: dict[str, Any]) -> str:
    return f"{node.get('node_type', '')}:{node.get('node_id', '')}"


def active_dependencies(items: list[dict[str, Any]], prerequisite_only: bool = False) -> list[dict[str, Any]]:
    return [item for item in items if item.get("status") == "active" and (not prerequisite_only or item.get("dependency_type") in PREREQUISITE_TYPES)]


def adjacency(items: list[dict[str, Any]], prerequisite_only: bool = False) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    forward: dict[str, set[str]] = {}
    reverse: dict[str, set[str]] = {}
    for item in active_dependencies(items, prerequisite_only):
        start, end = node_key(item.get("from_node", {})), node_key(item.get("to_node", {}))
        forward.setdefault(start, set()).add(end)
        reverse.setdefault(end, set()).add(start)
    return forward, reverse


def path(graph: dict[str, set[str]], start: str, target: str) -> list[str] | None:
    """Return a deterministic breadth-first path, including both endpoints."""
    queue: deque[list[str]] = deque([[start]])
    visited = {start}
    while queue:
        current = queue.popleft()
        here = current[-1]
        if here == target:
            return current
        for next_key in sorted(graph.get(here, ())):
            if next_key not in visited:
                visited.add(next_key)
                queue.append(current + [next_key])
    return None


def cycle_for_edge(items: list[dict[str, Any]], from_node: dict[str, Any], to_node: dict[str, Any]) -> list[str] | None:
    """A proposed prerequisite edge closes a cycle when downstream reaches upstream."""
    forward, _ = adjacency(items, prerequisite_only=True)
    start, end = node_key(from_node), node_key(to_node)
    closing = path(forward, end, start)
    return [start] + closing if closing else None


def mutual_blocks(items: list[dict[str, Any]]) -> list[list[str]]:
    pairs: set[tuple[str, str]] = set()
    blocks = [item for item in active_dependencies(items) if item.get("dependency_type") == "blocks"]
    edges = {(node_key(item.get("from_node", {})), node_key(item.get("to_node", {}))) for item in blocks}
    for start, end in edges:
        if (end, start) in edges:
            pairs.add(tuple(sorted((start, end))))
    return [list(pair) for pair in sorted(pairs)]


def first_cycle(graph: dict[str, set[str]]) -> list[str] | None:
    """Return one directed cycle without treating a zero-length path as a cycle."""
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(current: str, trail: list[str]) -> list[str] | None:
        visiting.add(current)
        for following in sorted(graph.get(current, ())):
            if following in visiting:
                return trail[trail.index(following):] + [following]
            if following not in visited:
                found = visit(following, trail + [following])
                if found:
                    return found
        visiting.remove(current); visited.add(current)
        return None

    for start in sorted(graph):
        if start not in visited:
            found = visit(start, [start])
            if found:
                return found
    return None
