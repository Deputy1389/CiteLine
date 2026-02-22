# Base image for Python and system-level medical processing dependencies
FROM python:3.12-slim-bookworm

# Install Tesseract OCR, Poppler (for PDF), and other system dependencies
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    libtesseract-dev \
    tesseract-ocr-eng \
    libmupdf-dev \
    mupdf-tools \
    python3-dev \
    build-essential \
    libpq-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install Python dependencies first (leverage Docker cache)
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

# Copy the rest of the application
COPY . .

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

# Expose the API port
EXPOSE 8000

# Default command starts the API (can be overridden for worker)
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
