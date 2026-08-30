"""Loader behaviour — SPEC.md step 1, plus the D05 decision.

The eval questions are covered in test_tools.py and test_retrieval.py. What is
tested here is the validation contract itself: which problems stop a load, and
which are reported without stopping it.

    python3 -m unittest discover -s tests -t .
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.graph import EAGraph, GraphValidationError, load_graph  # noqa: E402
from src.tools import ids, orphaned_data_if_retired  # noqa: E402


def model(**overrides) -> dict:
    """A minimal valid document: one application owning one data object."""
    document = {
        "applications": [{"id": "A01", "name": "Platform"}],
        "data_objects": [{"id": "D01", "name": "Events"}],
        "capabilities": [],
        "technologies": [],
        "relationships": [{"from": "A01", "type": "OWNS", "to": "D01"}],
    }
    document.update(overrides)
    return document


class StructuralValidationTests(unittest.TestCase):
    """Faults that leave nothing computable. These always raise."""

    def assertRejects(self, document: dict, fragment: str) -> None:
        for strict in (True, False):
            with self.subTest(strict=strict):
                with self.assertRaises(GraphValidationError) as caught:
                    EAGraph.from_dict(document, strict=strict)
                self.assertIn(fragment, "\n".join(caught.exception.errors))

    def test_missing_endpoint_is_rejected(self):
        self.assertRejects(
            model(relationships=[{"from": "A01", "type": "OWNS", "to": "D99"}]),
            "does not exist",
        )

    def test_endpoint_of_the_wrong_kind_is_rejected(self):
        self.assertRejects(
            model(relationships=[{"from": "A01", "type": "RUNS_ON", "to": "D01"}]),
            "requires a technology",
        )

    def test_unknown_relationship_type_is_rejected(self):
        self.assertRejects(
            model(relationships=[{"from": "A01", "type": "USES", "to": "D01"}]),
            "unknown relationship type",
        )

    def test_every_problem_is_reported_not_just_the_first(self):
        document = model(
            relationships=[
                {"from": "A01", "type": "OWNS", "to": "D98"},
                {"from": "A01", "type": "OWNS", "to": "D99"},
            ]
        )
        with self.assertRaises(GraphValidationError) as caught:
            EAGraph.from_dict(document)
        self.assertEqual(2, len(caught.exception.errors))


class OwnsAndConsumesTests(unittest.TestCase):
    """D05: an application that both OWNS and CONSUMES one data object."""

    CONFLICTED = model(
        relationships=[
            {"from": "A01", "type": "OWNS", "to": "D01"},
            {"from": "A01", "type": "CONSUMES", "to": "D01"},
        ]
    )

    def test_strict_refuses_the_combination(self):
        with self.assertRaises(GraphValidationError) as caught:
            EAGraph.from_dict(self.CONFLICTED, strict=True)
        self.assertIn("both OWNS and CONSUMES", "\n".join(caught.exception.errors))

    def test_strict_is_the_default(self):
        with self.assertRaises(GraphValidationError):
            EAGraph.from_dict(self.CONFLICTED)

    def test_non_strict_warns_and_still_loads(self):
        graph = EAGraph.from_dict(self.CONFLICTED, strict=False)
        self.assertEqual(1, len(graph.warnings))
        self.assertIn("both OWNS and CONSUMES", graph.warnings[0])

    def test_the_impact_answer_does_not_depend_on_the_reading(self):
        """The reason the combination is only a warning: it changes nothing.

        orphaned_data_if_retired works purely off OWNS, so D01 is orphaned
        either way. If this ever stops holding, D05 has to be reopened.
        """
        graph = EAGraph.from_dict(self.CONFLICTED, strict=False)
        self.assertEqual(["D01"], ids(orphaned_data_if_retired(graph, "A01")))

    def test_the_supplied_model_is_clean(self):
        self.assertEqual((), load_graph(strict=False).warnings)


if __name__ == "__main__":
    unittest.main()
