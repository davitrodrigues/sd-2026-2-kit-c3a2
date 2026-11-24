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

# sem EXPOSE: o worker nao recebe conexao, so consome a fila do redis
CMD ["python", "worker.py"]
