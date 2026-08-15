FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY nexa ./nexa
COPY config/settings.example.json /app/defaults/settings.example.json
COPY deploy/bot-entrypoint.sh /app/bot-entrypoint.sh
RUN chmod +x /app/bot-entrypoint.sh \
    && mkdir -p /app/config /app/data/media /app/sessions

ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["/bin/sh", "/app/bot-entrypoint.sh"]
CMD ["python", "-m", "nexa.cli", "run"]
