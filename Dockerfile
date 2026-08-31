FROM python:3.13-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
COPY README.md main.py ./
COPY src/ src/

RUN uv sync --frozen --no-dev

# Default for manual runs; the EventBridge schedule overrides this via
# containerOverrides. One daily snapshot, no arguments needed.
CMD ["uv", "run", "main.py"]
