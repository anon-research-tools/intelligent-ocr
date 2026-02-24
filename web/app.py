"""
FastAPI Web Application for OCR Tool

Main application entry point with:
- CORS middleware for cross-origin requests
- API router for OCR endpoints
- Static files serving for frontend
- Background cleanup task

Usage:
    uvicorn web.app:app --host 0.0.0.0 --port 8000

Or directly:
    python -m web.app
"""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .api import router, init_task_system, get_task_store


# Paths
WEB_DIR = Path(__file__).parent
TEMPLATES_DIR = WEB_DIR / "templates"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.

    Startup:
    - Initialize task management system
    - Start periodic cleanup task

    Shutdown:
    - Cancel cleanup task
    """
    # Initialize task system
    task_store, _ = init_task_system()

    # Start cleanup loop
    cleanup_task = asyncio.create_task(task_store.start_cleanup_loop())

    yield

    # Shutdown
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass


# Create FastAPI application
app = FastAPI(
    title="OCR Tool API",
    description="Convert scanned PDFs to searchable documents using OCR",
    version="2.0.2",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS middleware for cross-origin requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API router
app.include_router(router)


# Serve frontend
@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the frontend HTML page"""
    template_path = TEMPLATES_DIR / "index.html"

    if template_path.exists():
        return HTMLResponse(content=template_path.read_text(encoding="utf-8"))

    # Fallback minimal page if template not found
    return HTMLResponse(content="""
    <!DOCTYPE html>
    <html>
    <head><title>OCR Tool</title></head>
    <body>
        <h1>OCR Tool API</h1>
        <p>Frontend template not found.</p>
        <p>API documentation available at <a href="/docs">/docs</a></p>
    </body>
    </html>
    """)


# Health check at root level
@app.get("/health")
async def root_health():
    """Root health check endpoint"""
    return {"status": "ok", "service": "ocr-tool"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "web.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
