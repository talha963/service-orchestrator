# Use official lightweight Python image
FROM python:3.10-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PORT=7860

# Set work directory
WORKDIR /app

# Create a non-root user (Hugging Face requires running as user 1000)
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

# Copy requirements and install
COPY --chown=user:user requirements.txt .
RUN pip install --no-cache-dir --upgrade -r requirements.txt

# Copy project files
COPY --chown=user:user . .

# Expose Hugging Face default port
EXPOSE 7860

# Command to run the FastAPI app
CMD ["sh", "-c", "uvicorn orchestrator:app --host 0.0.0.0 --port $PORT"]
