# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the bot script
COPY otp.py .

# Create data directory with proper permissions
RUN mkdir -p /app/data && chmod 700 /app/data

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Run the bot
CMD ["python", "otp.py"]
