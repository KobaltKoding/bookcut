FROM python:3.11-slim

# Install system dependencies and Node.js (for epub2md)
# We use a multi-stage build or just install node in one go.
# Installing nodejs 18.x
RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y nodejs \
    && npm install -g epub2md \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy project files
COPY . .

# Install Python dependencies
# We install directly from requirements or pyproject.toml
# For simplicity, we just do a pip install -e .
RUN pip install --no-cache-dir -e .
RUN pip install --no-cache-dir fastapi uvicorn

# Environment variables
ENV BOOKCUT_DIR=/data
ENV PORT=8000

# Expose port
EXPOSE 8000

# Create volume mount point
VOLUME /data

# Run command
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
