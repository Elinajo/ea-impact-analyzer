# EA Impact Analyzer

An AI-assisted enterprise architecture impact-analysis prototype. Ask it what
breaks if you retire an application, and it answers from the architecture model
rather than from the language model — every factual claim traces back to a
relationship that is really in `data/ea_model.json`, or to a passage in a
document it retrieved.

Built as a four-day prototype ahead of the EUROCONTROL AI-Native EA Tooling
traineeship interview, 2 September 2026. The model describes a fictional
organisation; no real architecture is represented.

```
$ python3 -m src.main --impact A05

Impact of retiring A05 (Operational Data Platform)

Dependent applications:
  - A01 (Network Management Platform): depends on A05, direct
      · direct: A01 -DEPENDS_ON-> A05
  - A06 (Safety Reporting Tool): depends on A05, direct
      · direct: A06 -DEPENDS_ON-> A05
  - A07 (Decision Support Dashboard): depends on A05, direct and indirect
      · direct: A07 -DEPENDS_ON-> A05
      · indirect: A07 -DEPENDS_ON-> A01 ; A01 -DEPENDS_ON-> A05

Orphaned data objects:
  - D05 (Operational Events): A05 is its only authoritative source; no other
    application OWNS it [A05 -OWNS-> D05]

Consumed data (unaffected):
  - D01 (Flight Data): A05 consumes it but is not authoritative for it, so
    retirement does not orphan it [A05 -CONSUMES-> D01]
  ...
```

---

## The one design decision that matters

**Structured relationships are queried. Prose is retrieved. The LLM does
neither — it interprets the question, picks a tool, and explains the result.**

An architecture repository holds structured relationships. Asking which
applications support a capability is a *query*, not a similarity search. The
answer is computable, and therefore checkable. Embedding that structure as prose
and retrieving it throws the structure away and replaces a correct answer with a
plausible one, for nothing in return.

So retrieval is reserved for the part of the corpus that genuinely is prose —
principles and decision records, where the question really is "what did we say
about this" and there is no relation to traverse.

The consequence is visible in the output above: every finding carries the edges
that produced it. Without that, a computed answer and a hallucinated one look
identical to the reader, and the deterministic layer might as well not exist.

### The distinction the whole thing turns on

`OWNS` means the application is the **authoritative source** for a data object.
Retire it and that data is orphaned — nothing is authoritative for it any more.

`CONSUMES` means the application **reads data it is not authoritative for**.
Retire it and the data object is untouched; only the consumer loses access.

A system that reports "retiring A05 affects D01, D02, D03, D05" is wrong. A05
consumes the first three and owns only D05. Q03 in the eval set exists to catch
exactly that. The same care applies to technology (a technology is orphaned only
if the retired application was the last one running on it) and to capabilities
(losing *all* support is a different and stronger claim than being *degraded*).

---

## Running it

No dependencies for the deterministic layer — standard library only.

```bash
python3 -m unittest discover -s tests -t . -v     # tests, no venv needed
python3 eval/run_eval.py                          # the score table
python3 eval/retrieval_probe.py                   # where retrieval falls over
python3 -m src.main --impact A05                  # full impact report, no LLM
```

With a virtualenv (pytest and the Anthropic SDK):

```bash
python3 -m venv .venv && .venv/bin/pip install pytest anthropic
.venv/bin/pytest -q
```

The LLM layer needs a key:

```bash
cp .env.example .env        # then put your key in it; .env is git-ignored
.venv/bin/python3 -m src.main "Which applications depend on the Operational Data Platform?"
.venv/bin/python3 eval/run_eval.py --llm --show
```

The key is read from the environment or from `.env`, never stored in source.

---

## Layout

| Path | What it is |
|---|---|
| `data/ea_model.json` | The architecture model: 22 elements, 33 relationships. Supplied. |
| `data/principles/`, `data/adrs/` | The prose corpus — three principles, two ADRs. |
| `src/graph.py` | Loads and validates the model. Reports every problem, not just the first. |
| `src/tools.py` | Deterministic traversal. Every result carries its relationship path. |
| `src/retrieval.py` | BM25 over heading-level chunks. Standard library. |
| `src/llm.py` | Tool schemas, the agent loop, and the system prompt that bounds it. |
| `src/main.py` | CLI: one question in, answer plus evidence out. |
| `eval/questions.json` | Twelve questions with expected answers, written before the system. |
| `eval/run_eval.py` | Scores them. Two modes — see below. |
| `DECISIONS.md` | One entry per architecture decision, written at the time. |

---

## Eval results

Twelve questions, written before the system existed. **Expected answers are
never adjusted to match what the system produces.**

The runner scores in two layers, because they measure different things and one
combined number would hide which layer failed.

### Deterministic layer — 10/10 scored, 2 not run

`python3 eval/run_eval.py`. No API key, no model.

| Q | Type | Result | Note |
|---|---|---|---|
| Q01–Q08 | graph | **8/8 pass** | Exact set match. Computed, not generated. |
| Q09 | retrieval | **pass** | P03 at rank 1. |
| Q10 | retrieval | **pass** | ADR-002 at rank 1. |
| Q11, Q12 | refusal | **not run** | Needs the LLM layer and a key. |

### End-to-end layer — built, not yet run

`python3 eval/run_eval.py --llm`. **This has not been executed**: the layer is
written and its tools are unit-tested, but no API key was available when it was
built, so no end-to-end number is claimed here. Q11 and Q12 are therefore
**unmeasured, not passing**. Anyone reading this before that run has happened
should treat the honest score as **10 of 12, with 2 unmeasured**.

Scoring at this layer is heuristic by necessity — it is checking a paragraph of
English, not a set of ids — and every heuristic names itself in the output.
`--show` prints the answers in full so they can actually be read.

### What is weak, and why

**Retrieval passes for a slightly flattering reason.** Q09 and Q10 both share
vocabulary with the document they are supposed to find: Q09 says "AI-assisted
service" and P03's *Applies to* section says "AI-assisted service"; Q10 says
"shared data platform", which is ADR-002's title. That is a real pass, but it is
not evidence that the retrieval generalises.

`eval/retrieval_probe.py` asks the same questions in words the documents do not
use. **5 of 7 probes** find the right document. The two misses are total:

- *"What rule governs who is the master system for a dataset?"* → P01 does not
  make the top 3 at all. BM25 cannot connect "master system" to "authoritative
  source", or "dataset" to "data object".
- *"How should systems talk to each other?"* → P02 does not appear. The question
  shares no content word with the document.

These are vocabulary mismatches, not ranking errors, and no amount of BM25
tuning fixes them. It is the case a vector index exists for. The hybrid
retrieval in the spec is deliberately half-built — keyword first, so that what a
vector index adds can be measured rather than assumed (`DECISIONS.md` D07) — and
this probe is the measurement that says it would now be worth adding.

**Stemming is off.** "principle" and "principles" are separate terms. That was
kept as the first knob to turn if retrieval scored badly; it did not, so the
knob was not turned (`DECISIONS.md` D10).

---

## What it refuses to do

Q11 asks "can we safely retire the Operational Data Platform?" and Q12 asks what
a replacement would cost. Both must decline.

This is the most valuable feature in the prototype. The system can enumerate
architectural dependencies; it cannot determine operational safety, which needs
service level requirements, a transition plan, migration arrangements for the
data A05 owns, and an operational risk assessment. None of that is in the
repository. Cost is not represented anywhere at all.

The refusal is not a keyword rule. The system prompt states what the repository
*contains* and what it *does not*, and the refusal follows from that boundary —
so it applies to any question the evidence cannot carry, not only to the two in
the eval set (`DECISIONS.md` D12). A keyword rule would score green on these two
questions and prove nothing.

A confident yes or no scores zero, and it should: a system that expresses more
confidence than its evidence supports produces over-reliance no matter how
accurate it is elsewhere.

---

## Not built

- The vector half of the hybrid retrieval (D07) — with the measurement above
  showing it is now justified.
- No web framework, no database, no ORM. The model is 22 elements; traversal
  over dictionaries is faster than the query planner would be (D01).
