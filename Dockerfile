# ─────────────────────────────────────────────────────────────────────────────
# Sympany Social Listening & Media Compliance — one image, two ECS Fargate roles:
#   web task  (default CMD)  React dashboard + FastAPI API behind the ALB, port 8080
#   scan task (command override)  python -m src.scan_job --job all
# Built by AWS CodeBuild (buildspec.yml) and pushed to Amazon ECR.
# ─────────────────────────────────────────────────────────────────────────────

# ---- Stage 1: build the React dashboard ----
FROM public.ecr.aws/docker/library/node:20-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build          # outputs to /app/frontend/dist

# ---- Stage 2: Python backend that also serves the built frontend ----
FROM public.ecr.aws/docker/library/python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080 \
    KEEP_ALIVE_SECONDS=310
WORKDIR /app

# ffmpeg: split uploaded videos into audio (Amazon Transcribe) and frames (Bedrock vision),
# in temporary files that are deleted after each check. libheif: HEIC/AVIF stills.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libheif1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install -r requirements.txt

# Backend source, runtime config and maintenance tools
COPY src/ ./src/
COPY config/ ./config/
COPY tools/ ./tools/
# Knowledge base collected so far — only read by tools/seed_dynamodb.py (one-time import
# into DynamoDB). The running app reads and writes DynamoDB, never these files.
COPY data/ ./data/

# Built frontend from stage 1 (FastAPI serves it at "/")
COPY --from=frontend /app/frontend/dist ./frontend/dist

# Run as an unprivileged user; only /tmp is written to (temporary media files).
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app \
    && chown -R app:app /app
USER app

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,os;urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.environ.get('PORT','8080'), timeout=4)"

# --proxy-headers: trust X-Forwarded-* from the ALB. Keep-alive above the ALB idle timeout
# (300 s recommended, for long video checks) so the ALB never reuses a closed connection.
CMD ["sh", "-c", "exec uvicorn src.api:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*' --timeout-keep-alive ${KEEP_ALIVE_SECONDS}"]
