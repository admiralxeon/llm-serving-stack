FROM python:3.12.16-slim-bookworm

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .

# Don't run the app as root inside the container.
RUN useradd --create-home app
USER app

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
