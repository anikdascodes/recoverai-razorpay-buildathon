FROM python:3.12-slim

WORKDIR /app

# install deps first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# app code
COPY app/ ./app/

# data lives on the mounted volume so it survives redeploys
ENV DATABASE_URL=sqlite:////data/recoverai.db
ENV AUDIT_FILE=/data/audit.jsonl

EXPOSE 8000

# init_db on boot so a fresh volume is usable immediately
CMD ["sh", "-c", "python -c \"from app.db import init_db; init_db()\" && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
