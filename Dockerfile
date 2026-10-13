# CloudOps 360 - container image for local development (docker compose).
# Production on EC2 runs under systemd + Gunicorn (see infrastructure/aws).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN useradd --system --home /app cloudops \
    && mkdir -p /app/uploads \
    && chown -R cloudops:cloudops /app/uploads
USER cloudops

EXPOSE 5000
# Apply migrations, then start the development server
CMD ["sh", "-c", "flask --app wsgi db upgrade && python run.py"]
