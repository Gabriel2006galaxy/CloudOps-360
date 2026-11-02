# CloudOps 360 - container image.
#   Production-style default: Gunicorn on port 8000 (FLASK_ENV=production; secrets come from
#   AWS Secrets Manager or the environment, never from the image).
#   docker-compose.yml overrides the command for local development.
#   infrastructure/aws/docker_demo.sh builds and runs it on the EC2 server next to the live site.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_ENV=production \
    PORT=8000 \
    BIND_HOST=0.0.0.0 \
    WORKERS=2
WORKDIR /app

# Dependencies first, so code changes do not reinstall them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code only (.dockerignore keeps out .env, databases, uploads, .git and the virtualenv)
COPY . .
RUN useradd --system --home /app cloudops \
    && mkdir -p /app/uploads \
    && chown -R cloudops:cloudops /app/uploads
USER cloudops

EXPOSE 8000
# Docker marks the container healthy only when the app reaches its database and storage
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT', '8000'), timeout=8)"

CMD ["sh", "-c", "exec gunicorn --bind ${BIND_HOST}:${PORT} --workers ${WORKERS} --timeout 60 --forwarded-allow-ips 127.0.0.1 --access-logfile - --error-logfile - wsgi:app"]
