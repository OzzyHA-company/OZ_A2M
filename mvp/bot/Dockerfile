FROM python:3.12-slim

WORKDIR /app

# Security: Run as non-root
RUN groupadd -r botuser && useradd -r -g botuser botuser

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot code
COPY scalping_bot.py .

# Set permissions
RUN chown -R botuser:botuser /app

USER botuser

# Run bot
CMD ["python", "scalping_bot.py"]
