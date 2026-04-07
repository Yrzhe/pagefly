FROM python:3.11-slim

WORKDIR /app

# System dependencies for weasyprint (PDF rendering)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    libcairo2 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY . .

RUN mkdir -p /app/data/raw /app/data/knowledge /app/data/wiki

CMD ["python", "-m", "src.main"]
