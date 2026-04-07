FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY . .

RUN mkdir -p /app/data/raw /app/data/knowledge /app/data/wiki

CMD ["python", "-m", "src.main"]
