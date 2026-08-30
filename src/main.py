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

from .graph import GraphValidationError, load_graph
from .llm import Analyst, MissingAPIKey
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.question and not args.impact:
        build_parser().print_help()
        return 2

    try:
        graph = load_graph(strict=not args.warn)
    except GraphValidationError as error:
        print(error, file=sys.stderr)
        return 1
    for warning in graph.warnings:
        print(f"warning: {warning}", file=sys.stderr)

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
    except MissingAPIKey as error:
        print(error, file=sys.stderr)
        print(
            "\nThe deterministic layer needs no key: try --impact A05, or "
            "python3 eval/run_eval.py",
            file=sys.stderr,
        )
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
