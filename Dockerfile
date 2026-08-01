FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend /app/backend
COPY webapp /app/webapp
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh && mkdir -p /app/backend/uploads

WORKDIR /app/backend
EXPOSE 8000

CMD ["/app/start.sh"]
