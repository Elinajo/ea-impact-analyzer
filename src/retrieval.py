"""Retrieval over the prose corpus — SPEC.md step 5.

Structured relationships are queried in ``tools.py``; this module covers the
part of the corpus that genuinely is prose: principles and decision records.

Keyword retrieval (BM25) over heading-level chunks, standard library only.
That is deliberately the first half of the hybrid the spec asks for: it runs
today with no dependencies and no API key, and it gives an honest baseline to
measure a vector index against later, rather than assuming the vector index
helped. :class:`Retriever` is the seam a ``VectorRetriever`` slots into.

Chunk sources are reported relative to the corpus root, so a citation reads
``principles/P03-human-accountability.md`` — the form eval/questions.json
expects in ``expected_sources``.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Protocol, Sequence

from .graph import REPO_ROOT

DEFAULT_CORPUS_ROOT = REPO_ROOT / "data"

#: Globs searched for prose, relative to the corpus root.
CORPUS_GLOBS = ("principles/*.md", "adrs/*.md")

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_TOKEN = re.compile(r"[a-z0-9]+")

#: Deliberately small and English-only. The corpus and the eval questions are
#: English; an aggressive list would start removing domain words like "data".
STOPWORDS = frozenset(
    """
    a an and are as at be been but by can could do does for from had has have
    how i if in into is it its may might must of on or our shall should so
    such than that the their them then there these they this those to was we
    were what when where which while who why will with would you your
    """.split()
)


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens, minus stopwords.

    No stemming: "principle" and "principles" are different terms here. That is
    a known weakness and a knob to turn if the retrieval evals are poor — the
    point of keeping it explicit is to be able to say what was tried.
    """
    return [token for token in _TOKEN.findall(text.lower()) if token not in STOPWORDS]


@dataclass(frozen=True)
class Chunk:
    """One heading and the prose beneath it, up to the next heading."""

    source: str  # relative to the corpus root, e.g. "adrs/ADR-002-shared-data-platform.md"
    document_title: str
    heading: str
    heading_path: tuple[str, ...]
    body: str
    line_start: int
    line_end: int

    @property
    def id(self) -> str:
        return f"{self.source}#{self.line_start}"

    @property
    def breadcrumb(self) -> str:
        return " > ".join(self.heading_path) if self.heading_path else self.source

    @property
    def indexable_text(self) -> str:
        """Heading trail plus body. The trail is indexed because a heading like
        'Alternatives considered' carries real signal about what the section is."""
        return "\n".join([*self.heading_path, self.body]).strip()

    @property
    def is_empty(self) -> bool:
        """True when the section has a heading but no prose under it yet."""
        return not self.body.strip()

    @property
    def is_document_title(self) -> bool:
        """True for the top-level heading of a document.

        A document whose H1 is followed straight by its first ``##`` has an
        empty title chunk, which is normal formatting and not an unwritten
        section. Distinguishing the two keeps :attr:`KeywordRetriever.
        unwritten_sections` a real signal about corpus completeness.
        """
        return len(self.heading_path) <= 1

    def citation(self) -> str:
        return f"{self.source} ({self.breadcrumb}), lines {self.line_start}-{self.line_end}"


def chunk_markdown(text: str, source: str) -> list[Chunk]:
    """Split a markdown document on headings.

    HTML comments are removed before chunking, so editorial notes in a draft
    never reach the index. Headings inside fenced code blocks are not treated
    as headings.
    """
    text = _HTML_COMMENT.sub("", text)
    lines = text.splitlines()

    document_title = ""
    stack: list[tuple[int, str]] = []  # (level, heading text)
    chunks: list[Chunk] = []

    current_heading = ""
    current_path: tuple[str, ...] = ()
    current_body: list[str] = []
    current_start = 1
    in_fence = False

    def flush(end_line: int) -> None:
        body = "\n".join(current_body).strip()
        if not current_heading and not body:
            return  # blank preamble, nothing to index or cite
        chunks.append(
            Chunk(
                source=source,
                document_title=document_title,
                heading=current_heading,
                heading_path=current_path,
                body=body,
                line_start=current_start,
                line_end=end_line,
            )
        )

    for number, line in enumerate(lines, start=1):
        if _FENCE.match(line):
            in_fence = not in_fence
        match = None if in_fence else _HEADING.match(line)
        if match is None:
            current_body.append(line)
            continue

        flush(number - 1)

        level, heading = len(match.group(1)), match.group(2).strip()
        if not document_title and level == 1:
            document_title = heading
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, heading))

        current_heading = heading
        current_path = tuple(text for _, text in stack)
        current_body = []
        current_start = number

    flush(len(lines))
    return chunks


def load_corpus(root: str | Path = DEFAULT_CORPUS_ROOT) -> list[Chunk]:
    """Chunk every prose document under ``root``, sorted by source."""
    root = Path(root)
    chunks: list[Chunk] = []
    for glob in CORPUS_GLOBS:
        for path in sorted(root.glob(glob)):
            source = path.relative_to(root).as_posix()
            chunks.extend(chunk_markdown(path.read_text(encoding="utf-8"), source))
    return chunks


@dataclass(frozen=True)
class SearchResult:
    chunk: Chunk
    score: float
    rank: int

    @property
    def source(self) -> str:
        return self.chunk.source

    def render(self) -> str:
        return f"{self.rank}. [{self.score:.3f}] {self.chunk.citation()}"


class Retriever(Protocol):
    """The seam a vector retriever slots into (SPEC.md step 5, hybrid)."""

    def search(self, query: str, k: int = 3) -> list[SearchResult]: ...


@dataclass
class KeywordRetriever:
    """BM25 over chunks. Deterministic, offline, no dependencies.

    Sections with a heading but no prose are excluded from the index and listed
    in :attr:`empty_sections`: an unwritten section must not be retrievable, and
    silently dropping it would hide that the corpus is incomplete.
    """

    chunks: Sequence[Chunk]
    k1: float = 1.5
    b: float = 0.75

    indexed: list[Chunk] = field(init=False, default_factory=list)
    empty_sections: list[Chunk] = field(init=False, default_factory=list)
    _frequencies: list[Counter[str]] = field(init=False, default_factory=list)
    _lengths: list[int] = field(init=False, default_factory=list)
    _document_frequency: Counter[str] = field(init=False, default_factory=Counter)
    _average_length: float = field(init=False, default=0.0)

    def __post_init__(self) -> None:
        for chunk in self.chunks:
            (self.empty_sections if chunk.is_empty else self.indexed).append(chunk)

        for chunk in self.indexed:
            counts = Counter(tokenize(chunk.indexable_text))
            self._frequencies.append(counts)
            self._lengths.append(sum(counts.values()))
            self._document_frequency.update(counts.keys())
        if self._lengths:
            self._average_length = sum(self._lengths) / len(self._lengths)

    @property
    def unwritten_sections(self) -> list[Chunk]:
        """Empty sections that really are unwritten prose.

        An empty document title whose document has written sections underneath
        is formatting, not a gap; reporting it would make a finished corpus look
        incomplete and drown the signal this list exists to give.
        """
        written = {chunk.source for chunk in self.indexed}
        return [
            chunk
            for chunk in self.empty_sections
            if not (chunk.is_document_title and chunk.source in written)
        ]

    @classmethod
    def from_corpus(cls, root: str | Path = DEFAULT_CORPUS_ROOT) -> "KeywordRetriever":
        return cls(load_corpus(root))

    def _idf(self, term: str) -> float:
        total = len(self.indexed)
        seen = self._document_frequency.get(term, 0)
        return math.log(1 + (total - seen + 0.5) / (seen + 0.5))

    def score(self, query_terms: Sequence[str], index: int) -> float:
        counts = self._frequencies[index]
        length = self._lengths[index] or 1
        total = 0.0
        for term in query_terms:
            frequency = counts.get(term, 0)
            if not frequency:
                continue
            denominator = frequency + self.k1 * (
                1 - self.b + self.b * length / (self._average_length or 1)
            )
            total += self._idf(term) * frequency * (self.k1 + 1) / denominator
        return total

    def search(self, query: str, k: int = 3) -> list[SearchResult]:
        """Top-k chunks for a query, best first. Zero-scoring chunks are not
        returned: padding the list to k would invent relevance."""
        terms = tokenize(query)
        scored = [
            (self.score(terms, index), index)
            for index in range(len(self.indexed))
        ]
        # Sort by score, then chunk id, so ties are broken deterministically.
        ranked = sorted(
            (pair for pair in scored if pair[0] > 0),
            key=lambda pair: (-pair[0], self.indexed[pair[1]].id),
        )
        return [
            SearchResult(chunk=self.indexed[index], score=score, rank=rank)
            for rank, (score, index) in enumerate(ranked[:k], start=1)
        ]

    def __repr__(self) -> str:
        return (
            f"<KeywordRetriever {len(self.indexed)} indexed chunk(s), "
            f"{len(self.empty_sections)} empty section(s)>"
        )
