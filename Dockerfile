FROM python:3.11-slim

ARG APP_VERSION=dev
ARG GIT_SHA=unknown
ARG GIT_BRANCH=unknown
ARG BUILD_TIME=unknown
ARG BUILD_IMAGE=unknown

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    GATEWAY_CONFIG=/app/config.yaml \
    APP_VERSION=${APP_VERSION} \
    GIT_SHA=${GIT_SHA} \
    GIT_BRANCH=${GIT_BRANCH} \
    BUILD_TIME=${BUILD_TIME} \
    BUILD_IMAGE=${BUILD_IMAGE}

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
