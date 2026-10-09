FROM python:3.12-slim

LABEL org.opencontainers.image.authors="Marcelo Araujo"

WORKDIR /app
COPY aiops.py ./aiops.py
COPY aiops.config.example.json ./aiops.config.example.json

RUN useradd --create-home --uid 10001 appuser
USER appuser

ENTRYPOINT ["python", "aiops.py"]
