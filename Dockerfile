# Dockerfile for OCR Tool Web Service
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt

# Copy application code
COPY core/ core/
COPY web/ web/

# Create directories for file storage
RUN mkdir -p /tmp/ocr_uploads /tmp/ocr_outputs

# Environment variables
ENV UPLOAD_DIR=/tmp/ocr_uploads
ENV OUTPUT_DIR=/tmp/ocr_outputs
ENV PYTHONUNBUFFERED=1

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

# Run the application
CMD ["uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8000"]
