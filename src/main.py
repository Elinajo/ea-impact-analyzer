"""Command line interface — SPEC.md step 7. One question in, answer plus
evidence out.

    python3 -m src.main "Which applications depend on the Operational Data Platform?"
    python3 -m src.main --json "Can we safely retire the Operational Data Platform?"

Needs ANTHROPIC_API_KEY (environment or .env). Without a key, the deterministic
layer is still fully usable — see ``--impact``, which needs no model at all.
"""

from __future__ import annotations

import argparse
import json
import sys

from .graph import (
    ELEMENT_COLLECTIONS,
    RELATIONSHIP_ENDPOINTS,
    GraphValidationError,
    load_graph,
)
from .llm import Analyst, ConfigurationError
from .retrieval import DEFAULT_CORPUS_ROOT, KeywordRetriever
from .tools import impact_of_retiring


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m src.main",
        description="Ask a question about the EA model. Answers cite the relationship "
        "path or document they came from.",
    )
    parser.add_argument("question", nargs="?", help="The question, in quotes.")
    parser.add_argument(
        "--impact",
        metavar="APPLICATION_ID",
        help="Print the deterministic impact report for one application and exit. "
        "No model involved, no API key needed.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print the whole model — every element and every relationship — and exit.",
    )
    parser.add_argument(
        "--show",
        metavar="ELEMENT_ID",
        help="Print one element and everything connected to it, and exit.",
    )
    parser.add_argument("--json", action="store_true", help="Machine-readable output.")
    parser.add_argument(
        "--no-evidence",
        action="store_true",
        help="Answer only. The evidence is the point, so this is off by default.",
    )
    parser.add_argument("--model", default=None, help="Override the model id.")
    parser.add_argument(
        "--warn",
        action="store_true",
        help="Load the model non-strictly: report OWNS/CONSUMES conflicts as warnings "
        "instead of refusing to load (DECISIONS.md D05).",
    )
    return parser


def render_model(graph) -> str:
    """The whole model, grouped for reading rather than for parsing.

    Elements first with their name, then relationships grouped by type. An
    element's degree is shown beside it because that is the thing you actually
    scan a model for: what is heavily connected, and what is isolated.
    """
    lines = [f"{graph!r}".strip("<>"), ""]

    for kind, collection in ELEMENT_COLLECTIONS.items():
        elements = graph.elements_of_kind(kind)
        lines.append(f"{collection.upper().replace('_', ' ')} ({len(elements)})")
        for element in elements:
            degree = len(graph.outgoing(element.id)) + len(graph.incoming(element.id))
            lifecycle = element.attributes.get("lifecycle")
            suffix = f"  [{lifecycle}]" if lifecycle else ""
            plural = "relationship" if degree == 1 else "relationships"
            note = "  <- isolated" if degree == 0 else ""
            lines.append(f"  {element.id}  {element.name}{suffix}  ({degree} {plural}){note}")
        lines.append("")

    by_type: dict[str, list] = {}
    for edge in graph.edges:
        by_type.setdefault(edge.type, []).append(edge)

    lines.append(f"RELATIONSHIPS ({len(graph.edges)})")
    for edge_type in RELATIONSHIP_ENDPOINTS:
        edges = sorted(by_type.get(edge_type, []), key=lambda e: (e.source, e.target))
        lines.append(f"\n  {edge_type} ({len(edges)})")
        for edge in edges:
            lines.append(
                f"    {edge.source} -> {edge.target}"
                f"    {graph.name(edge.source)} -> {graph.name(edge.target)}"
            )
    return "\n".join(lines)


def render_element(graph, element_id: str) -> str:
    """One element and its immediate neighbourhood, both directions.

    Direction matters and is easy to lose: A05 *owns* D05, and A01 *depends on*
    A05. Reading those off one flat edge list is where mistakes come from, so
    outgoing and incoming are separated and each line says which way it runs.
    """
    element = graph.element(element_id)
    lines = [f"{element.id} — {element.name}  ({element.kind})"]
    for key, value in element.attributes.items():
        lines.append(f"  {key}: {value}")

    for label, edges, other, arrow in (
        ("OUTGOING — this element points at", graph.outgoing(element.id), "target", "->"),
        ("INCOMING — these point at this element", graph.incoming(element.id), "source", "<-"),
    ):
        lines.append(f"\n  {label}")
        listed = sorted(edges, key=lambda e: (e.type, getattr(e, other)))
        if not listed:
            lines.append("    (none)")
        for edge in listed:
            neighbour = getattr(edge, other)
            lines.append(
                f"    {edge.type:<11} {arrow} {neighbour}  {graph.name(neighbour)}"
            )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not any((args.question, args.impact, args.list, args.show)):
        build_parser().print_help()
        return 2

    try:
        graph = load_graph(strict=not args.warn)
    except GraphValidationError as error:
        print(error, file=sys.stderr)
        return 1
    for warning in graph.warnings:
        print(f"warning: {warning}", file=sys.stderr)

    if args.list:
        if args.json:
            print(json.dumps(
                {
                    "elements": [
                        {"id": e.id, "name": e.name, "kind": e.kind, **dict(e.attributes)}
                        for kind in ELEMENT_COLLECTIONS
                        for e in graph.elements_of_kind(kind)
                    ],
                    "relationships": [edge.as_dict() for edge in graph.edges],
                },
                indent=2,
            ))
        else:
            print(render_model(graph))
        return 0

    if args.show:
        try:
            print(render_element(graph, args.show))
        except KeyError as error:
            print(str(error).strip("'"), file=sys.stderr)
            return 1
        return 0

    if args.impact:
        try:
            report = impact_of_retiring(graph, args.impact)
        except KeyError as error:
            print(str(error).strip("'"), file=sys.stderr)
            return 1
        print(json.dumps(report.as_dict(), indent=2) if args.json else report.render())
        return 0

    analyst = Analyst(
        graph=graph,
        retriever=KeywordRetriever.from_corpus(DEFAULT_CORPUS_ROOT),
        **({"model": args.model} if args.model else {}),
    )
    try:
        answer = analyst.ask(args.question)
    except ConfigurationError as error:
        print(error, file=sys.stderr)
        return 2

    if args.json:
        print(
            json.dumps(
                {
                    "question": answer.question,
                    "answer": answer.text,
                    "sources": answer.sources,
                    "tool_calls": [
                        {"tool": c.name, "arguments": c.arguments, "result": c.result, "error": c.error}
                        for c in answer.calls
                    ],
                    "usage": {
                        "input_tokens": answer.input_tokens,
                        "output_tokens": answer.output_tokens,
                    },
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(answer.render(evidence=not args.no_evidence))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
