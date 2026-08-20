"""Structure-aware, page-preserving text chunking."""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import uuid4

from backend.documents.models import ChunkRecord, PageRecord

_NUMBERED_HEADING = re.compile(r"^(?:\d+(?:\.\d+)*[.)]?|[A-Z][.)])\s+\S+")


@dataclass(frozen=True, slots=True)
class _Section:
    page_number: int
    heading: str | None
    text: str


class StructureAwareChunker:
    """Prefer page, heading, paragraph, and sentence boundaries."""

    def __init__(self, *, chunk_size: int, chunk_overlap: int) -> None:
        if chunk_size < 100:
            raise ValueError("chunk_size must be at least 100 characters")
        if chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be non-negative and smaller than chunk_size")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk(self, pages: list[PageRecord]) -> list[ChunkRecord]:
        chunks: list[ChunkRecord] = []
        for page in pages:
            for section in self._sections(page):
                for text in self._split_text(section.text):
                    chunks.append(
                        ChunkRecord(
                            id=str(uuid4()),
                            index=len(chunks),
                            text=text,
                            char_count=len(text),
                            page_start=section.page_number,
                            page_end=section.page_number,
                            heading=section.heading,
                            metadata={
                                "page_number": section.page_number,
                                "heading": section.heading,
                            },
                        )
                    )
        return chunks

    def _sections(self, page: PageRecord) -> list[_Section]:
        lines = page.text.splitlines()
        sections: list[_Section] = []
        heading: str | None = None
        body: list[str] = []

        def flush() -> None:
            text = self._normalise_body(body)
            if text:
                sections.append(_Section(page_number=page.page_number, heading=heading, text=text))
            body.clear()

        for line in lines:
            stripped = line.strip()
            if stripped and self._is_heading(stripped):
                flush()
                heading = stripped
            else:
                body.append(stripped)
        flush()

        if not sections and page.text.strip():
            sections.append(
                _Section(page_number=page.page_number, heading=None, text=page.text.strip())
            )
        return sections

    def _split_text(self, text: str) -> list[str]:
        if len(text) <= self.chunk_size:
            return [text]

        chunks: list[str] = []
        start = 0
        while start < len(text):
            maximum_end = min(start + self.chunk_size, len(text))
            end = maximum_end
            if maximum_end < len(text):
                end = self._preferred_break(text, start, maximum_end)
            piece = text[start:end].strip()
            if piece:
                chunks.append(piece)
            if end >= len(text):
                break
            next_start = max(0, end - self.chunk_overlap)
            if next_start <= start:
                next_start = end
            start = self._word_start(text, next_start, end)
        return chunks

    @staticmethod
    def _normalise_body(lines: list[str]) -> str:
        paragraphs: list[str] = []
        current: list[str] = []
        for line in lines:
            if line:
                current.append(line)
            elif current:
                paragraphs.append(" ".join(current))
                current = []
        if current:
            paragraphs.append(" ".join(current))
        return "\n\n".join(paragraphs).strip()

    @staticmethod
    def _is_heading(line: str) -> bool:
        if len(line) > 120 or line.endswith((".", ";", ",")):
            return False
        words = line.split()
        if not words or len(words) > 14:
            return False
        return bool(
            _NUMBERED_HEADING.match(line)
            or (any(char.isalpha() for char in line) and line.upper() == line)
            or (len(words) >= 2 and line.istitle())
        )

    @staticmethod
    def _preferred_break(text: str, start: int, maximum_end: int) -> int:
        minimum = start + max(1, (maximum_end - start) // 2)
        for marker in ("\n\n", ". ", "\n", " "):
            position = text.rfind(marker, minimum, maximum_end)
            if position >= minimum:
                return position + (1 if marker == ". " else 0)
        return maximum_end

    @staticmethod
    def _word_start(text: str, candidate: int, previous_end: int) -> int:
        if candidate <= 0 or candidate >= len(text) or text[candidate - 1].isspace():
            return candidate
        boundary = text.find(" ", candidate, previous_end)
        return boundary + 1 if boundary != -1 else candidate
