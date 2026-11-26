FROM python:3.12-slim

# sem .pyc no disco e log saindo na hora (sem buffer) para o docker logs;
# DIR_DADOS e onde o compose monta o volume do indice
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DIR_DADOS=/app/dados

WORKDIR /app

# dependencias antes do codigo: mudar o codigo nao reinstala tudo (cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# o codigo e os documentos/*.txt que indexam um volume vazio
COPY . .

# nao roda como root dentro do container; a pasta de dados ja nasce do
# usuario app, e o volume novo herda esse dono na primeira montagem
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /app/dados && chown app /app/dados
USER app

EXPOSE 8002

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8002/saude', timeout=2)" || exit 1

# sem o access log do uvicorn: ele grava o ip de quem chama (LGPD);
# o app.py ja registra top_k, quantos resultados e o tempo, sem a pergunta
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8002", "--no-access-log"]
