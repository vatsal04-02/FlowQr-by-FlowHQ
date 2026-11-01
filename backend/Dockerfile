FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY alembic.ini .
COPY alembic ./alembic
COPY app ./app
RUN useradd --system --uid 10001 --no-create-home flowqr && chown -R flowqr /srv
USER flowqr
EXPOSE 8000
# Behind Caddy only (port never published publicly), so trusting forwarded headers is safe.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*", "--workers", "2"]
