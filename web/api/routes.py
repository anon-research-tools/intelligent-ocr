"""
API Routes for OCR Web Service

Endpoints:
- POST /api/upload - Upload PDF for processing
- GET /api/status/{task_id} - Get task status
- GET /api/download/{task_id} - Download processed PDF
- DELETE /api/task/{task_id} - Cancel/delete task
"""
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse

from .tasks import (
    get_task_store,
    get_processor,
    TaskStatus,
    TaskStore,
)


router = APIRouter(prefix="/api", tags=["OCR API"])


@router.post("/upload")
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    languages: str = Form("ch,en"),
    dpi: int = Form(300),
):
    """
    Upload a PDF file for OCR processing.

    Args:
        file: PDF file to process
        languages: Comma-separated language codes (ch, en, japan)
        dpi: Processing DPI (150, 200, 300, 400)

    Returns:
        task_id: Unique identifier for tracking the task
        message: Status message

    Raises:
        400: Invalid file type or file too large
        503: Queue is full
    """
    store = get_task_store()
    processor = get_processor()

    # Validate file type
    if not file.filename or not file.filename.lower().endswith('.pdf'):
        raise HTTPException(
            status_code=400,
            detail="Only PDF files are accepted"
        )

    # Check queue capacity (rate limiting)
    if not store.can_accept_task():
        raise HTTPException(
            status_code=503,
            detail="Queue is full, please try again later"
        )

    # Read and validate file size
    content = await file.read()
    if len(content) > store.MAX_FILE_SIZE:
        max_mb = store.MAX_FILE_SIZE // (1024 * 1024)
        raise HTTPException(
            status_code=400,
            detail=f"File too large, maximum {max_mb}MB allowed"
        )

    # Parse languages
    lang_list = [lang.strip() for lang in languages.split(",") if lang.strip()]
    if not lang_list:
        lang_list = ["ch", "en"]

    # Validate and clamp DPI
    dpi = max(150, min(400, dpi))

    # Create task
    task = store.create_task(
        filename=file.filename,
        languages=lang_list,
        dpi=dpi,
    )

    # Save uploaded file
    with open(task.input_path, "wb") as f:
        f.write(content)

    # Start background processing
    background_tasks.add_task(
        processor.process_pdf_async,
        task.task_id,
        task.input_path,
        task.output_path,
        task.languages,
        task.dpi,
    )

    return {
        "task_id": task.task_id,
        "message": "File uploaded, processing started",
    }


@router.get("/status/{task_id}")
async def get_status(task_id: str):
    """
    Get processing status for a task.

    Args:
        task_id: Task identifier from upload response

    Returns:
        Task status including progress percentage, current page, etc.

    Raises:
        404: Task not found
    """
    store = get_task_store()
    task = store.get_task(task_id)

    if not task:
        raise HTTPException(
            status_code=404,
            detail="Task not found"
        )

    return task.to_dict()


@router.get("/download/{task_id}")
async def download_file(task_id: str):
    """
    Download the processed PDF file.

    Args:
        task_id: Task identifier

    Returns:
        PDF file as download

    Raises:
        400: Task not completed
        404: Task or output file not found
    """
    store = get_task_store()
    task = store.get_task(task_id)

    if not task:
        raise HTTPException(
            status_code=404,
            detail="Task not found"
        )

    if task.status != TaskStatus.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail=f"Task not completed, current status: {task.status.value}"
        )

    if not task.output_path or not Path(task.output_path).exists():
        raise HTTPException(
            status_code=404,
            detail="Output file not found or expired"
        )

    # Generate download filename from original
    original_name = Path(task.filename).stem
    download_name = f"{original_name}_ocr.pdf"

    return FileResponse(
        path=task.output_path,
        media_type="application/pdf",
        filename=download_name,
    )


@router.delete("/task/{task_id}")
async def cancel_task(task_id: str):
    """
    Cancel a pending task or delete a completed task.

    Note: Cannot cancel tasks that are currently processing.

    Args:
        task_id: Task identifier

    Returns:
        Success message

    Raises:
        400: Cannot cancel processing task
        404: Task not found
    """
    store = get_task_store()
    task = store.get_task(task_id)

    if not task:
        raise HTTPException(
            status_code=404,
            detail="Task not found"
        )

    if task.status == TaskStatus.PROCESSING:
        raise HTTPException(
            status_code=400,
            detail="Cannot cancel a task that is currently processing"
        )

    # Delete the task and clean up files
    store.delete_task(task_id)

    return {"message": "Task cancelled and removed"}


@router.get("/health")
async def health_check():
    """
    Health check endpoint for monitoring.

    Returns:
        Service status and queue information
    """
    store = get_task_store()

    return {
        "status": "healthy",
        "pending_tasks": store.get_pending_count(),
        "max_queue_size": store.MAX_QUEUE_SIZE,
        "can_accept_tasks": store.can_accept_task(),
    }
