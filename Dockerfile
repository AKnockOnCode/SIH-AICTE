FROM python:3.12-slim

WORKDIR /app

# Install system dependencies if any
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy backend requirements and install
COPY backend/requirements.txt backend/
RUN pip install --no-cache-dir -r backend/requirements.txt

# Copy application files and prebuilt UI bundle
COPY backend backend
COPY frontend/dist frontend/dist
COPY .env.example .env

ENV PORT=10000
ENV AGNIDRISHTI_AUTO_SEED=1

EXPOSE 10000

CMD ["sh", "-c", "cd backend && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
