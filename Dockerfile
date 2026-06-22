FROM mcr.microsoft.com/playwright/python:latest

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data

EXPOSE 8000

ENV HEADLESS=true

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
