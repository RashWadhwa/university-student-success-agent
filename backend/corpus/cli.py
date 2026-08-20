"""Command-line entry point for loading the configured institution corpus."""

from __future__ import annotations

import asyncio

from backend.core.config import get_settings
from backend.corpus.loader import CuratedCorpusLoader, OfficialPDFDownloader, load_manifest
from backend.main import create_app


async def _load() -> None:
    settings = get_settings()
    manifest = load_manifest(settings.primary_institution_corpus_manifest)
    downloader = OfficialPDFDownloader(
        allowed_hosts=settings.primary_institution_source_hosts,
        max_size_bytes=settings.max_document_size_bytes,
        timeout_seconds=settings.corpus_download_timeout_seconds,
    )
    app = create_app(settings)
    try:
        async with app.router.lifespan_context(app):
            if app.state.indexing_service is None:
                raise RuntimeError("The configured embedding provider is unavailable.")
            loader = CuratedCorpusLoader(
                institution=settings.primary_institution_name,
                manager=app.state.document_manager,
                indexing=app.state.indexing_service,
                source=downloader,
            )
            summary = await loader.load(manifest)
            print(summary.model_dump_json(indent=2))
    finally:
        await downloader.close()


def main() -> None:
    asyncio.run(_load())


if __name__ == "__main__":
    main()
