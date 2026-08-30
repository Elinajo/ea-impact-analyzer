"""LLM layer — SPEC.md step 6.

The model interprets the question, selects a tool, and explains what comes
back. It does not produce architecture facts: every tool here is the
deterministic Python from ``tools.py`` or the keyword retriever from
``retrieval.py``, executed by this module, with the result handed to the model
as evidence. See DECISIONS.md D03.

The loop is written out rather than delegated to the SDK's tool runner. The
whole claim of the project is that the facts come from code and not from the
model, and a loop you can read is a loop you can point at when asked to show
that. DECISIONS.md D11.

Needs ``ANTHROPIC_API_KEY``, read from the environment or from a ``.env`` file
at the repository root. The key is never written into source.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import tools as t
from .graph import ELEMENT_COLLECTIONS, REPO_ROOT, EAGraph, UnknownElementError, load_graph
from .retrieval import DEFAULT_CORPUS_ROOT, KeywordRetriever

ELEMENT_KINDS = tuple(ELEMENT_COLLECTIONS)
#: An example id per kind, so the schema tells the model what an id looks like.
EXAMPLE_IDS = {
    "capability": "C01",
    "application": "A05",
    "data_object": "D01",
    "technology": "T02",
}

MODEL = "claude-opus-5"
MAX_TOKENS = 16000
#: A question needs a handful of lookups. More than this is a loop, not an
#: analysis, and the run is stopped rather than left to spend tokens.
MAX_TURNS = 12
TOP_K = 3

ENV_PATH = REPO_ROOT / ".env"


class ConfigurationError(RuntimeError):
    """Something the environment must supply is missing or wrong.

    Distinct from an API failure: nothing was sent, and no amount of retrying
    helps until a human changes a setting.
    """


class MissingAPIKey(ConfigurationError):
    """Raised when no API key is available, with the way to supply one."""


class WorkspaceRequired(ConfigurationError):
    """Raised when the key is identity-linked and needs a workspace id.

    The API rejects such a key with a 400 rather than an auth error, which
    reads like a bug in the request. It is not: it is a missing setting.
    """


def load_env(path: str | Path = ENV_PATH) -> None:
    """Read ``KEY=VALUE`` lines from a .env file into ``os.environ``.

    Twenty lines of standard library instead of a dependency on python-dotenv,
    which is the whole of what that package would be used for here. Values
    already present in the environment win, so an exported key is not silently
    overridden by a stale file.
    """
    path = Path(path)
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        os.environ.setdefault(key, value)


#: The value shipped in .env.example. Copying that file and forgetting to edit it
#: is the likely first mistake, and it would otherwise reach the API and come
#: back as an authentication error that says nothing about the real cause.
PLACEHOLDER_KEY = "sk-ant-..."


def api_key() -> str:
    load_env()
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key or key == PLACEHOLDER_KEY:
        problem = (
            "still holds the placeholder from .env.example"
            if key
            else "is not set"
        )
        raise MissingAPIKey(
            f"ANTHROPIC_API_KEY {problem}. Put a real key in {ENV_PATH} as\n"
            "    ANTHROPIC_API_KEY=sk-ant-your-key-here\n"
            "or export it in your shell. Get one at "
            "https://console.anthropic.com/settings/keys\n"
            ".env is git-ignored; the key is never stored in source or committed."
        )
    return key


def workspace_id() -> str | None:
    """The workspace an identity-linked key acts in, if one is configured.

    Personal API keys do not need this. Keys linked to an identity do: the API
    rejects them with a 400 until the ``anthropic-workspace-id`` header names
    the workspace. There is no SDK parameter for it, so it is sent as a header.
    """
    load_env()
    return os.environ.get("ANTHROPIC_WORKSPACE_ID", "").strip() or None


def _explain(error: Exception) -> Exception:
    """Turn the workspace 400 into an error that says what to change.

    Left as-is it reads as a malformed request, which sends you looking in the
    wrong place. Any other error is passed through untouched.
    """
    if "anthropic-workspace-id" not in str(error):
        return error
    return WorkspaceRequired(
        "This API key is identity-linked, so every request must name the workspace "
        "it acts in.\n"
        f"Add a line to {ENV_PATH}:\n"
        "    ANTHROPIC_WORKSPACE_ID=wrkspc_...\n"
        "Find the id at https://console.anthropic.com/settings/workspaces — open the "
        "workspace and take the id from the page URL.\n"
        "The deterministic layer needs neither key nor workspace: python3 -m src.main "
        "--impact A05 works regardless."
    )


# ----------------------------------------------------------------- the prompt

SYSTEM_PROMPT = """\
You are an enterprise architecture impact analyst. You answer questions about \
one specific architecture repository, using the tools provided.

EVIDENCE
Every factual claim you make must come from a tool result in this conversation. \
Cite it inline:
- for anything from the architecture model, the relationship path the tool \
returned, e.g. (A07 -DEPENDS_ON-> A01 ; A01 -DEPENDS_ON-> A05);
- for anything from a document, the source file, e.g. \
(adrs/ADR-002-shared-data-platform.md).
Never state a relationship you have not seen in a tool result. If you believe a \
relationship exists, call a tool and check. Do not fill gaps from general \
knowledge about air traffic management, enterprise architecture, or how systems \
like these usually work: this repository describes a fictional organisation and \
general knowledge about it is not evidence.

WHAT THE REPOSITORY CONTAINS
Applications, capabilities, data objects and technologies, connected by exactly \
five relationship types: SUPPORTS (application realises part of a capability), \
OWNS (application is the authoritative source for a data object), CONSUMES \
(application reads a data object it is not authoritative for), DEPENDS_ON \
(application requires another application), RUNS_ON (application runs on a \
technology). Applications carry a lifecycle attribute. Alongside the model there \
are three architecture principles and two decision records, as prose.

WHAT IT DOES NOT CONTAIN
No costs, budgets, effort or licence figures. No service levels, availability \
targets, performance or capacity data. No transition, migration or delivery \
plans. No operational risk assessments. No schedules, staffing or contracts. No \
incident history. Nothing about how well any of it works in practice.

So the repository answers questions about structure and dependency. It does not \
answer questions about safety, cost, duration or quality. When you are asked one \
of those, say plainly that it is not derivable from this repository, name the \
specific information that would be needed to answer it, and report the \
structural facts you can establish as what they are — dependencies, not a \
verdict. Do not estimate. Do not give a qualified yes or no. Do not offer an \
illustrative figure or a typical range. An answer more confident than the \
evidence supports is worse than no answer, because the reader cannot tell the \
difference.

RETIREMENT SEMANTICS — the distinction most often got wrong
Retiring an application orphans the data objects it OWNS: nothing is \
authoritative for them any more. Data it merely CONSUMES is unaffected — that \
data keeps its owner, and only the consumer loses access. Never report consumed \
data as impacted data.
A technology is orphaned only if the retired application was the last one \
running on it.
A capability loses all support only when the retired application was its only \
supporter. A capability whose supporting application merely depends on the \
retired one is degraded, which is a weaker and separate claim. Do not merge \
those two.

STYLE
Answer the question that was asked, briefly, then give the evidence. Say what \
you checked. If a tool returned nothing, say it returned nothing rather than \
concluding the thing does not exist — those differ when the question was \
ambiguous or an id was wrong.\
"""


# ------------------------------------------------------------------- the tools


def _findings(items) -> list[dict]:
    return [finding.as_dict() for finding in items]


@dataclass(frozen=True)
class ToolSpec:
    """One tool, as exposed to the model and as executed here."""

    name: str
    description: str
    schema: dict[str, Any]
    run: Callable[..., Any]

    def definition(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.schema,
        }


def _one_id(argument: str, kind: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            argument: {
                "type": "string",
                "description": f"Id of the {kind}, e.g. {EXAMPLE_IDS.get(kind, 'A05')}.",
            }
        },
        "required": [argument],
        "additionalProperties": False,
    }


def build_tools(graph: EAGraph, retriever: KeywordRetriever) -> list[ToolSpec]:
    """The tool surface offered to the model, bound to a graph and a corpus."""

    def find_elements(query: str, kind: str | None = None) -> list[dict]:
        needle = query.strip().lower()
        kinds = [kind] if kind else list(ELEMENT_KINDS)
        matches = [
            {
                "id": element.id,
                "name": element.name,
                "kind": element.kind,
                "attributes": dict(element.attributes),
            }
            for k in kinds
            for element in graph.elements_of_kind(k)
            if needle in element.name.lower() or needle == element.id.lower()
        ]
        return matches

    def list_elements(kind: str) -> list[dict]:
        return [
            {"id": e.id, "name": e.name, "attributes": dict(e.attributes)}
            for e in graph.elements_of_kind(kind)
        ]

    def search_documents(query: str, k: int = TOP_K) -> list[dict]:
        return [
            {
                "source": result.source,
                "section": result.chunk.breadcrumb,
                "lines": [result.chunk.line_start, result.chunk.line_end],
                "score": round(result.score, 3),
                "text": result.chunk.body,
            }
            for result in retriever.search(query, k=k)
        ]

    def impact(application_id: str) -> dict:
        return t.impact_of_retiring(graph, application_id).as_dict()

    specs: list[ToolSpec] = [
        ToolSpec(
            name="find_elements",
            description=(
                "Resolve a name or partial name to element ids. Use this first when the "
                "question names a system, capability, data object or technology in words "
                "rather than by id. Returns nothing if nothing matches."
            ),
            schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Name, part of a name, or an id."},
                    "kind": {
                        "type": "string",
                        "enum": list(ELEMENT_KINDS),
                        "description": "Optional: restrict to one kind of element.",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            run=find_elements,
        ),
        ToolSpec(
            name="list_elements",
            description="List every element of one kind, with its id and name.",
            schema={
                "type": "object",
                "properties": {"kind": {"type": "string", "enum": list(ELEMENT_KINDS)}},
                "required": ["kind"],
                "additionalProperties": False,
            },
            run=list_elements,
        ),
        ToolSpec(
            name="search_documents",
            description=(
                "Keyword search over the prose corpus: architecture principles and "
                "decision records. Returns matching sections with their source file, so "
                "the answer can cite them. Use for questions about principles, policy, "
                "rationale or prior decisions — not for relationships, which are in the "
                "model and must come from the model tools."
            ),
            schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "k": {"type": "integer", "description": f"How many sections. Default {TOP_K}."},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            run=search_documents,
        ),
        ToolSpec(
            name="impact_of_retiring",
            description=(
                "Full impact of retiring one application: dependent applications (direct "
                "and indirect), data objects left with no authoritative source, data it "
                "only consumes and which is therefore unaffected, capabilities losing all "
                "support, capabilities degraded, capabilities unaffected, and orphaned "
                "technologies. Every entry carries its relationship path. Prefer this "
                "over calling the narrower tools one at a time."
            ),
            schema=_one_id("application_id", "application"),
            run=impact,
        ),
    ]

    #: The narrower lookups. Same evidence, one question at a time — useful when
    #: the question asks for exactly one of them and the full report would bury
    #: the answer in eight other lists.
    narrow: list[tuple[str, str, str, Callable]] = [
        (
            "applications_for_capability",
            "capability_id",
            "Applications that support a capability (inbound SUPPORTS).",
            t.applications_for_capability,
        ),
        (
            "direct_dependents",
            "application_id",
            "Applications with a DEPENDS_ON edge straight to this one.",
            t.direct_dependents,
        ),
        (
            "indirect_dependents",
            "application_id",
            "Applications that reach this one only through an intermediary (two or more "
            "hops). An application can be both direct and indirect — those are two facts "
            "about one application, not two applications.",
            t.indirect_dependents,
        ),
        (
            "transitive_dependents",
            "application_id",
            "Every application that reaches this one through DEPENDS_ON at any depth, "
            "direct dependents included.",
            t.transitive_dependents,
        ),
        (
            "owned_data",
            "application_id",
            "Data objects this application is the authoritative source for (OWNS).",
            t.owned_data,
        ),
        (
            "consumed_data",
            "application_id",
            "Data objects this application reads but is not authoritative for (CONSUMES). "
            "Retiring this application does NOT orphan these.",
            t.consumed_data,
        ),
        (
            "consumers_without_ownership",
            "data_object_id",
            "Applications that consume a data object without owning it.",
            t.consumers_without_ownership,
        ),
        (
            "orphaned_data_if_retired",
            "application_id",
            "Data objects that would be left with no authoritative source if this "
            "application were retired. OWNS only — consumed data is not included.",
            t.orphaned_data_if_retired,
        ),
        (
            "orphaned_technologies_if_retired",
            "application_id",
            "Technologies this application was the last one running on.",
            t.orphaned_technologies_if_retired,
        ),
        (
            "capabilities_losing_all_support",
            "application_id",
            "Capabilities whose only supporting application is this one.",
            t.capabilities_losing_all_support,
        ),
        (
            "capabilities_degraded_by_retiring",
            "application_id",
            "Capabilities that keep some support but are affected, because a supporting "
            "application depends on the retired one. Weaker than losing all support.",
            t.capabilities_degraded_by_retiring,
        ),
        (
            "capabilities_unaffected_by_retiring",
            "application_id",
            "Capabilities with no supporting application in the affected set.",
            t.capabilities_unaffected_by_retiring,
        ),
    ]

    for name, argument, description, function in narrow:
        kind = argument.replace("_id", "")
        specs.append(
            ToolSpec(
                name=name,
                description=description,
                schema=_one_id(argument, kind),
                run=(lambda f, a: lambda **kwargs: _findings(f(graph, kwargs[a])))(function, argument),
            )
        )

    return specs


# -------------------------------------------------------------------- the loop


@dataclass
class ToolCall:
    """One tool the model chose, and what the deterministic layer returned."""

    name: str
    arguments: dict[str, Any]
    result: Any
    error: str | None = None

    def render(self) -> str:
        arguments = ", ".join(f"{k}={v!r}" for k, v in self.arguments.items())
        if self.error:
            return f"{self.name}({arguments}) -> error: {self.error}"
        return f"{self.name}({arguments}) -> {json.dumps(self.result, ensure_ascii=False)}"


@dataclass
class Answer:
    """What the model said, and everything it was allowed to say it from."""

    question: str
    text: str
    calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = ""
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def sources(self) -> list[str]:
        """Document sources cited by the retrieval results, in rank order."""
        seen: list[str] = []
        for call in self.calls:
            if call.name != "search_documents" or not isinstance(call.result, list):
                continue
            for hit in call.result:
                if isinstance(hit, dict) and hit.get("source") not in seen:
                    seen.append(hit["source"])
        return seen

    def render(self, evidence: bool = True) -> str:
        parts = [self.text.strip()]
        if evidence:
            parts.append("\n--- evidence " + "-" * 52)
            if not self.calls:
                parts.append(
                    "No tools were called. Nothing in this answer is backed by the "
                    "repository."
                )
            for index, call in enumerate(self.calls, start=1):
                parts.append(f"[{index}] {call.render()}")
        return "\n".join(parts)


class Analyst:
    """One question in, an answer plus its evidence out."""

    def __init__(
        self,
        graph: EAGraph | None = None,
        retriever: KeywordRetriever | None = None,
        model: str = MODEL,
        client: Any | None = None,
    ) -> None:
        self.graph = graph if graph is not None else load_graph()
        self.retriever = (
            retriever if retriever is not None else KeywordRetriever.from_corpus(DEFAULT_CORPUS_ROOT)
        )
        self.model = model
        self.tools = build_tools(self.graph, self.retriever)
        self._by_name = {spec.name: spec for spec in self.tools}
        self._client = client

    @property
    def client(self):
        if self._client is None:
            import anthropic  # imported here so the tools work without the SDK

            workspace = workspace_id()
            self._client = anthropic.Anthropic(
                api_key=api_key(),
                default_headers=(
                    {"anthropic-workspace-id": workspace} if workspace else None
                ),
            )
        return self._client

    def _execute(self, name: str, arguments: dict[str, Any]) -> ToolCall:
        """Run one tool. A bad argument comes back as an error the model can read
        and correct, not as a crash — an unknown id is usually a wrong guess at a
        name, and the model can look it up and try again."""
        spec = self._by_name.get(name)
        if spec is None:
            return ToolCall(name, arguments, None, error=f"no such tool {name!r}")
        try:
            return ToolCall(name, arguments, spec.run(**arguments))
        except UnknownElementError as error:
            return ToolCall(name, arguments, None, error=str(error).strip("'"))
        except (TypeError, ValueError) as error:
            return ToolCall(name, arguments, None, error=f"{type(error).__name__}: {error}")

    def ask(self, question: str) -> Answer:
        messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
        answer = Answer(question=question, text="")
        definitions = [spec.definition() for spec in self.tools]

        for _ in range(MAX_TURNS):
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=MAX_TOKENS,
                    system=SYSTEM_PROMPT,
                    thinking={"type": "adaptive"},
                    tools=definitions,
                    messages=messages,
                )
            except Exception as error:  # re-raised, possibly with a better message
                raise _explain(error) from None
            answer.stop_reason = response.stop_reason or ""
            answer.input_tokens += response.usage.input_tokens
            answer.output_tokens += response.usage.output_tokens

            text = "\n".join(b.text for b in response.content if b.type == "text").strip()
            if text:
                answer.text = text

            requested = [block for block in response.content if block.type == "tool_use"]
            if not requested:
                break

            messages.append({"role": "assistant", "content": response.content})
            results = []
            for block in requested:
                call = self._execute(block.name, dict(block.input))
                answer.calls.append(call)
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(
                            call.error if call.error else call.result, ensure_ascii=False
                        ),
                        **({"is_error": True} if call.error else {}),
                    }
                )
            messages.append({"role": "user", "content": results})
        else:
            answer.text = (
                answer.text
                or f"Stopped after {MAX_TURNS} tool-calling turns without reaching an answer."
            )

        return answer


def ask(question: str, **kwargs) -> Answer:
    """Convenience wrapper: one question, one answer."""
    return Analyst(**kwargs).ask(question)
