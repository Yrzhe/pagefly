# ── Build stage ──
FROM python:3.11-slim AS builder

WORKDIR /build

COPY pyproject.toml ./
RUN pip install --no-cache-dir --prefix=/install .

# ── Runtime stage ──
FROM python:3.11-slim

WORKDIR /app

# System dependencies for weasyprint (PDF rendering) + Chinese fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    libcairo2 \
    curl \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY src/ ./src/
COPY config/ ./config/
COPY data/demo/ ./data/demo/
COPY pyproject.toml ./

# Create non-root user and data directories
RUN groupadd -r pagefly && useradd -r -g pagefly -d /app pagefly \
    && mkdir -p /app/data/raw /app/data/knowledge /app/data/wiki \
       /app/data/inbox /app/data/workspace \
    && chown -R pagefly:pagefly /app

USER pagefly

# Health check — hits the FastAPI /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -sf http://localhost:8000/health || exit 1

EXPOSE 8000

CMD ["python", "-m", "src.main"]
