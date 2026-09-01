"""The model views in src/main.py — SPEC.md step 7.

These are presentation, so what is worth asserting is that nothing is silently
dropped and that direction survives. A view that quietly omits an element, or
that renders `A05 OWNS D05` in a way you could read as `D05 OWNS A05`, is worse
than no view: it looks authoritative and is wrong.

    python3 -m unittest discover -s tests -t .
"""

from __future__ import annotations

import contextlib
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.graph import ELEMENT_COLLECTIONS, load_graph  # noqa: E402
from src.main import main, render_element, render_model  # noqa: E402


class ModelViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.graph = load_graph()
        cls.text = render_model(cls.graph)

    def test_every_element_is_listed(self):
        for kind in ELEMENT_COLLECTIONS:
            for element in self.graph.elements_of_kind(kind):
                with self.subTest(element=element.id):
                    self.assertIn(element.id, self.text)
                    self.assertIn(element.name, self.text)

    def test_every_relationship_is_listed(self):
        for edge in self.graph.edges:
            with self.subTest(edge=str(edge)):
                self.assertIn(f"{edge.source} -> {edge.target}", self.text)

    def test_the_counts_match_the_model(self):
        self.assertIn(f"RELATIONSHIPS ({len(self.graph.edges)})", self.text)
        self.assertIn(f"APPLICATIONS ({len(self.graph.elements_of_kind('application'))})", self.text)

    def test_an_unconnected_element_is_called_out(self):
        """T04 has no relationships in the supplied model. A reader scanning for
        what is heavily connected should also see what is connected to nothing."""
        line = next(l for l in self.text.splitlines() if l.strip().startswith("T04"))
        self.assertIn("0 relationships", line)
        self.assertIn("isolated", line)

    def test_singular_is_not_written_as_plural(self):
        self.assertNotIn("(1 relationships)", self.text)


class ElementViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.graph = load_graph()

    def test_direction_is_preserved_in_both_lists(self):
        text = render_element(self.graph, "A05")
        outgoing, incoming = text.split("INCOMING")

        # A05 owns D05 and runs on T03 — those point away from A05.
        self.assertIn("OWNS", outgoing)
        self.assertIn("D05", outgoing)
        self.assertIn("T03", outgoing)
        # A01, A06 and A07 depend on A05 — those point at it.
        for dependent in ("A01", "A06", "A07"):
            self.assertIn(dependent, incoming)
        self.assertNotIn("DEPENDS_ON", outgoing)

    def test_a_data_object_shows_its_owner_separately_from_its_consumers(self):
        text = render_element(self.graph, "D01")
        self.assertIn("OWNS        <- A02", text)
        self.assertIn("CONSUMES    <- A01", text)
        self.assertIn("CONSUMES    <- A05", text)

    def test_attributes_are_shown(self):
        self.assertIn("lifecycle: strategic", render_element(self.graph, "A05"))

    def test_an_isolated_element_renders_without_error(self):
        text = render_element(self.graph, "T04")
        self.assertEqual(2, text.count("(none)"))

    def test_an_unknown_id_raises(self):
        with self.assertRaises(KeyError):
            render_element(self.graph, "A99")


class ExitCodeTests(unittest.TestCase):
    """The CLI contract: a bad request is a non-zero exit, not a traceback."""

    def run_cli(self, argv: list[str]) -> int:
        """Run main() with its output swallowed, so a test run stays readable."""
        with open(os.devnull, "w", encoding="utf-8") as sink:
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                return main(argv)

    def test_list_and_show_succeed(self):
        self.assertEqual(0, self.run_cli(["--list"]))
        self.assertEqual(0, self.run_cli(["--show", "A05"]))
        self.assertEqual(0, self.run_cli(["--list", "--json"]))

    def test_an_unknown_id_exits_non_zero(self):
        self.assertEqual(1, self.run_cli(["--show", "A99"]))
        self.assertEqual(1, self.run_cli(["--impact", "A99"]))

    def test_no_arguments_prints_help_and_exits_non_zero(self):
        self.assertEqual(2, self.run_cli([]))


if __name__ == "__main__":
    unittest.main()
