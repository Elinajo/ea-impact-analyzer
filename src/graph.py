"""Load and validate the EA model, and expose lookups over it.

Step 1 of SPEC.md. This module is a typed, validated view over
``data/ea_model.json`` and nothing more: no traversal semantics, no LLM,
no retrieval. Anything that reasons about retirement lives in ``tools.py``.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL_PATH = REPO_ROOT / "data" / "ea_model.json"

#: element kind -> the JSON key that holds elements of that kind
ELEMENT_COLLECTIONS: Mapping[str, str] = {
    "capability": "capabilities",
    "application": "applications",
    "data_object": "data_objects",
    "technology": "technologies",
}

#: relationship type -> (source kind, target kind).
#: Mirrors ``_relationship_semantics`` in the model file. Kept in code rather
#: than parsed from the prose in that block, so the constraint is executable.
RELATIONSHIP_ENDPOINTS: Mapping[str, tuple[str, str]] = {
    "SUPPORTS": ("application", "capability"),
    "OWNS": ("application", "data_object"),
    "CONSUMES": ("application", "data_object"),
    "DEPENDS_ON": ("application", "application"),
    "RUNS_ON": ("application", "technology"),
}


class GraphValidationError(ValueError):
    """Raised when the model file is internally inconsistent.

    Carries every problem found, not just the first, so a broken model can be
    fixed in one pass.
    """

    def __init__(self, errors: list[str]) -> None:
        self.errors = list(errors)
        super().__init__(
            "invalid EA model ({} problem(s)):\n  - {}".format(
                len(self.errors), "\n  - ".join(self.errors)
            )
        )


class UnknownElementError(KeyError):
    """Raised when an element id is not present in the model."""


#: Problems that are a modelling judgement rather than a broken file. Under
#: ``strict=False`` these are collected in :attr:`EAGraph.warnings` instead of
#: raising — see DECISIONS.md D05. Structural faults (a missing endpoint, an
#: endpoint of the wrong kind, an unknown relationship type) are never
#: downgradable: nothing can be computed over them.
DOWNGRADABLE = "owns_and_consumes"


@dataclass(frozen=True)
class Element:
    """A node: a capability, application, data object or technology."""

    id: str
    name: str
    kind: str
    # lifecycle and any other element properties; excluded from eq/hash so
    # Element stays hashable.
    attributes: Mapping[str, object] = field(default_factory=dict, compare=False)

    def __str__(self) -> str:
        return f"{self.id} ({self.name})"


@dataclass(frozen=True)
class Edge:
    """A single relationship, exactly as recorded in the model."""

    source: str
    type: str
    target: str

    def __str__(self) -> str:
        return f"{self.source} -{self.type}-> {self.target}"

    def as_dict(self) -> dict[str, str]:
        return {"from": self.source, "type": self.type, "to": self.target}


class EAGraph:
    """Validated, immutable view over the architecture model."""

    def __init__(
        self,
        elements: Iterable[Element],
        edges: Iterable[Edge],
        about: str = "",
        warnings: Iterable[str] = (),
    ) -> None:
        self._elements: dict[str, Element] = {e.id: e for e in elements}
        self._edges: tuple[Edge, ...] = tuple(edges)
        self.about = about
        #: Problems tolerated under ``strict=False``. A loaded graph that is not
        #: empty here is usable but has been flagged; callers that care are
        #: expected to surface it rather than let it pass silently.
        self.warnings: tuple[str, ...] = tuple(warnings)

        self._outgoing: dict[str, list[Edge]] = defaultdict(list)
        self._incoming: dict[str, list[Edge]] = defaultdict(list)
        for edge in self._edges:
            self._outgoing[edge.source].append(edge)
            self._incoming[edge.target].append(edge)

    # ------------------------------------------------------------------ load

    @classmethod
    def load(cls, path: str | Path = DEFAULT_MODEL_PATH, strict: bool = True) -> "EAGraph":
        """Load and validate a model from a JSON file.

        With ``strict=False`` the modelling judgement in :data:`DOWNGRADABLE`
        is collected in :attr:`warnings` instead of raising.
        """
        with open(path, "r", encoding="utf-8") as handle:
            return cls.from_dict(json.load(handle), strict=strict)

    @classmethod
    def from_dict(cls, document: Mapping[str, object], strict: bool = True) -> "EAGraph":
        """Build a graph from an already-parsed model document."""
        errors: list[str] = []
        warnings: list[str] = []
        elements: dict[str, Element] = {}

        for kind, collection in ELEMENT_COLLECTIONS.items():
            raw = document.get(collection, [])
            if not isinstance(raw, list):
                errors.append(f"{collection}: expected a list, got {type(raw).__name__}")
                continue
            for index, item in enumerate(raw):
                if not isinstance(item, dict) or "id" not in item or "name" not in item:
                    errors.append(f"{collection}[{index}]: needs both 'id' and 'name'")
                    continue
                element_id = str(item["id"])
                if element_id in elements:
                    errors.append(
                        f"duplicate element id {element_id!r} "
                        f"({elements[element_id].kind} and {kind})"
                    )
                    continue
                attributes = {k: v for k, v in item.items() if k not in ("id", "name")}
                elements[element_id] = Element(
                    id=element_id, name=str(item["name"]), kind=kind, attributes=attributes
                )

        edges: list[Edge] = []
        seen: set[Edge] = set()
        raw_relationships = document.get("relationships", [])
        if not isinstance(raw_relationships, list):
            errors.append("relationships: expected a list")
            raw_relationships = []

        for index, item in enumerate(raw_relationships):
            where = f"relationships[{index}]"
            if not isinstance(item, dict) or not {"from", "type", "to"} <= set(item):
                errors.append(f"{where}: needs 'from', 'type' and 'to'")
                continue
            edge = Edge(str(item["from"]), str(item["type"]), str(item["to"]))

            if edge.type not in RELATIONSHIP_ENDPOINTS:
                errors.append(f"{where}: unknown relationship type {edge.type!r}")
                continue
            expected_source_kind, expected_target_kind = RELATIONSHIP_ENDPOINTS[edge.type]

            # Every relationship endpoint must exist — SPEC.md step 1.
            endpoints_ok = True
            for role, node_id, expected_kind in (
                ("from", edge.source, expected_source_kind),
                ("to", edge.target, expected_target_kind),
            ):
                element = elements.get(node_id)
                if element is None:
                    errors.append(f"{where} ({edge}): {role} endpoint {node_id!r} does not exist")
                    endpoints_ok = False
                elif element.kind != expected_kind:
                    errors.append(
                        f"{where} ({edge}): {role} endpoint {node_id!r} is a {element.kind}, "
                        f"but {edge.type} requires a {expected_kind}"
                    )
                    endpoints_ok = False
            if not endpoints_ok:
                continue

            if edge in seen:
                errors.append(f"{where}: duplicate relationship {edge}")
                continue
            if edge.type == "DEPENDS_ON" and edge.source == edge.target:
                errors.append(f"{where}: {edge.source} cannot depend on itself")
                continue

            seen.add(edge)
            edges.append(edge)

        # An application that both OWNS and CONSUMES one data object. Under the
        # strict reading the pair is contradictory, because CONSUMES means "not
        # authoritative". But a platform that masters its own records and also
        # ingests an external feed of the same kind is a real shape, and the
        # impact answer does not depend on which reading is taken:
        # orphaned_data_if_retired works purely off OWNS either way. So this is
        # reported, and strict mode decides whether that report is fatal.
        # DECISIONS.md D05.
        owned = {(e.source, e.target) for e in edges if e.type == "OWNS"}
        for pair in sorted(owned & {(e.source, e.target) for e in edges if e.type == "CONSUMES"}):
            problem = (
                f"{pair[0]} both OWNS and CONSUMES {pair[1]}: CONSUMES means the "
                "application is not authoritative for that data. Retirement impact is "
                "unaffected — only OWNS orphans a data object — but the two edges say "
                "opposite things about authority and one of them is probably wrong."
            )
            (errors if strict else warnings).append(problem)

        if errors:
            raise GraphValidationError(errors)

        return cls(
            elements.values(),
            edges,
            about=str(document.get("_about", "")),
            warnings=warnings,
        )

    # --------------------------------------------------------------- lookups

    @property
    def edges(self) -> tuple[Edge, ...]:
        return self._edges

    def has(self, element_id: str) -> bool:
        return element_id in self._elements

    def element(self, element_id: str) -> Element:
        """Return an element, or raise ``UnknownElementError``."""
        try:
            return self._elements[element_id]
        except KeyError:
            raise UnknownElementError(f"no element with id {element_id!r} in the model") from None

    def require(self, element_id: str, kind: str) -> Element:
        """Return an element, asserting its kind. Used by the tools to reject
        arguments of the wrong type instead of silently returning nothing."""
        element = self.element(element_id)
        if element.kind != kind:
            raise UnknownElementError(
                f"{element_id!r} is a {element.kind}, expected a {kind}"
            )
        return element

    def name(self, element_id: str) -> str:
        return self.element(element_id).name

    def elements_of_kind(self, kind: str) -> tuple[Element, ...]:
        if kind not in ELEMENT_COLLECTIONS:
            raise ValueError(f"unknown element kind {kind!r}")
        return tuple(sorted((e for e in self._elements.values() if e.kind == kind), key=lambda e: e.id))

    def ids_of_kind(self, kind: str) -> tuple[str, ...]:
        return tuple(e.id for e in self.elements_of_kind(kind))

    def outgoing(self, element_id: str, type: str | None = None) -> tuple[Edge, ...]:
        """Relationships where ``element_id`` is the source."""
        self.element(element_id)
        return tuple(e for e in self._outgoing.get(element_id, ()) if type is None or e.type == type)

    def incoming(self, element_id: str, type: str | None = None) -> tuple[Edge, ...]:
        """Relationships where ``element_id`` is the target."""
        self.element(element_id)
        return tuple(e for e in self._incoming.get(element_id, ()) if type is None or e.type == type)

    def targets(self, element_id: str, type: str) -> tuple[str, ...]:
        return tuple(sorted({e.target for e in self.outgoing(element_id, type)}))

    def sources(self, element_id: str, type: str) -> tuple[str, ...]:
        return tuple(sorted({e.source for e in self.incoming(element_id, type)}))

    def __repr__(self) -> str:
        counts = ", ".join(
            f"{len(self.elements_of_kind(kind))} {collection}"
            for kind, collection in ELEMENT_COLLECTIONS.items()
        )
        return f"<EAGraph {counts}, {len(self._edges)} relationships>"


def load_graph(path: str | Path = DEFAULT_MODEL_PATH, strict: bool = True) -> EAGraph:
    """Convenience wrapper around :meth:`EAGraph.load`."""
    return EAGraph.load(path, strict=strict)
