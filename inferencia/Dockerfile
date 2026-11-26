FROM python:3.12-slim

# sem .pyc no disco e log saindo na hora (sem buffer) para o docker logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# dependencias antes do codigo: mudar o codigo nao reinstala tudo (cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# treina o modelo no build: a imagem ja sai pronta e a subida fica rapida
RUN python modelo.py

# nao roda como root dentro do container
RUN useradd --create-home --uid 10001 app
USER app

EXPOSE 8001

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/saude', timeout=2)" || exit 1

# sem o access log do uvicorn: ele grava o ip de quem chama (LGPD);
# o log.py ja registra id, tamanho da entrada e tempo
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001", "--no-access-log"]
