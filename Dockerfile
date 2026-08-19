FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY migrations ./migrations
COPY data ./data

RUN useradd --create-home --uid 10001 specledger \
    && mkdir -p /app/object-data \
    && chown -R specledger:specledger /app

USER specledger

EXPOSE 8000
CMD ["sh", "-c", "uvicorn backend.specledger.http_api:app --host 0.0.0.0 --port ${PORT}"]
