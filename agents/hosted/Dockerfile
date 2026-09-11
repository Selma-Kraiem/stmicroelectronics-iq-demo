FROM python:3.13-slim

WORKDIR /app
# Build with repository root as context:
# docker build -f agents/hosted/Dockerfile .
COPY pyproject.toml /app/
COPY app /app/app
COPY agents/hosted /app/agents/hosted
COPY agents/__init__.py /app/agents/__init__.py
COPY data/v1 /app/data/v1
RUN pip install --no-cache-dir ".[hosted]"

WORKDIR /app
EXPOSE 8088
CMD ["python", "-m", "agents.hosted.main"]
