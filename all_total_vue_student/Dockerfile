FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8100 \
    HOST=0.0.0.0 \
    SERVICE_MODE=spells \
    SPELL_DB_PATH=/app/data/kharakteres.sqlite \
    FASTEMBED_CACHE_PATH=/models/fastembed

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /app/data /models/fastembed \
    && useradd --create-home --uid 10001 kharakteres \
    && chown -R kharakteres:kharakteres /app /models
USER kharakteres

EXPOSE 8100
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8100/health', timeout=3)" || exit 1

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8100"]
