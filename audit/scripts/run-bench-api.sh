cd "$(dirname "$0")/../backend"
export APP_ENV=development DATABASE_URL="postgresql+psycopg://flowqr_app:flowqr_app_dev@127.0.0.1:55441/flowqr_bench" MIGRATION_DATABASE_URL="postgresql+psycopg://flowqr:flowqr_dev@127.0.0.1:55441/flowqr_bench" REDIS_URL="redis://127.0.0.1:1/0" TOKEN_ENCRYPTION_KEY="Zm9yLXRlc3RzLW9ubHktMzItYnl0ZS1rZXktMTIzNDU=" GOOGLE_CLIENT_ID=x GOOGLE_CLIENT_SECRET=y RATE_LIMIT_ENABLED=false PLATFORM_ADMIN_EMAILS=root@flowhq-admin.example.com COOKIE_SECURE=false
exec ../venv/Scripts/python -m uvicorn app.main:app --port 8155
