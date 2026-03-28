# Department 1: Gateway Service
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY pyproject.toml .
COPY lib/ ./lib/
COPY department_1/ ./department_1/

# Install Python dependencies
RUN pip install --no-cache-dir \
    fastapi>=0.110.0 \
    uvicorn[standard]>=0.27.0 \
    pydantic>=2.6.0 \
    pydantic-settings>=2.2.0 \
    aiomqtt>=2.0.0 \
    httpx>=0.27.0 \
    redis>=5.0.0 \
    elasticsearch>=8.12.0 \
    python-json-logger>=2.0.7 \
    structlog>=24.1.0 \
    tenacity>=8.2.3 \
    orjson>=3.9.0 \
    python-dotenv>=1.0.0

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run application
CMD ["uvicorn", "department_1.src.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
