FROM python:3.11-slim

WORKDIR /app

# Install curl and certificates
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY config.yaml .

# Ensure data directory exists
RUN mkdir -p /app/data/photos

EXPOSE 8080

CMD ["python", "-m", "app.main"]
