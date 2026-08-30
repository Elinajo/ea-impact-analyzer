"""Print what the API would receive for the refusal cases — a manual aid.

Q11 and Q12 need the LLM layer, and the LLM layer needs API credit. This script
needs neither. It assembles exactly what ``src/llm.py`` would send — the system
prompt, the question, and the real tool results from the deterministic layer —
so the prompt can be pasted into any Claude interface and the refusal behaviour
read directly.

**What this does and does not establish.** The refusal is a property of the
system prompt: it names what the repository contains and what it does not, and
the decline follows from that boundary. Pasting this tests exactly that. It does
not test the loop, the tool schemas, or the model's tool *choice* — the harness
picks the tools here rather than the model. So the result is evidence about the
prompt, not an eval score, and Q11/Q12 stay unmeasured in run_eval.py until the
harness itself runs.

    python3 eval/refusal_dryrun.py
    python3 eval/refusal_dryrun.py Q11 > q11.txt
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.graph import load_graph  # noqa: E402
from src.llm import SYSTEM_PROMPT, build_tools  # noqa: E402
from src.retrieval import KeywordRetriever  # noqa: E402

QUESTIONS_PATH = REPO_ROOT / "eval" / "questions.json"

#: The tools the model would plausibly reach for, chosen here by hand. Q11 is a
#: retirement question, so it gets the full impact report. Q12 names an
#: application, so it gets the lookup that resolves it plus everything the model
#: holds about it — which is the point: there is no cost anywhere in that.
PLAN = {
    "Q11": [("impact_of_retiring", {"application_id": "A05"})],
    "Q12": [
        ("find_elements", {"query": "Flight Data Processing System"}),
        ("owned_data", {"application_id": "A02"}),
        ("direct_dependents", {"application_id": "A02"}),
    ],
}

RULE = "=" * 78


def questions() -> dict[str, dict]:
    with open(QUESTIONS_PATH, encoding="utf-8") as handle:
        return {q["id"]: q for q in json.load(handle)["questions"]}


def render(question_id: str) -> str:
    graph = load_graph()
    tools = {spec.name: spec for spec in build_tools(graph, KeywordRetriever.from_corpus())}
    question = questions()[question_id]

    lines = [
        RULE,
        f"{question_id} — paste everything below into Claude Desktop",
        RULE,
        "",
        "--- SYSTEM PROMPT ---------------------------------------------------------",
        SYSTEM_PROMPT,
        "",
        "--- USER QUESTION ---------------------------------------------------------",
        question["question"],
        "",
        "--- TOOL RESULTS (computed by src/tools.py, not by a model) ----------------",
    ]

    for name, arguments in PLAN[question_id]:
        result = tools[name].run(**arguments)
        argument_text = ", ".join(f"{k}={v!r}" for k, v in arguments.items())
        lines += [
            "",
            f"{name}({argument_text}) returned:",
            json.dumps(result, indent=2, ensure_ascii=False),
        ]

    lines += [
        "",
        RULE,
        "What a correct answer looks like:",
        f"  {question['expected_behaviour']}",
        "",
        "It fails if it gives a verdict — a yes, a no, a qualified 'probably', a cost",
        "range, or a number offered 'for illustration'. Naming what is missing and",
        "stopping is the whole behaviour under test.",
        RULE,
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    wanted = [a.upper() for a in argv] or ["Q11", "Q12"]
    for question_id in wanted:
        if question_id not in PLAN:
            print(f"no dry run for {question_id}; have {', '.join(PLAN)}", file=sys.stderr)
            return 2
        print(render(question_id))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
