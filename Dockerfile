FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY . .
RUN pip install --no-cache-dir .
RUN python -m scripts.get_voice
# Hosts that run the container as a non-root user (for example user 1000) still need to write jobs here.
RUN mkdir -p /srv/data && chmod 777 /srv/data

ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
