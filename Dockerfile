# IRIS PostgreSQL Wire Protocol Server - Production Container
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast Python package management
RUN pip install uv

# Copy application source and build files (needed for version detection)
COPY src/ ./src/
COPY examples/ ./examples/
COPY LICENSE ./
COPY README.md ./

# Copy requirements and install dependencies
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash pgwire
RUN chown -R pgwire:pgwire /app
USER pgwire

# Environment variables with defaults
ENV PGWIRE_HOST=0.0.0.0
ENV PGWIRE_PORT=5432
ENV IRIS_HOST=iris
ENV IRIS_PORT=1972
ENV IRIS_USERNAME=SuperUser
ENV IRIS_PASSWORD=SYS
ENV IRIS_NAMESPACE=USER
ENV PGWIRE_SSL_ENABLED=false
ENV PGWIRE_DEBUG=false

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import socket; s=socket.socket(); s.settimeout(5); s.connect(('localhost', int('${PGWIRE_PORT}'))); s.close()" || exit 1

# Expose PostgreSQL port
EXPOSE 5432

# Run the server using uv to ensure virtualenv is active
CMD [".venv/bin/python", "-m", "iris_pgwire.server"]