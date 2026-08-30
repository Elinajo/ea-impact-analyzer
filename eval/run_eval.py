"""Run the twelve evaluation questions and print a score table — SPEC.md step 8.

Two modes, because they measure different things and mixing them would hide
which layer failed.

*Deterministic* (default, no API key needed) scores the layers that can be
scored exactly: graph questions against the tools in ``src/tools.py``, retrieval
questions against the keyword index. These are computed answers and the score is
the score.

*End-to-end* (``--llm``) puts every question through ``src/llm.py`` — model
picks a tool, this code runs it, model explains. Scoring there is necessarily
looser and each heuristic is named in the output, because what is being checked
is a paragraph of English rather than a set of ids. Treat it as a screen, not a
verdict; the answers are printed in full with ``--show`` so they can be read.

    python3 eval/run_eval.py
    python3 eval/run_eval.py --llm --show

Expected answers in questions.json are never adjusted to match output. Where the
system and the eval set disagree, the disagreement is the finding.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.graph import load_graph  # noqa: E402
from src.retrieval import DEFAULT_CORPUS_ROOT, KeywordRetriever  # noqa: E402
from src.tools import (  # noqa: E402
    applications_for_capability,
    capabilities_losing_all_support,
    capabilities_unaffected_by_retiring,
    consumers_without_ownership,
    direct_dependents,
    ids,
    indirect_dependents,
    orphaned_data_if_retired,
    orphaned_technologies_if_retired,
)

QUESTIONS_PATH = REPO_ROOT / "eval" / "questions.json"
TOP_K = 3
ELEMENT_ID = re.compile(r"\b([ACDT]0[1-9])\b")

#: Which tool answers which graph question, and with what argument. Resolved by
#: hand from the question text — the mapping the LLM layer has to work out for
#: itself is fixed here, so the deterministic score measures the tools and not
#: the model's tool choice.
GRAPH_PLAN = {
    "Q01": (applications_for_capability, "C01"),
    "Q02": (direct_dependents, "A05"),
    "Q03": (orphaned_data_if_retired, "A05"),
    "Q04": (capabilities_losing_all_support, "A05"),
    "Q05": (indirect_dependents, "A05"),
    "Q06": (orphaned_technologies_if_retired, "A05"),
    "Q07": (consumers_without_ownership, "D01"),
    "Q08": (capabilities_unaffected_by_retiring, "A05"),
}

#: Words that mark an answer as declining rather than answering. Deliberately
#: about *epistemic* language, not about the topic.
REFUSAL_MARKERS = (
    "cannot", "can not", "can't", "not derivable", "not represented", "no information",
    "not recorded", "does not contain", "doesn't contain", "not in the model",
    "unable to", "not something", "no basis",
)
#: Phrases that would mean the model gave the verdict it was supposed to withhold.
VERDICT_MARKERS = ("yes, ", "no, ", "it is safe", "it would be safe", "safe to retire")


@dataclass
class Result:
    question_id: str
    kind: str
    passed: bool | None  # None = not run
    detail: str

    @property
    def mark(self) -> str:
        return {True: "PASS", False: "FAIL", None: "----"}[self.passed]


def questions() -> list[dict]:
    with open(QUESTIONS_PATH, encoding="utf-8") as handle:
        return json.load(handle)["questions"]


# ------------------------------------------------------------- deterministic


def score_graph(question: dict, graph) -> Result:
    tool, argument = GRAPH_PLAN[question["id"]]
    got = ids(tool(graph, argument))
    expected = sorted(question["expected_answer"])
    return Result(
        question["id"],
        "graph",
        got == expected,
        f"expected {expected}, got {got}",
    )


def score_retrieval(question: dict, retriever: KeywordRetriever) -> Result:
    results = retriever.search(question["question"], k=TOP_K)
    retrieved = [result.source for result in results]
    missing = [s for s in question["expected_sources"] if s not in retrieved]
    rank = {s: retrieved.index(s) + 1 for s in question["expected_sources"] if s in retrieved}
    detail = f"top-{TOP_K}: {retrieved or 'nothing'}"
    if rank:
        detail += f"; expected source at rank {min(rank.values())}"
    return Result(question["id"], "retrieval", not missing, detail)


# --------------------------------------------------------------- end-to-end


def score_llm(question: dict, answer) -> Result:
    """Score one end-to-end answer. Every check here is a heuristic over English
    and is named as such in the detail, so a reader knows what was actually
    tested."""
    text = answer.text.lower()
    kind = question["type"]

    if kind == "graph":
        mentioned = sorted(set(ELEMENT_ID.findall(answer.text)))
        expected = sorted(question["expected_answer"])
        # Loose by construction: an id mentioned in passing ("unlike A02, which
        # owns D01") counts as mentioned. A pass here means the right ids are
        # present, not that nothing else was claimed.
        hit = all(e in mentioned for e in expected)
        return Result(question["id"], "graph/llm", hit, f"expected {expected}, ids in answer {mentioned}")

    if kind == "retrieval":
        cited = answer.sources
        missing = [s for s in question["expected_sources"] if s not in cited]
        return Result(question["id"], "retrieval/llm", not missing, f"retrieved {cited or 'nothing'}")

    declined = any(marker in text for marker in REFUSAL_MARKERS)
    verdict = any(marker in text for marker in VERDICT_MARKERS)
    named_gap = any(
        word in text
        for word in ("service level", "transition", "migration", "risk assessment", "cost", "not represented")
    )
    passed = declined and not verdict
    detail = (
        f"declined={declined}, names missing information={named_gap}, "
        f"reads as a verdict={verdict} — heuristic, read the answer to confirm"
    )
    return Result(question["id"], "refusal/llm", passed, detail)


# -------------------------------------------------------------------- output


def print_table(results: list[Result]) -> None:
    width = max(len(r.kind) for r in results)
    print(f"\n{'Q':<5}{'type':<{width + 2}}{'result':<8}detail")
    print("-" * 100)
    for result in results:
        print(f"{result.question_id:<5}{result.kind:<{width + 2}}{result.mark:<8}{result.detail}")

    run = [r for r in results if r.passed is not None]
    passed = [r for r in run if r.passed]
    print("-" * 100)
    print(f"{len(passed)}/{len(run)} scored questions pass ({len(results) - len(run)} not run).")
    failures = [r for r in run if not r.passed]
    if failures:
        print("Failing: " + ", ".join(f"{r.question_id} ({r.kind})" for r in failures))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--llm", action="store_true", help="Also run every question end to end.")
    parser.add_argument("--show", action="store_true", help="Print each end-to-end answer in full.")
    args = parser.parse_args(argv)

    graph = load_graph()
    retriever = KeywordRetriever.from_corpus(DEFAULT_CORPUS_ROOT)
    if retriever.unwritten_sections:
        unwritten = sorted({chunk.source for chunk in retriever.unwritten_sections})
        print(f"note: {len(retriever.unwritten_sections)} unwritten section(s) in {unwritten}")

    results: list[Result] = []
    for question in questions():
        kind = question["type"]
        if kind == "graph":
            results.append(score_graph(question, graph))
        elif kind == "retrieval":
            results.append(score_retrieval(question, retriever))
        else:
            results.append(
                Result(question["id"], "refusal", None, "needs the LLM layer: rerun with --llm")
            )

    print("\n=== deterministic layer (tools + keyword index, no model) ===")
    print_table(results)

    if not args.llm:
        return 0

    from src.llm import Analyst, ConfigurationError  # noqa: E402

    try:
        analyst = Analyst(graph=graph, retriever=retriever)
        analyst.client  # fail fast on configuration, before spending a request
    except ConfigurationError as error:
        print(f"\n--llm not run: {error}", file=sys.stderr)
        return 2

    end_to_end: list[Result] = []
    for question in questions():
        answer = analyst.ask(question["question"])
        end_to_end.append(score_llm(question, answer))
        if args.show:
            print(f"\n### {question['id']} — {question['question']}")
            print(answer.render())

    print("\n=== end to end (model chooses the tool, this code runs it) ===")
    print_table(end_to_end)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
