"""Tests for the retrieval layer — SPEC.md step 5.

Two kinds of test live here:

* Chunker behaviour, against inline fixtures. Deterministic and independent of
  what the corpus says, so these run today.
* Q09 and Q10 from the eval set. These need the prose corpus to be written;
  while a document is still an empty stub they *skip* with a message naming the
  file, rather than passing vacuously or being deleted.

    python3 -m unittest discover -s tests -t . -v
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.retrieval import (  # noqa: E402
    DEFAULT_CORPUS_ROOT,
    KeywordRetriever,
    chunk_markdown,
    load_corpus,
    tokenize,
)

QUESTIONS_PATH = REPO_ROOT / "eval" / "questions.json"
TOP_K = 3


def _retrieval_questions() -> dict[str, dict]:
    with open(QUESTIONS_PATH, encoding="utf-8") as handle:
        questions = json.load(handle)["questions"]
    return {q["id"]: q for q in questions if q["type"] == "retrieval"}


SAMPLE = """# ADR-002 — Shared data platform

Preamble prose before any subheading.

## Context
<!-- an editorial note that must not be indexed -->
Operational data was distributed point to point.

## Decision
Consolidate distribution into a shared platform.

### Scope
Operational events only.

## Consequences

```
# not a heading, it is inside a fence
```

Coupling on the platform increased.
"""


class ChunkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.chunks = chunk_markdown(SAMPLE, "adrs/ADR-002-shared-data-platform.md")
        self.by_heading = {chunk.heading: chunk for chunk in self.chunks}

    def test_splits_on_headings(self):
        self.assertEqual(
            ["ADR-002 — Shared data platform", "Context", "Decision", "Scope", "Consequences"],
            [chunk.heading for chunk in self.chunks],
        )

    def test_heading_path_records_nesting(self):
        self.assertEqual(
            ("ADR-002 — Shared data platform", "Decision", "Scope"),
            self.by_heading["Scope"].heading_path,
        )

    def test_preamble_stays_with_the_document_heading(self):
        self.assertIn("Preamble prose", self.by_heading["ADR-002 — Shared data platform"].body)

    def test_html_comments_are_stripped(self):
        context = self.by_heading["Context"]
        self.assertNotIn("editorial note", context.body)
        self.assertIn("point to point", context.body)

    def test_headings_inside_code_fences_are_not_headings(self):
        consequences = self.by_heading["Consequences"]
        self.assertIn("not a heading", consequences.body)
        self.assertIn("Coupling on the platform", consequences.body)

    def test_every_chunk_carries_its_source_and_line_range(self):
        for chunk in self.chunks:
            with self.subTest(heading=chunk.heading):
                self.assertEqual("adrs/ADR-002-shared-data-platform.md", chunk.source)
                self.assertLessEqual(chunk.line_start, chunk.line_end)

    def test_tokenize_drops_stopwords_and_case(self):
        self.assertEqual(["shared", "data", "platform"], tokenize("The shared Data platform"))


class IndexTests(unittest.TestCase):
    def test_empty_sections_are_not_retrievable(self):
        chunks = chunk_markdown("# Doc\n\n## Written\nreal prose here\n\n## Unwritten\n", "p.md")
        retriever = KeywordRetriever(chunks)
        self.assertEqual(["Written"], [c.heading for c in retriever.indexed])
        self.assertIn("Unwritten", [c.heading for c in retriever.empty_sections])

    def test_an_empty_document_title_is_not_an_unwritten_section(self):
        """A `# Title` followed straight by `## Section` has an empty title chunk.

        That is formatting, not a gap. Counting it would make a finished corpus
        report as incomplete, which is the one thing this list exists to say.
        """
        chunks = chunk_markdown("# Doc\n\n## Written\nreal prose here\n", "p.md")
        retriever = KeywordRetriever(chunks)
        self.assertIn("Doc", [c.heading for c in retriever.empty_sections])
        self.assertEqual([], retriever.unwritten_sections)

    def test_a_genuinely_unwritten_section_is_still_reported(self):
        chunks = chunk_markdown("# Doc\n\n## Written\nprose\n\n## Unwritten\n", "p.md")
        retriever = KeywordRetriever(chunks)
        self.assertEqual(["Unwritten"], [c.heading for c in retriever.unwritten_sections])

    def test_search_returns_nothing_rather_than_padding(self):
        chunks = chunk_markdown("# Doc\n\n## Written\nreal prose here\n", "p.md")
        results = KeywordRetriever(chunks).search("entirely unrelated vocabulary", k=TOP_K)
        self.assertEqual([], results)

    def test_ranking_prefers_the_matching_section(self):
        chunks = chunk_markdown(
            "# Doc\n\n## Gateway\nexternal access routes through the gateway\n\n"
            "## Ownership\nevery data object has one authoritative source\n",
            "p.md",
        )
        results = KeywordRetriever(chunks).search("authoritative source for a data object")
        self.assertEqual("Ownership", results[0].chunk.heading)


class CorpusTests(unittest.TestCase):
    """The corpus on disk, as the eval set will cite it."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.chunks = load_corpus(DEFAULT_CORPUS_ROOT)
        cls.retriever = KeywordRetriever(cls.chunks)
        cls.questions = _retrieval_questions()

    def test_expected_sources_exist_with_the_citation_form_the_eval_set_uses(self):
        available = {chunk.source for chunk in self.chunks}
        for question_id, question in self.questions.items():
            for source in question["expected_sources"]:
                with self.subTest(question=question_id, source=source):
                    self.assertIn(source, available)

    def _assert_retrieves(self, question_id: str) -> None:
        question = self.questions[question_id]
        unwritten = sorted({chunk.source for chunk in self.retriever.unwritten_sections})
        if not self.retriever.indexed:
            self.skipTest(
                f"{question_id} needs the prose corpus; every section is still an empty "
                f"stub ({', '.join(unwritten)})"
            )
        results = self.retriever.search(question["question"], k=TOP_K)
        retrieved = [result.source for result in results]
        for source in question["expected_sources"]:
            self.assertIn(
                source,
                retrieved,
                f"{question_id}: expected {source} in top-{TOP_K}, got {retrieved or 'nothing'}",
            )

    def test_q09_principle_for_an_ai_assisted_service(self):
        self._assert_retrieves("Q09")

    def test_q10_prior_decision_about_a_shared_data_platform(self):
        self._assert_retrieves("Q10")


if __name__ == "__main__":
    unittest.main()
