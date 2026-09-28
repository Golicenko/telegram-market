FROM python:3.12-slim

# Redeploy request 2026-09-29: main already includes referral backend PR #58.

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend /app/backend
COPY webapp /app/webapp
RUN python /app/backend/scripts/build_webapp.py
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh && mkdir -p /app/backend/uploads

WORKDIR /app/backend
EXPOSE 8000

CMD ["/app/start.sh"]
