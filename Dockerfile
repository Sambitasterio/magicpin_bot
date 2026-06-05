FROM python:3.12-slim

WORKDIR /app

# Install deps first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code + dataset
COPY app ./app
COPY bot.py conversation_handlers.py ./
COPY data ./data

ENV PORT=8080
EXPOSE 8080

# OPENAI_API_KEY is provided at runtime (do NOT bake it into the image)
CMD ["sh", "-c", "uvicorn app.server:app --host 0.0.0.0 --port ${PORT}"]
