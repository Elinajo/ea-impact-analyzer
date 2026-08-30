"""Q01-Q08 from eval/questions.json, asserted against the deterministic tools.

The expected answers are read from the eval file rather than copied into this
module, so the assertions are provably against the evaluation set and cannot
drift from it. These are computed answers: they are expected to match exactly.

Written for the standard library's unittest so the deterministic layer has no
test dependency; pytest collects TestCase classes too, if it gets added later.

    python3 -m unittest discover -s tests -t .
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.graph import Edge, load_graph  # noqa: E402
from src.tools import (  # noqa: E402
    applications_for_capability,
    capabilities_losing_all_support,
    capabilities_unaffected_by_retiring,
    consumers_without_ownership,
    direct_dependents,
    ids,
    impact_of_retiring,
    indirect_dependents,
    orphaned_data_if_retired,
    orphaned_technologies_if_retired,
)

QUESTIONS_PATH = REPO_ROOT / "eval" / "questions.json"

# Element ids referenced by the questions, resolved by hand from their names:
# Q01 "Network Capacity Management" -> C01, Q02-Q06/Q08 "Operational Data
# Platform" -> A05, Q07 "Flight Data" -> D01.
C_NETWORK_CAPACITY = "C01"
A_OPERATIONAL_DATA_PLATFORM = "A05"
D_FLIGHT_DATA = "D01"


def _expected() -> dict[str, list[str]]:
    with open(QUESTIONS_PATH, encoding="utf-8") as handle:
        questions = json.load(handle)["questions"]
    return {q["id"]: q["expected_answer"] for q in questions if q["type"] == "graph"}


class GraphQuestionTests(unittest.TestCase):
    """One test per graph question in the eval set."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.graph = load_graph()
        cls.expected = _expected()

    # -- helpers ---------------------------------------------------------

    def assertAnswers(self, question_id: str, findings) -> None:
        """The finding ids match the eval set's expected answer, in sorted order."""
        self.assertEqual(sorted(self.expected[question_id]), ids(findings), question_id)

    def assertEvidenced(self, findings) -> None:
        """Every finding carries a path of relationships that are really in the model."""
        model_edges = set(self.graph.edges)
        for finding in findings:
            self.assertTrue(finding.path, f"{finding.id} has no relationship path")
            for edge in finding.path:
                self.assertIsInstance(edge, Edge)
                self.assertIn(edge, model_edges, f"{edge} is not a relationship in the model")

    # -- questions -------------------------------------------------------

    def test_q01_applications_supporting_network_capacity_management(self):
        findings = applications_for_capability(self.graph, C_NETWORK_CAPACITY)
        self.assertAnswers("Q01", findings)
        self.assertEvidenced(findings)

    def test_q02_applications_depending_directly_on_the_platform(self):
        findings = direct_dependents(self.graph, A_OPERATIONAL_DATA_PLATFORM)
        self.assertAnswers("Q02", findings)
        self.assertEvidenced(findings)
        self.assertTrue(all(f.depth == 1 for f in findings))

    def test_q03_data_objects_losing_their_authoritative_source(self):
        findings = orphaned_data_if_retired(self.graph, A_OPERATIONAL_DATA_PLATFORM)
        self.assertAnswers("Q03", findings)
        self.assertEvidenced(findings)
        # The distinction under test: consumed data is not orphaned.
        self.assertEqual(["OWNS"], sorted({e.type for f in findings for e in f.path}))
        for consumed in ("D01", "D02", "D03"):
            self.assertNotIn(consumed, ids(findings))

    def test_q04_capabilities_losing_all_support(self):
        findings = capabilities_losing_all_support(self.graph, A_OPERATIONAL_DATA_PLATFORM)
        self.assertAnswers("Q04", findings)
        self.assertEvidenced(findings)
        # C03 is degraded, not unsupported: it must not appear here.
        self.assertNotIn("C03", ids(findings))

    def test_q05_applications_indirectly_affected(self):
        findings = indirect_dependents(self.graph, A_OPERATIONAL_DATA_PLATFORM)
        self.assertAnswers("Q05", findings)
        self.assertEvidenced(findings)
        self.assertTrue(all(f.depth >= 2 for f in findings))

    def test_q06_technologies_left_with_no_applications(self):
        findings = orphaned_technologies_if_retired(self.graph, A_OPERATIONAL_DATA_PLATFORM)
        self.assertAnswers("Q06", findings)
        self.assertEvidenced(findings)
        # T02 still carries A06, so it is not orphaned.
        self.assertNotIn("T02", ids(findings))

    def test_q07_applications_consuming_flight_data_without_owning_it(self):
        findings = consumers_without_ownership(self.graph, D_FLIGHT_DATA)
        self.assertAnswers("Q07", findings)
        self.assertEvidenced(findings)
        self.assertNotIn("A02", ids(findings))  # A02 owns D01

    def test_q08_capabilities_unaffected(self):
        findings = capabilities_unaffected_by_retiring(self.graph, A_OPERATIONAL_DATA_PLATFORM)
        self.assertAnswers("Q08", findings)
        self.assertEvidenced(findings)


class ImpactReportTests(unittest.TestCase):
    """The same answers must come out of the single structured result."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.graph = load_graph()
        cls.expected = _expected()
        cls.report = impact_of_retiring(cls.graph, A_OPERATIONAL_DATA_PLATFORM)

    def test_report_matches_the_individual_questions(self):
        for question_id, findings in (
            ("Q02", self.report.direct_dependents),
            ("Q03", self.report.orphaned_data_objects),
            ("Q04", self.report.capabilities_losing_all_support),
            ("Q05", self.report.indirect_dependents),
            ("Q06", self.report.orphaned_technologies),
            ("Q08", self.report.capabilities_unaffected),
        ):
            with self.subTest(question=question_id):
                self.assertEqual(sorted(self.expected[question_id]), ids(findings))

    def test_consumed_data_is_reported_as_unaffected(self):
        self.assertEqual(["D01", "D02", "D03"], ids(self.report.consumed_data_unaffected))
        self.assertEqual(
            ["CONSUMES"],
            sorted({e.type for f in self.report.consumed_data_unaffected for e in f.path}),
        )

    def test_render_gives_a_double_dependent_one_line_with_both_routes(self):
        """D06: A07 is direct *and* indirect. Two facts, one application.

        The lists stay non-disjoint — as_dict() still reports A07 in both, and
        Q02/Q05 both depend on that — but the rendered report must not invite a
        reader to count A07 twice.
        """
        lines = self.report.render().splitlines()
        a07 = [line for line in lines if line.strip().startswith("- A07")]
        self.assertEqual(1, len(a07), f"A07 should occupy one line, got {a07}")
        self.assertIn("direct and indirect", a07[0])

        routes = lines[lines.index(a07[0]) + 1 : lines.index(a07[0]) + 3]
        self.assertIn("· direct: A07 -DEPENDS_ON-> A05", routes[0])
        self.assertIn("A07 -DEPENDS_ON-> A01 ; A01 -DEPENDS_ON-> A05", routes[1])

        # A01 has only the one route and must not be dressed up as having two.
        a01 = next(line for line in lines if line.strip().startswith("- A01"))
        self.assertNotIn("indirect", a01)

    def test_every_entry_carries_a_relationship_path(self):
        for key, entries in self.report.as_dict().items():
            if key == "application":
                continue
            for entry in entries:
                with self.subTest(section=key, id=entry["id"]):
                    self.assertTrue(entry["path"], f"{entry['id']} in {key} has no path")


if __name__ == "__main__":
    unittest.main()
