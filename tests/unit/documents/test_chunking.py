"""Tests for structure-aware, metadata-preserving chunking."""

from backend.documents.chunking import StructureAwareChunker
from backend.documents.models import PageRecord


def test_chunker_preserves_page_and_heading_metadata() -> None:
    page = PageRecord(
        page_number=3,
        text=(
            "ACADEMIC PROGRESS\n"
            + "Students must meet the published progression rules. " * 14
            + "\n\nAppeals must be submitted by the stated deadline. " * 8
        ),
        char_count=900,
        metadata={"rotation": 0},
    )
    chunker = StructureAwareChunker(chunk_size=220, chunk_overlap=40)

    chunks = chunker.chunk([page])

    assert len(chunks) > 1
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.page_start == 3 and chunk.page_end == 3 for chunk in chunks)
    assert all(chunk.heading == "ACADEMIC PROGRESS" for chunk in chunks)
    assert all(chunk.char_count <= 220 for chunk in chunks)
    assert all(chunk.metadata["page_number"] == 3 for chunk in chunks)


def test_chunker_does_not_merge_pages() -> None:
    pages = [
        PageRecord(page_number=1, text="First page policy text.", char_count=23),
        PageRecord(page_number=2, text="Second page policy text.", char_count=24),
    ]

    chunks = StructureAwareChunker(chunk_size=200, chunk_overlap=20).chunk(pages)

    assert [(chunk.page_start, chunk.page_end) for chunk in chunks] == [(1, 1), (2, 2)]
