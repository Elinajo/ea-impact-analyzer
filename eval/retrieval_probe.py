"""Where the keyword retriever stops working — a diagnostic, not a test.

Q09 and Q10 both pass, and both pass at rank 1. That is a weaker result than it
looks, because both questions happen to share vocabulary with the document they
should find: Q09 says "AI-assisted service" and P03's *Applies to* section says
"AI-assisted service"; Q10 says "shared data platform" and that is the title of
ADR-002.

These probes ask the same things in words the documents do not use. They are not
part of the eval set and nothing here is scored — the eval set is fixed and is
not extended to make a point. Run it to see the shape of the failure, and to
have something concrete to point at when asked whether the retrieval is any
good.

    python3 eval/retrieval_probe.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.retrieval import KeywordRetriever  # noqa: E402

#: (question, the document a reader would expect, why it is interesting)
PROBES = [
    (
        "Which architecture principle applies to introducing a new AI-assisted service?",
        "principles/P03-human-accountability.md",
        "Q09 itself. Shares 'AI-assisted service' with the document verbatim.",
    ),
    (
        "Do we need a person to sign off on automated advice?",
        "principles/P03-human-accountability.md",
        "Same question, no shared noun phrase. 'accountability' never appears.",
    ),
    (
        "Who signs off when a tool proposes a change?",
        "principles/P03-human-accountability.md",
        "Only 'proposes' overlaps. Scores collapse but the ranking survives.",
    ),
    (
        "Has any prior decision been recorded about replacing a shared data platform?",
        "adrs/ADR-002-shared-data-platform.md",
        "Q10 itself. 'shared data platform' is the document's title.",
    ),
    (
        "Why is everything coupled to the operational data platform?",
        "adrs/ADR-002-shared-data-platform.md",
        "Different words, same subject. 'coupling' is in Consequences.",
    ),
    (
        "What rule governs who is the master system for a dataset?",
        "principles/P01-authoritative-sources.md",
        "'master system' and 'dataset' for 'authoritative source' and 'data object'.",
    ),
    (
        "How should systems talk to each other?",
        "principles/P02-standard-interfaces.md",
        "Plain English for 'standard interfaces'. No shared content word at all.",
    ),
]

TOP_K = 3


def main() -> int:
    retriever = KeywordRetriever.from_corpus()
    hits = 0
    for question, expected, note in PROBES:
        results = retriever.search(question, k=TOP_K)
        retrieved = [result.source for result in results]
        found = expected in retrieved
        hits += found
        print(f"\n{'HIT ' if found else 'MISS'}  {question}")
        print(f"      expect {expected}")
        print(f"      {note}")
        for result in results:
            print(f"      {result.score:6.2f}  {result.source}  [{result.chunk.heading}]")
        if not results:
            print("      (nothing scored above zero)")
    print(f"\n{hits}/{len(PROBES)} probes put the expected document in the top {TOP_K}.")
    print(
        "The misses are vocabulary mismatch, not ranking error: BM25 cannot match\n"
        "'master system' to 'authoritative source'. That is the case a vector index\n"
        "would answer, and the measured reason to add one — see DECISIONS.md D07."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
