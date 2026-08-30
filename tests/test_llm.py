"""The LLM layer — SPEC.md step 6, tested without an API key.

What is testable here without calling the model is the half that matters most:
that this code, not the model, executes the tools; that a bad argument comes
back as something the model can correct rather than a crash; and that the loop
terminates. The model's own judgement — does it pick the right tool, does it
refuse when it should — is not unit-testable and is measured in
``eval/run_eval.py --llm`` instead.

The client is stubbed with scripted responses shaped like the SDK's, so no
network call and no key are involved.

    python3 -m unittest discover -s tests -t .
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.graph import load_graph  # noqa: E402
from src.llm import MAX_TURNS, Analyst, load_env  # noqa: E402
from src.retrieval import KeywordRetriever  # noqa: E402


class Block:
    """A content block, quacking like the SDK's."""

    def __init__(self, **fields):
        self.__dict__.update(fields)


def text_block(text: str) -> Block:
    return Block(type="text", text=text)


def tool_block(name: str, arguments: dict, id: str = "tu_1") -> Block:
    return Block(type="tool_use", name=name, input=arguments, id=id)


class Response:
    def __init__(self, content, stop_reason="end_turn"):
        self.content = content
        self.stop_reason = stop_reason
        self.usage = Block(input_tokens=10, output_tokens=5)


class StubClient:
    """Returns scripted responses and records what it was sent."""

    def __init__(self, *responses):
        self._responses = list(responses)
        self.requests: list[dict] = []
        self.messages = self

    def create(self, **kwargs):
        self.requests.append(kwargs)
        if not self._responses:
            raise AssertionError("the loop asked for more responses than were scripted")
        return self._responses.pop(0)


def analyst(*responses) -> Analyst:
    return Analyst(
        graph=load_graph(),
        retriever=KeywordRetriever.from_corpus(),
        client=StubClient(*responses),
    )


class ToolDefinitionTests(unittest.TestCase):
    """The schemas handed to the model."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.analyst = analyst()

    def test_every_tool_is_well_formed(self):
        for spec in self.analyst.tools:
            with self.subTest(tool=spec.name):
                definition = spec.definition()
                self.assertTrue(definition["description"].strip())
                schema = definition["input_schema"]
                self.assertEqual("object", schema["type"])
                self.assertFalse(schema["additionalProperties"])
                for required in schema["required"]:
                    self.assertIn(required, schema["properties"])

    def test_the_schemas_are_json_serialisable(self):
        json.dumps([spec.definition() for spec in self.analyst.tools])

    def test_the_semantics_are_stated_where_the_model_will_read_them(self):
        """The OWNS/CONSUMES distinction has to be in the tool descriptions.

        A correct answer depends on the model not treating consumed data as
        impacted, and the description is where it learns that.
        """
        by_name = {spec.name: spec.description for spec in self.analyst.tools}
        self.assertIn("not orphan", by_name["consumed_data"].lower())
        self.assertIn("owns only", by_name["orphaned_data_if_retired"].lower())


class LoopTests(unittest.TestCase):
    """Who executes the tools, and what the caller gets back."""

    def test_this_code_executes_the_tool_not_the_model(self):
        subject = analyst(
            Response(
                [tool_block("orphaned_data_if_retired", {"application_id": "A05"})],
                stop_reason="tool_use",
            ),
            Response([text_block("D05 is orphaned (A05 -OWNS-> D05).")]),
        )
        answer = subject.ask("What is orphaned if A05 retires?")

        self.assertEqual(1, len(answer.calls))
        call = answer.calls[0]
        self.assertIsNone(call.error)
        self.assertEqual(["D05"], [entry["id"] for entry in call.result])
        # The result the model saw came from tools.py, edges and all.
        self.assertEqual(
            [{"from": "A05", "type": "OWNS", "to": "D05"}], call.result[0]["path"]
        )
        self.assertIn("D05", answer.text)

    def test_the_tool_result_is_sent_back_as_a_tool_result_block(self):
        subject = analyst(
            Response([tool_block("owned_data", {"application_id": "A05"}, id="tu_x")], "tool_use"),
            Response([text_block("done")]),
        )
        subject.ask("what does A05 own?")

        second = subject._client.requests[1]["messages"]
        self.assertEqual("assistant", second[1]["role"])
        result = second[2]["content"][0]
        self.assertEqual("tool_result", result["type"])
        self.assertEqual("tu_x", result["tool_use_id"])
        self.assertNotIn("is_error", result)

    def test_a_bad_id_comes_back_as_a_correctable_error(self):
        """An unknown id is usually a wrong guess at a name, not a dead end."""
        subject = analyst(
            Response([tool_block("owned_data", {"application_id": "A99"})], "tool_use"),
            Response([tool_block("find_elements", {"query": "platform"})], "tool_use"),
            Response([text_block("You probably mean A05.")]),
        )
        answer = subject.ask("what does A99 own?")

        self.assertIsNotNone(answer.calls[0].error)
        self.assertIn("A99", answer.calls[0].error)
        result = subject._client.requests[1]["messages"][2]["content"][0]
        self.assertTrue(result["is_error"])
        # The loop kept going and the model got a second chance.
        self.assertEqual("find_elements", answer.calls[1].name)
        self.assertIn("A05", answer.text)

    def test_an_unknown_tool_name_does_not_crash_the_loop(self):
        subject = analyst(
            Response([tool_block("estimate_cost", {"application_id": "A02"})], "tool_use"),
            Response([text_block("There is no cost information in this repository.")]),
        )
        answer = subject.ask("what would A02 cost to replace?")
        self.assertIn("no such tool", answer.calls[0].error)

    def test_parallel_tool_calls_are_answered_in_one_message(self):
        subject = analyst(
            Response(
                [
                    tool_block("owned_data", {"application_id": "A05"}, id="tu_1"),
                    tool_block("consumed_data", {"application_id": "A05"}, id="tu_2"),
                ],
                stop_reason="tool_use",
            ),
            Response([text_block("A05 owns D05 and consumes D01, D02, D03.")]),
        )
        answer = subject.ask("what data does A05 touch?")

        self.assertEqual(2, len(answer.calls))
        results = subject._client.requests[1]["messages"][2]["content"]
        self.assertEqual(["tu_1", "tu_2"], [r["tool_use_id"] for r in results])

    def test_the_loop_stops_rather_than_spinning(self):
        forever = [
            Response([tool_block("owned_data", {"application_id": "A05"})], "tool_use")
            for _ in range(MAX_TURNS)
        ]
        answer = analyst(*forever).ask("loop forever")
        self.assertEqual(MAX_TURNS, len(answer.calls))
        self.assertIn("Stopped after", answer.text)

    def test_an_answer_with_no_tool_calls_says_so_in_the_evidence(self):
        answer = analyst(Response([text_block("I think it is fine.")])).ask("is it fine?")
        self.assertEqual([], answer.calls)
        self.assertIn("Nothing in this answer is backed by the repository", answer.render())

    def test_sources_are_collected_from_retrieval_calls(self):
        subject = analyst(
            Response([tool_block("search_documents", {"query": "AI-assisted service"})], "tool_use"),
            Response([text_block("P03 applies.")]),
        )
        answer = subject.ask("which principle applies to an AI-assisted service?")
        self.assertIn("principles/P03-human-accountability.md", answer.sources)


class EnvTests(unittest.TestCase):
    def test_an_exported_key_is_not_overwritten_by_the_file(self):
        env_file = Path(self.enterContext(__import__("tempfile").TemporaryDirectory())) / ".env"
        env_file.write_text("ANTHROPIC_API_KEY=from-file\n", encoding="utf-8")
        os.environ["ANTHROPIC_API_KEY"] = "from-environment"
        self.addCleanup(os.environ.pop, "ANTHROPIC_API_KEY", None)

        load_env(env_file)
        self.assertEqual("from-environment", os.environ["ANTHROPIC_API_KEY"])

    def test_comments_and_blank_lines_are_ignored(self):
        env_file = Path(self.enterContext(__import__("tempfile").TemporaryDirectory())) / ".env"
        env_file.write_text("# a comment\n\nEA_TEST_KEY='quoted value'\n", encoding="utf-8")
        self.addCleanup(os.environ.pop, "EA_TEST_KEY", None)

        load_env(env_file)
        self.assertEqual("quoted value", os.environ["EA_TEST_KEY"])

    def test_a_missing_file_is_not_an_error(self):
        load_env(Path("/nonexistent/.env"))


if __name__ == "__main__":
    unittest.main()
