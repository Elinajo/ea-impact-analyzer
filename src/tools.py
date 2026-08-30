"""Deterministic tools over the EA graph — SPEC.md step 3.

Pure Python, no LLM. Every result is a :class:`Finding` that carries the
relationship path that produced it, so the reasoning can be shown rather than
asserted.

Two semantic rules drive everything here:

* ``OWNS`` vs ``CONSUMES``. Retiring an application orphans the data it owns
  (nothing is authoritative for it any more). Data it merely consumes is
  untouched; only the consumer loses access. See ``orphaned_data_if_retired``.
* A technology is orphaned only when the retired application was the *last*
  one running on it. See ``orphaned_technologies_if_retired``.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Iterable

from .graph import EAGraph, Edge

__all__ = [
    "Finding",
    "ImpactReport",
    "ids",
    "applications_for_capability",
    "direct_dependents",
    "transitive_dependents",
    "indirect_dependents",
    "owned_data",
    "consumed_data",
    "consumers_without_ownership",
    "orphaned_data_if_retired",
    "orphaned_technologies_if_retired",
    "capabilities_losing_all_support",
    "capabilities_degraded_by_retiring",
    "capabilities_unaffected_by_retiring",
    "impact_of_retiring",
]


@dataclass(frozen=True)
class Finding:
    """One element a tool returned, with the evidence for it.

    ``path`` holds real relationships from the model, in reading order. Where a
    finding also rests on the *absence* of a relationship ("no other application
    runs on T03"), that part is stated in ``explanation`` — an absence has no
    edge to point at.
    """

    id: str
    name: str
    kind: str
    explanation: str
    path: tuple[Edge, ...] = ()
    depth: int | None = None  # hop count, for dependency findings

    def render(self) -> str:
        trail = " ; ".join(str(edge) for edge in self.path) or "no relationship path"
        return f"{self.id} ({self.name}): {self.explanation} [{trail}]"

    def as_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "explanation": self.explanation,
            "path": [edge.as_dict() for edge in self.path],
        }
        if self.depth is not None:
            result["depth"] = self.depth
        return result


def ids(findings: Iterable[Finding]) -> list[str]:
    """The element ids of a finding list, sorted — the form the eval set uses."""
    return sorted(finding.id for finding in findings)


def _finding(graph: EAGraph, element_id: str, explanation: str, path: Iterable[Edge] = (), depth: int | None = None) -> Finding:
    element = graph.element(element_id)
    return Finding(
        id=element.id,
        name=element.name,
        kind=element.kind,
        explanation=explanation,
        path=tuple(path),
        depth=depth,
    )


def _sorted(findings: Iterable[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: f.id)


# --------------------------------------------------------------- basic lookups


def applications_for_capability(graph: EAGraph, capability_id: str) -> list[Finding]:
    """Applications that realise part of a capability (inbound SUPPORTS)."""
    capability = graph.require(capability_id, "capability")
    return _sorted(
        _finding(
            graph,
            edge.source,
            f"supports {capability.id} ({capability.name})",
            [edge],
        )
        for edge in graph.incoming(capability.id, "SUPPORTS")
    )


def owned_data(graph: EAGraph, application_id: str) -> list[Finding]:
    """Data objects the application is the authoritative source for."""
    application = graph.require(application_id, "application")
    return _sorted(
        _finding(graph, edge.target, f"{application.id} is an authoritative source", [edge])
        for edge in graph.outgoing(application.id, "OWNS")
    )


def consumed_data(graph: EAGraph, application_id: str) -> list[Finding]:
    """Data objects the application reads but is not authoritative for."""
    application = graph.require(application_id, "application")
    return _sorted(
        _finding(graph, edge.target, f"{application.id} reads it but does not own it", [edge])
        for edge in graph.outgoing(application.id, "CONSUMES")
    )


def consumers_without_ownership(graph: EAGraph, data_object_id: str) -> list[Finding]:
    """Applications that consume a data object without owning it.

    The model forbids an application both owning and consuming the same data
    object, but the ownership check is made here anyway rather than assumed:
    the point of the tool is that consumption and authority are different facts.
    """
    data_object = graph.require(data_object_id, "data_object")
    owners = set(graph.sources(data_object.id, "OWNS"))
    return _sorted(
        _finding(
            graph,
            edge.source,
            f"consumes {data_object.id} and is not among its owners "
            f"({', '.join(sorted(owners)) or 'none recorded'})",
            [edge],
        )
        for edge in graph.incoming(data_object.id, "CONSUMES")
        if edge.source not in owners
    )


# ------------------------------------------------------------- dependency tree


def _dependency_paths(graph: EAGraph, application_id: str) -> dict[str, list[tuple[Edge, ...]]]:
    """Every simple DEPENDS_ON path that ends at ``application_id``.

    Walks inbound DEPENDS_ON edges breadth-first, so each application's paths
    are recorded shortest-first. Paths read from the dependent application down
    to the one being retired: ``A07 -DEPENDS_ON-> A01 ; A01 -DEPENDS_ON-> A05``.
    A node is never revisited within a single path, so cycles terminate.
    """
    graph.require(application_id, "application")
    paths: dict[str, list[tuple[Edge, ...]]] = defaultdict(list)
    queue: deque[tuple[str, tuple[Edge, ...], frozenset[str]]] = deque(
        [(application_id, (), frozenset({application_id}))]
    )
    while queue:
        current, path, visited = queue.popleft()
        for edge in graph.incoming(current, "DEPENDS_ON"):
            if edge.source in visited:
                continue
            extended = (edge,) + path
            paths[edge.source].append(extended)
            queue.append((edge.source, extended, visited | {edge.source}))
    return paths


def direct_dependents(graph: EAGraph, application_id: str) -> list[Finding]:
    """Applications with a DEPENDS_ON edge straight to this one."""
    application = graph.require(application_id, "application")
    return _sorted(
        _finding(
            graph,
            edge.source,
            f"depends directly on {application.id} ({application.name})",
            [edge],
            depth=1,
        )
        for edge in graph.incoming(application.id, "DEPENDS_ON")
    )


def transitive_dependents(graph: EAGraph, application_id: str) -> list[Finding]:
    """Every application that reaches this one through DEPENDS_ON, at any depth.

    Includes the direct dependents. Evidence is the shortest path found.
    """
    paths = _dependency_paths(graph, application_id)
    return _sorted(
        _finding(
            graph,
            dependent,
            f"reaches {application_id} through {len(found[0])} DEPENDS_ON hop(s)",
            found[0],
            depth=len(found[0]),
        )
        for dependent, found in paths.items()
    )


def indirect_dependents(graph: EAGraph, application_id: str) -> list[Finding]:
    """Applications affected through an intermediary — a path of two or more hops.

    An application can appear here *and* in ``direct_dependents``: A07 depends on
    A05 directly and again through A01. Those are two distinct facts about A07,
    and the eval set (Q05) asks for the indirect one specifically, so neither is
    suppressed to keep the sets disjoint.
    """
    paths = _dependency_paths(graph, application_id)
    findings = []
    for dependent, found in paths.items():
        indirect = next((p for p in found if len(p) >= 2), None)
        if indirect is None:
            continue
        via = " -> ".join(edge.source for edge in indirect[1:])
        findings.append(
            _finding(
                graph,
                dependent,
                f"reaches {application_id} via {via} ({len(indirect)} hops)",
                indirect,
                depth=len(indirect),
            )
        )
    return _sorted(findings)


# ---------------------------------------------------------- retirement effects


def orphaned_data_if_retired(graph: EAGraph, application_id: str) -> list[Finding]:
    """Data objects left with no authoritative source.

    Only OWNS is considered. Data the application CONSUMES is unaffected by its
    retirement — the data keeps its owner; the consumer is the one that loses
    access. A data object with a second owner is not orphaned either.
    """
    application = graph.require(application_id, "application")
    findings = []
    for edge in graph.outgoing(application.id, "OWNS"):
        other_owners = [owner for owner in graph.sources(edge.target, "OWNS") if owner != application.id]
        if other_owners:
            continue
        findings.append(
            _finding(
                graph,
                edge.target,
                f"{application.id} is its only authoritative source; "
                "no other application OWNS it",
                [edge],
            )
        )
    return _sorted(findings)


def orphaned_technologies_if_retired(graph: EAGraph, application_id: str) -> list[Finding]:
    """Technologies the retired application was the last one running on.

    A technology still carrying another application is not orphaned, even if
    that application is itself a dependent of the one being retired: it has not
    been retired, so it is still running.
    """
    application = graph.require(application_id, "application")
    findings = []
    for edge in graph.outgoing(application.id, "RUNS_ON"):
        remaining = [app for app in graph.sources(edge.target, "RUNS_ON") if app != application.id]
        if remaining:
            continue
        findings.append(
            _finding(
                graph,
                edge.target,
                f"{application.id} is the only application running on it",
                [edge],
            )
        )
    return _sorted(findings)


def _affected_applications(graph: EAGraph, application_id: str) -> dict[str, tuple[Edge, ...]]:
    """The retired application plus everything downstream of it, with evidence."""
    affected: dict[str, tuple[Edge, ...]] = {application_id: ()}
    for dependent, paths in _dependency_paths(graph, application_id).items():
        affected[dependent] = paths[0]
    return affected


def capabilities_losing_all_support(graph: EAGraph, application_id: str) -> list[Finding]:
    """Capabilities whose only supporting application is the retired one.

    First-order only: a capability still supported by an application that merely
    *depends* on the retired one has not lost its support, it is degraded. That
    is a different claim and is reported separately.
    """
    application = graph.require(application_id, "application")
    findings = []
    for edge in graph.outgoing(application.id, "SUPPORTS"):
        others = [app for app in graph.sources(edge.target, "SUPPORTS") if app != application.id]
        if others:
            continue
        findings.append(
            _finding(
                graph,
                edge.target,
                f"{application.id} is its only supporting application",
                [edge],
            )
        )
    return _sorted(findings)


def capabilities_degraded_by_retiring(graph: EAGraph, application_id: str) -> list[Finding]:
    """Capabilities that keep some support but are affected.

    Either a supporting application is the retired one (and others remain), or a
    supporting application depends on the retired one directly or transitively.
    """
    graph.require(application_id, "application")
    lost = {finding.id for finding in capabilities_losing_all_support(graph, application_id)}
    affected = _affected_applications(graph, application_id)

    findings = []
    for capability in graph.elements_of_kind("capability"):
        if capability.id in lost:
            continue
        for edge in sorted(graph.incoming(capability.id, "SUPPORTS"), key=lambda e: e.source):
            if edge.source not in affected:
                continue
            dependency_path = affected[edge.source]
            if dependency_path:
                explanation = (
                    f"supporting application {edge.source} depends on {application_id} "
                    f"({len(dependency_path)} hop(s))"
                )
            else:
                explanation = (
                    f"loses supporting application {application_id}, "
                    "but other applications still support it"
                )
            findings.append(
                _finding(graph, capability.id, explanation, tuple(dependency_path) + (edge,))
            )
            break
    return _sorted(findings)


def capabilities_unaffected_by_retiring(graph: EAGraph, application_id: str) -> list[Finding]:
    """Capabilities with no supporting application in the affected set.

    The negative control the eval set asks for (Q08).
    """
    graph.require(application_id, "application")
    affected = _affected_applications(graph, application_id)
    findings = []
    for capability in graph.elements_of_kind("capability"):
        supporters = graph.sources(capability.id, "SUPPORTS")
        if any(supporter in affected for supporter in supporters):
            continue
        findings.append(
            _finding(
                graph,
                capability.id,
                "supported by {} — none of which is affected by retiring {}".format(
                    ", ".join(supporters) or "no application", application_id
                ),
                [edge for edge in graph.incoming(capability.id, "SUPPORTS")],
            )
        )
    return _sorted(findings)


@dataclass(frozen=True)
class ImpactReport:
    """Structured result of retiring one application. Every list holds
    :class:`Finding` objects carrying their own relationship path."""

    application_id: str
    application_name: str
    direct_dependents: list[Finding] = field(default_factory=list)
    indirect_dependents: list[Finding] = field(default_factory=list)
    transitive_dependents: list[Finding] = field(default_factory=list)
    orphaned_data_objects: list[Finding] = field(default_factory=list)
    consumed_data_unaffected: list[Finding] = field(default_factory=list)
    capabilities_losing_all_support: list[Finding] = field(default_factory=list)
    capabilities_degraded: list[Finding] = field(default_factory=list)
    capabilities_unaffected: list[Finding] = field(default_factory=list)
    orphaned_technologies: list[Finding] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "application": {"id": self.application_id, "name": self.application_name},
            "direct_dependents": [f.as_dict() for f in self.direct_dependents],
            "indirect_dependents": [f.as_dict() for f in self.indirect_dependents],
            "transitive_dependents": [f.as_dict() for f in self.transitive_dependents],
            "orphaned_data_objects": [f.as_dict() for f in self.orphaned_data_objects],
            "consumed_data_unaffected": [f.as_dict() for f in self.consumed_data_unaffected],
            "capabilities_losing_all_support": [
                f.as_dict() for f in self.capabilities_losing_all_support
            ],
            "capabilities_degraded": [f.as_dict() for f in self.capabilities_degraded],
            "capabilities_unaffected": [f.as_dict() for f in self.capabilities_unaffected],
            "orphaned_technologies": [f.as_dict() for f in self.orphaned_technologies],
        }

    def _dependent_lines(self) -> list[str]:
        """Dependent applications, one line each, with every route beneath it.

        ``direct_dependents`` and ``indirect_dependents`` are not disjoint: A07
        depends on A05 straight and again through A01. Those are two facts about
        one application, and making the lists disjoint would delete one of them.
        The traversal therefore keeps both, and the merge happens here, in the
        presentation — so a reader sees one entry per application and cannot
        count A07 twice. DECISIONS.md D06.
        """
        routes: dict[str, list[tuple[str, Finding]]] = {}
        for label, findings in (("direct", self.direct_dependents), ("indirect", self.indirect_dependents)):
            for finding in findings:
                routes.setdefault(finding.id, []).append((label, finding))

        lines: list[str] = []
        for element_id in sorted(routes):
            entries = routes[element_id]
            name = entries[0][1].name
            labels = " and ".join(label for label, _ in entries)
            lines.append(f"  - {element_id} ({name}): depends on {self.application_id}, {labels}")
            for label, finding in entries:
                trail = " ; ".join(str(edge) for edge in finding.path) or "no relationship path"
                lines.append(f"      · {label}: {trail}")
        return lines or ["  (none)"]

    def render(self) -> str:
        sections = [
            ("Orphaned data objects", self.orphaned_data_objects),
            ("Consumed data (unaffected)", self.consumed_data_unaffected),
            ("Capabilities losing all support", self.capabilities_losing_all_support),
            ("Capabilities degraded", self.capabilities_degraded),
            ("Capabilities unaffected", self.capabilities_unaffected),
            ("Orphaned technologies", self.orphaned_technologies),
        ]
        lines = [f"Impact of retiring {self.application_id} ({self.application_name})"]
        lines.append("\nDependent applications:")
        lines.extend(self._dependent_lines())
        for title, findings in sections:
            lines.append(f"\n{title}:")
            if not findings:
                lines.append("  (none)")
            lines.extend(f"  - {finding.render()}" for finding in findings)
        return "\n".join(lines)


def impact_of_retiring(graph: EAGraph, application_id: str) -> ImpactReport:
    """Full impact of retiring one application, with evidence per entry."""
    application = graph.require(application_id, "application")
    consumed_unaffected = [
        Finding(
            id=finding.id,
            name=finding.name,
            kind=finding.kind,
            explanation=(
                f"{application.id} consumes it but is not authoritative for it, "
                "so retirement does not orphan it"
            ),
            path=finding.path,
        )
        for finding in consumed_data(graph, application.id)
    ]
    return ImpactReport(
        application_id=application.id,
        application_name=application.name,
        direct_dependents=direct_dependents(graph, application.id),
        indirect_dependents=indirect_dependents(graph, application.id),
        transitive_dependents=transitive_dependents(graph, application.id),
        orphaned_data_objects=orphaned_data_if_retired(graph, application.id),
        consumed_data_unaffected=consumed_unaffected,
        capabilities_losing_all_support=capabilities_losing_all_support(graph, application.id),
        capabilities_degraded=capabilities_degraded_by_retiring(graph, application.id),
        capabilities_unaffected=capabilities_unaffected_by_retiring(graph, application.id),
        orphaned_technologies=orphaned_technologies_if_retired(graph, application.id),
    )
