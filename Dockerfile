FROM mcr.microsoft.com/playwright/python:v1.60.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Garante o navegador casado com a versão do pacote playwright instalado.
# A imagem v1.60.0-jammy já traz o Chromium, mas isto blinda contra divergência futura.
RUN playwright install chromium

COPY . .

RUN mkdir -p /app/data

EXPOSE 8000

ENV HEADLESS=true

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/executions')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
