FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LANGUAGE_GATEWAY_HOST=0.0.0.0 \
    LANGUAGE_GATEWAY_PORT=8000 \
    LANGUAGE_GATEWAY_LOG_LEVEL=info

WORKDIR /app

RUN adduser --disabled-password --gecos "" gateway

COPY pyproject.toml README.md /app/
COPY app /app/app

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir .

USER gateway

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"

CMD ["python", "-m", "app.main"]