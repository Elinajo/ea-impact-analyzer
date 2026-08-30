# EA Impact Analyzer — build spec

A small AI-assisted enterprise architecture impact-analysis prototype. Deterministic graph traversal for architecture facts; retrieval over prose for principles and decision records; LLM only for interpretation and explanation.

Built as a four-day prototype ahead of the EUROCONTROL AI-Native EA Tooling traineeship interview on 2 September 2026.

---

## The one design decision that matters

The LLM does not produce architecture facts. It interprets the question, calls deterministic tools, and explains the result. Every factual claim in an answer traces to a relationship in `data/ea_model.json` or a passage in a retrieved document.

Rationale to be able to give out loud: an architecture repository holds structured relationships. Asking which applications support a capability is a query, not a similarity search. Embedding structured data as prose throws away the structure and reintroduces the possibility of a plausible wrong answer where a correct one was computable. Retrieval is reserved for the parts of the corpus that genuinely are prose — principles, ADRs, guidelines.

---

## Relationship semantics — get these right

The distinction between **OWNS** and **CONSUMES** is the substance of the whole tool, and it is where a naive implementation goes wrong.

- `OWNS` — the application is the authoritative source for that data object. Retire it and the data object is orphaned: nothing is authoritative for it any more.
- `CONSUMES` — the application reads data it is not authoritative for. Retire it and the data object is unaffected; only the consumer loses access.

A system that reports "retiring A05 affects D01, D02, D03, D05" is wrong. A05 consumes the first three; it owns only D05. Q03 in the eval set exists to catch exactly this.

Same care with technology: retiring an application orphans a technology only if it was the last application running on it.

---

## Build order

Strictly this order. If time runs out, stop — the earlier stages stand alone as a defensible project.

1. **Graph + loader.** `data/ea_model.json` is supplied. Build `src/graph.py`: load, validate that every relationship endpoint exists, expose lookups by id and by type.
2. **Eval set.** `eval/questions.json` is supplied — twelve questions with expected answers, written before the system existed. Do not modify expected answers to match what the system produces. If the system disagrees with an expected answer, work out which is wrong and record it in the decision log.
3. **Deterministic tools.** `src/tools.py` — pure Python over the graph, no LLM:
   - `applications_for_capability(capability_id)`
   - `direct_dependents(application_id)`
   - `transitive_dependents(application_id)`
   - `owned_data(application_id)` / `consumed_data(application_id)`
   - `orphaned_technologies_if_retired(application_id)`
   - `impact_of_retiring(application_id)` — returns a structured result: directly dependent applications, transitively dependent applications, orphaned data objects, capabilities losing all support, capabilities degraded, orphaned technologies. Each entry carries the relationship path that produced it.
4. **Tests.** `tests/test_tools.py` — assert the graph questions (Q01–Q08) against the tool outputs. These should pass exactly; they are computed, not generated.
5. **Retrieval.** `src/retrieval.py` over `data/principles/*.md` and `data/adrs/*.md`. Chunk on headings. Embed. Hybrid retrieval (vector + keyword) if time allows; pure vector otherwise. Return chunks with source filenames for citation.
6. **LLM layer.** `src/llm.py` — tool schemas exposed to the model, model selects and calls, results returned, model explains. System prompt constrains it: answer only from supplied evidence, cite the relationship path or document for every claim, and if the evidence does not support an answer, say what is missing instead of estimating.
7. **CLI.** `src/main.py` — one question in, answer plus evidence out.
8. **README.** What it does, the structured/unstructured split, how to run it, and the eval results including failures.

No web framework. No database. No React. SQLite only if a vector store needs it.

---

## The refusal cases

Q11 and Q12 must refuse. "Can we safely retire A05?" should return something close to: the model can enumerate architectural dependencies, but operational safety cannot be determined without service level requirements, a transition plan, migration arrangements for the data A05 owns, and an operational risk assessment.

This is the most valuable single feature in the prototype. It demonstrates epistemic boundaries in running code rather than as an opinion, and it connects directly to the thesis: a system that expresses more confidence than its evidence supports produces over-reliance regardless of how accurate it is elsewhere.

---

## Decision log — write entries as you go

`DECISIONS.md`, one short entry per decision, **written at the time**, not reconstructed at the end. Reconstructed rationale reads as too clean and an interviewer can tell.

Entries to expect:
- Why JSON rather than a graph database
- Why OWNS and CONSUMES are distinct edge types
- Why relationship traversal is deterministic rather than LLM-driven
- Why retrieval covers only the prose corpus
- Why the system refuses certain questions
- Anything Claude Code proposed that was changed, and why

That last category is the one worth having examples of. "I used Claude Code to build it" is weak. "Claude proposed X, I changed it to Y because Z" is evidence of judgement.

---

## Eval reporting

Run the twelve questions, record results honestly, including failures. A result like 10/12 with a diagnosis of the two failures is a stronger interview artefact than a claimed 12/12. Retrieval questions in particular are expected to be weak, because architecture documents share vocabulary heavily — if that happens, record what was tried in response (metadata filtering, hybrid retrieval, different chunking) and what it changed.

---

## Kickoff prompt for Claude Code

> I'm building a small enterprise architecture impact-analysis prototype in Python. Read SPEC.md, data/ea_model.json and eval/questions.json first — the model and the evaluation set already exist and the expected answers are not to be modified to match implementation output.
>
> Start with step 1 and step 3 only: the graph loader in src/graph.py and the deterministic tools in src/tools.py. No LLM, no retrieval yet.
>
> The critical semantics: OWNS means the application is the authoritative source for a data object, so retiring it orphans that data object. CONSUMES means the application reads data it is not authoritative for, so retiring it does not affect the data object. impact_of_retiring must respect that distinction. A technology is orphaned only if the retired application was the last one running on it.
>
> impact_of_retiring should return a structured result where every entry carries the relationship path that produced it, so the reasoning can be shown rather than asserted.
>
> Then write tests/test_tools.py asserting questions Q01 through Q08 from the eval set against the tool outputs. These are computed answers and should pass exactly. If any test fails, tell me which and why rather than adjusting the expected answer.
>
> Ask before adding dependencies. No web framework, no database.

---

## Prose corpus to write yourself

Short — three principles, two ADRs, a few hundred words each. Write them by hand rather than generating them; you need to know what is in them when you are asked why retrieval failed on one.

- `principles/P01-authoritative-sources.md` — every data object has one designated authoritative source
- `principles/P02-standard-interfaces.md` — information is exposed through standard interfaces, not direct system-to-system access
- `principles/P03-human-accountability.md` — automated analysis may propose, a named human accepts; applies to AI-assisted services
- `adrs/ADR-001-api-gateway.md` — decision to route external access through an API gateway, alternatives considered, consequences
- `adrs/ADR-002-shared-data-platform.md` — decision to consolidate operational data distribution into a shared platform, and the coupling that created

Note that ADR-002 is the decision that produced the dependency concentration on A05 which the impact analysis now surfaces. That is a good thing to point out in the interview: the tool makes visible the consequence of a decision that was reasonable when it was taken.
