FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium and all its system dependencies
RUN playwright install chromium --with-deps

COPY . .

CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
