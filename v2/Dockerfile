FROM python:3.13-slim

WORKDIR /app
COPY pyproject.toml /app/
COPY app /app/app
COPY v2 /app/v2
RUN pip install --no-cache-dir ".[cloud]"

EXPOSE 8000
CMD ["uvicorn", "v2.main:app", "--host", "0.0.0.0", "--port", "8000"]
