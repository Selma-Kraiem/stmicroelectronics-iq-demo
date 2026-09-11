FROM python:3.13-slim

WORKDIR /app
COPY pyproject.toml /app/
COPY app /app/app
COPY v2 /app/v2
RUN pip install --no-cache-dir ".[hosted]"

EXPOSE 8088
CMD ["python", "-m", "v2.agents.entrypoint"]
