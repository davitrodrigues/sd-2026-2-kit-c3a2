# vetorial: armazenamento vetorial (do C2.A2), guarda os documentos com os
# vetores tf-idf e devolve os trechos mais parecidos com uma pergunta.
#
# rodar: uvicorn app:app --port 8002
# opcional: DIR_DADOS (pasta do indice) e OTEL_EXPORTER_OTLP_ENDPOINT (jaeger)
import glob
import os
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from opentelemetry import trace
from pydantic import BaseModel, ConfigDict, Field

import armazenamento
import rastreio
from embeddings import Vetorizador, similaridade

# textos da disciplina que vao dentro da imagem
PASTA_DOCUMENTOS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "documentos")

# a indexacao troca o estado inteiro por um novo, sem mexer no antigo, entao
# a busca sempre le um indice completo
ESTADO = {"versao": 0, "documentos": [], "vetorizador": None}
TRAVA = threading.Lock()  # uma indexacao por vez
_tracer = trace.get_tracer("vetorial")


# junta os documentos novos aos do indice e grava a versao nova no disco.
def acrescentar(pares):
    global ESTADO
    with TRAVA:
        atual = ESTADO
        todos = [(d["texto"], d["origem"]) for d in atual["documentos"]]
        vistos = set(todos)
        for par in pares:
            if par not in vistos:  # mesmo texto e origem nao entra de novo
                vistos.add(par)
                todos.append(par)
        novos = len(todos) - len(atual["documentos"])
        if novos:
            # reajusta com todos os textos: o tf-idf muda de tamanho a cada
            # ajuste, e a pergunta tem de usar o vetorizador que gerou os
            # vetores; por isso os dois sao gravados juntos
            vetorizador = Vetorizador()
            vetorizador.ajustar([t for t, _ in todos])
            novo = {"versao": atual["versao"] + 1,
                    "documentos": [{"texto": t, "origem": o,
                                    "vetor": vetorizador.vetorizar(t)}
                                   for t, o in todos],
                    "vetorizador": vetorizador}
            armazenamento.salvar(novo)  # se falhar, o estado nao muda
            ESTADO = novo
        return novos, ESTADO


# le os .txt da imagem; o modo texto ja troca o fim de linha crlf por lf.
def documentos_da_imagem():
    pares = []
    for caminho in sorted(glob.glob(os.path.join(PASTA_DOCUMENTOS, "*.txt"))):
        with open(caminho, encoding="utf-8") as f:
            texto = f.read().strip()
        if texto:
            pares.append((texto, os.path.basename(caminho)))
    return pares


# na subida usa o indice do volume; volume vazio indexa os documentos da
# imagem, para a busca funcionar de cara.
@asynccontextmanager
async def ciclo_de_vida(_app: FastAPI):
    global ESTADO
    salvo = armazenamento.carregar()
    if salvo and salvo["documentos"]:
        ESTADO = salvo
        como = "indice carregado do volume"
    else:
        acrescentar(documentos_da_imagem())
        como = "volume vazio, indice criado com os documentos da imagem"
    print(f"[vetorial] {como}: {len(ESTADO['documentos'])} "
          f"documentos, versao {ESTADO['versao']} ({armazenamento.CAMINHO})",
          flush=True)
    yield


app = FastAPI(title="Armazenamento Vetorial - C3.A2", lifespan=ciclo_de_vida)
# continua o trace que chega do gateway pelo header traceparent
if rastreio.configurar("vetorial"):
    rastreio.instrumentar_fastapi(app)


class Documento(BaseModel):
    texto: str = Field(min_length=1)
    origem: str = "desconhecida"


class Consulta(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    pergunta: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(3, ge=1, le=10)


# diz se o texto tem pelo menos uma palavra que o tf-idf entende.
def tem_vocabulario(texto):
    try:
        Vetorizador().ajustar([texto])
        return True
    except ValueError:
        return False


# healthcheck do container: quantos documentos e qual versao do indice.
@app.get("/saude")
def saude():
    estado = ESTADO
    return {"status": "ok", "documentos": len(estado["documentos"]),
            "versao": estado["versao"]}


# devolve os top_k trechos mais parecidos com a pergunta, do maior score para
# o menor. a pergunta nao vai para o log nem para o span (lgpd).
@app.post("/buscar")
def buscar(consulta: Consulta):
    inicio = time.perf_counter()
    estado = ESTADO  # uma leitura so: indexar no meio nao mistura versoes
    resultados = []
    with _tracer.start_as_current_span("buscar no indice") as span:
        if estado["documentos"]:
            pergunta = estado["vetorizador"].vetorizar(consulta.pergunta)
            achados = [(similaridade(pergunta, d["vetor"]), d)
                       for d in estado["documentos"]]
            # zero e nenhuma palavra em comum, nao e resultado
            achados = sorted((a for a in achados if a[0] > 0),
                             key=lambda a: a[0], reverse=True)
            resultados = [{"texto": d["texto"], "origem": d["origem"],
                           "score": round(s, 4)}
                          for s, d in achados[:consulta.top_k]]
        span.set_attributes({"indice.versao": estado["versao"],
                             "busca.top_k": consulta.top_k,
                             "busca.resultados": len(resultados)})
    ms = (time.perf_counter() - inicio) * 1000
    print(f"[vetorial] buscar top_k={consulta.top_k} "
          f"resultados={len(resultados)} versao={estado['versao']} "
          f"({ms:.1f}ms){rastreio.para_log()}", flush=True)
    return {"resultados": resultados}


# acrescenta documentos sem apagar os que ja estavam. o gateway nao expoe
# esta rota: so quem esta na rede interna alcanca.
@app.post("/indexar")
def indexar(docs: list[Documento]):
    if not docs:
        raise HTTPException(422, "envie ao menos um documento")
    invalidos = [i for i, d in enumerate(docs)
                 if not tem_vocabulario(d.texto)]
    if invalidos:
        raise HTTPException(
            422, f"documentos sem nenhuma palavra de 2 ou mais letras nas "
                 f"posicoes {invalidos}; nada foi indexado")
    try:
        novos, estado = acrescentar([(d.texto, d.origem) for d in docs])
    except OSError as e:
        print(f"[vetorial] falha ao gravar o indice: {type(e).__name__}",
              flush=True)
        raise HTTPException(500, "falha ao gravar o indice; nada mudou")
    print(f"[vetorial] indexar recebidos={len(docs)} novos={novos} "
          f"total={len(estado['documentos'])} versao={estado['versao']}"
          f"{rastreio.para_log()}", flush=True)
    return {"indexados": novos, "ignorados": len(docs) - novos,
            "total": len(estado["documentos"]), "versao": estado["versao"]}
