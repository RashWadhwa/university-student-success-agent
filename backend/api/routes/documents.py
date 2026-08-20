"""Thin HTTP adapters for document ingestion and indexing."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile, status

from backend.api.dependencies import get_document_manager, get_indexing_service
from backend.documents.manager import DocumentManager
from backend.rag.errors import DocumentNotFoundError
from backend.rag.indexing import IndexingService
from backend.schemas.documents import DocumentResponse, DocumentUploadResponse
from backend.schemas.indexing import DocumentIndexRequest, DocumentIndexResponse

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post(
    "",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and ingest a PDF document",
)
async def upload_document(
    file: Annotated[UploadFile, File(description="A text-based PDF document")],
    manager: Annotated[DocumentManager, Depends(get_document_manager)],
) -> DocumentUploadResponse:
    try:
        record = await manager.ingest(file)
    finally:
        await file.close()
    return DocumentUploadResponse(document=DocumentResponse.model_validate(record.model_dump()))


@router.post(
    "/{document_id}/index",
    response_model=DocumentIndexResponse,
    summary="Embed and index an ingested document",
)
async def index_document(
    document_id: UUID,
    request: DocumentIndexRequest,
    manager: Annotated[DocumentManager, Depends(get_document_manager)],
    service: Annotated[IndexingService, Depends(get_indexing_service)],
) -> DocumentIndexResponse:
    record = manager.get_document(str(document_id))
    if record is None:
        raise DocumentNotFoundError(str(document_id))
    result = await service.index_document(record, request.to_domain())
    return DocumentIndexResponse.from_result(result)
