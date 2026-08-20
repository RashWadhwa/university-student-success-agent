"""Thin HTTP adapter for document ingestion."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile, status

from backend.api.dependencies import get_document_manager
from backend.documents.manager import DocumentManager
from backend.schemas.documents import DocumentResponse, DocumentUploadResponse

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
