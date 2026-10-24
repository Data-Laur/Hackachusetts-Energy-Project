# Heat Check self-hosting app (upload flow).
FROM python:3.12-slim

# Don't buffer stdout/stderr; no .pyc files.
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install dependencies first (better layer caching).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the code + the precomputed report, assets, and samples the app serves.
COPY app.py config.py climate.py waste_detect.py ./
COPY src/ ./src/
COPY docs/ ./docs/
COPY samples/ ./samples/

# Render (and most PaaS) provide the port via $PORT; default to 8000 locally.
ENV PORT=8000
EXPOSE 8000

# Shell form so $PORT expands at runtime.
CMD uvicorn app:app --host 0.0.0.0 --port $PORT
