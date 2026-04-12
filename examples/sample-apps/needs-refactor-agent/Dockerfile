FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY agent.py .

EXPOSE 8080

# NOTE: No HEALTHCHECK — this is intentional (C4 violation)

CMD ["python", "agent.py"]
