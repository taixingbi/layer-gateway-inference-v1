FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    GATEWAY_CONFIG=/app/config.yaml

WORKDIR /app

COPY pyproject.toml README.md config.yaml ./
COPY app/ app/

RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir . \
 && useradd --create-home --system appuser \
 && chown -R appuser:appuser /app

USER appuser
EXPOSE 8010

CMD ["python", "-m", "app.main"]
