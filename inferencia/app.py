# servico de inferencia (vindo do C1.A2): recebe o texto do gateway, coloca na
# fila e devolve o id; o worker processa depois e grava o resultado no redis.
#
# rodar: uvicorn app:app --port 8001
# ambiente: REDIS_URL
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import fila
from log import registrar_requisicao
from modelo import carregar_modelo

modelo = None


# carrega o modelo uma vez so, na subida, e nao a cada requisicao (Aula 6).
@asynccontextmanager
async def ciclo_de_vida(_app: FastAPI):
    global modelo
    inicio = time.perf_counter()
    modelo = carregar_modelo()
    print(f"[inferencia] modelo carregado em "
          f"{time.perf_counter() - inicio:.3f}s", flush=True)
    yield


app = FastAPI(title="Servico de Inferencia - C3.A2", lifespan=ciclo_de_vida)


class Entrada(BaseModel):
    texto: str


@app.get("/saude")
def saude():
    return {"status": "ok", "modelo_carregado": modelo is not None}


# inferencia sincrona: o cliente espera a resposta.
@app.post("/predict-sync")
def predict_sync(entrada: Entrada):
    inicio = time.perf_counter()
    try:
        if not entrada.texto.strip():
            raise HTTPException(status_code=400, detail="texto vazio")
        resultado = modelo.prever(entrada.texto)
        resultado["tempo_ms"] = round((time.perf_counter() - inicio) * 1000, 2)
        return resultado
    finally:
        registrar_requisicao(str(uuid.uuid4()), len(entrada.texto), inicio,
                             "inferencia")


# submissao assincrona: enfileira e devolve o id sem esperar a inferencia.
@app.post("/predict", status_code=202)
def predict(entrada: Entrada):
    inicio = time.perf_counter()
    identificador = "-"
    try:
        if not entrada.texto.strip():
            raise HTTPException(status_code=400, detail="texto vazio")
        identificador = fila.enfileirar(entrada.texto)
        return {"id": identificador}
    finally:
        registrar_requisicao(identificador, len(entrada.texto), inicio,
                             "inferencia")


# consulta do resultado; 404 se o id nao existir.
@app.get("/resultado/{tarefa_id}")
def resultado(tarefa_id: str):
    inicio = time.perf_counter()
    try:
        retorno = fila.buscar_resultado(tarefa_id)
        if retorno is None:
            raise HTTPException(status_code=404, detail="tarefa nao encontrada")
        return retorno
    finally:
        registrar_requisicao(tarefa_id, 0, inicio, "inferencia")
