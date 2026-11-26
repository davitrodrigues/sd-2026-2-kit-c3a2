# gateway: porta de entrada unica, confere o token, limita o ritmo de cada
# cliente e repassa para a inferencia.
#
# rodar: uvicorn app:app --port 8000
# obrigatorias no ambiente: JWT_SEGREDO, GATEWAY_USUARIO e GATEWAY_SENHA
# opcional: OTEL_EXPORTER_OTLP_ENDPOINT liga o rastreamento (jaeger)
import hashlib
import hmac
import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import redis
import requests
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from pydantic import BaseModel

import rastreio
from resiliencia import (CircuitBreaker, CircuitoAberto, FalhaTransitoria,
                         com_retentativa)

log = logging.getLogger("uvicorn.error")


# le uma variavel obrigatoria e recusa subir sem ela, em vez de usar um padrao.
def _env_obrigatoria(nome: str) -> str:
    valor = os.getenv(nome)
    if not valor or not valor.strip():
        raise RuntimeError(f"variavel de ambiente obrigatoria ausente: {nome}")
    return valor


app = FastAPI(title="Gateway - C3.A2")
# o requests instrumentado leva o traceparent no header ate a inferencia
if rastreio.configurar("gateway"):
    rastreio.instrumentar_fastapi(app)
    RequestsInstrumentor().instrument()
URL_INFERENCIA = os.getenv("URL_INFERENCIA", "http://localhost:8001")

# resiliencia da chamada a inferencia (Aula 11). tempo-limite separado: abrir
# a conexao e rapido numa rede interna, entao espera pouco; ler da mais folga.
TIMEOUT_INFERENCIA = (float(os.getenv("INFERENCIA_TIMEOUT_CONEXAO", "1")),
                      float(os.getenv("INFERENCIA_TIMEOUT_LEITURA", "3")))
INFERENCIA_TENTATIVAS = int(os.getenv("INFERENCIA_TENTATIVAS", "3"))
INFERENCIA_ESPERA_BASE = float(os.getenv("INFERENCIA_ESPERA_BASE", "0.2"))
disjuntor_inferencia = CircuitBreaker(
    limite_falhas=int(os.getenv("DISJUNTOR_LIMITE_FALHAS", "3")),
    espera_segundos=float(os.getenv("DISJUNTOR_ESPERA_SEGUNDOS", "15")),
    conta_como_falha=(FalhaTransitoria,), nome="disjuntor-inferencia")

JWT_SEGREDO = _env_obrigatoria("JWT_SEGREDO")
GATEWAY_USUARIO = _env_obrigatoria("GATEWAY_USUARIO")
GATEWAY_SENHA = _env_obrigatoria("GATEWAY_SENHA")
JWT_EXPIRA_MINUTOS = int(os.getenv("JWT_EXPIRA_MINUTOS", "30"))
JWT_ALGORITMO = "HS256"

LIMITE_POR_MINUTO = int(os.getenv("LIMITE_POR_MINUTO", "10"))
LIMITE_LOGIN_POR_MINUTO = int(os.getenv("LIMITE_LOGIN_POR_MINUTO", "5"))
JANELA_SEGUNDOS = 60
# contador no redis, e nao em memoria, para valer igual em todas as replicas.
_redis = redis.Redis.from_url(
    os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    # curto para um redis lento ou fora do ar nao segurar a requisicao
    socket_connect_timeout=0.5, socket_timeout=0.5)
# derivada do segredo do jwt para nao usar a mesma chave em duas funcoes.
_CHAVE_APELIDO = hmac.new(JWT_SEGREDO.encode(), b"limite",
                          hashlib.sha256).digest()


class Entrada(BaseModel):
    texto: str


class Credenciais(BaseModel):
    usuario: str
    senha: str


# auto_error=False porque o padrao do fastapi e 403 e o enunciado pede 401.
_bearer = HTTPBearer(auto_error=False)


# monta o 401 com o header que diz ao cliente para mandar um bearer.
def _nao_autorizado(motivo: str) -> HTTPException:
    return HTTPException(status_code=401, detail=motivo,
                         headers={"WWW-Authenticate": "Bearer"})


# confere o token do header e devolve o usuario dono dele.
def usuario_atual(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    if cred is None:  # header ausente, vazio ou sem o esquema bearer
        raise _nao_autorizado("token ausente")
    try:
        dados = jwt.decode(
            cred.credentials,
            JWT_SEGREDO,
            # lista fixa para nao aceitar alg none nem troca de algoritmo
            algorithms=[JWT_ALGORITMO],
            # sem exp o token seria eterno, e sem sub nao se sabe quem e
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.ExpiredSignatureError:
        raise _nao_autorizado("token expirado")
    except jwt.InvalidTokenError:
        # generica de proposito, o motivo exato ajudaria a forjar um token
        raise _nao_autorizado("token invalido")
    return dados["sub"]


# ip de quem chamou, a chave do limite no /login, onde ainda nao ha usuario.
def ip_do_cliente(request: Request) -> str:
    return request.client.host if request.client else "desconhecido"


# troca ip ou usuario por um apelido, para o redis nao guardar dado pessoal.
def _apelido(cliente: str) -> str:
    # com segredo porque o sha puro de um ipv4 se desfaz testando todos os ips
    return hmac.new(_CHAVE_APELIDO, cliente.encode(),
                    hashlib.sha256).hexdigest()


# monta uma dependencia que deixa cada cliente fazer ate maximo por minuto.
def limitar(escopo: str, maximo: int, cliente_de):

    # conta esta requisicao do cliente e barra com 429 quem passou do maximo.
    def dependencia(response: Response, cliente: str = Depends(cliente_de)):
        agora = int(time.time())
        # o numero da janela na chave zera a contagem quando o minuto vira
        janela = agora // JANELA_SEGUNDOS
        chave = f"limite:{escopo}:{_apelido(cliente)}:{janela}"
        try:
            # incr e expire na mesma transacao, entao nunca sobra chave sem ttl
            contagem, _ = (_redis.pipeline().incr(chave)
                           .expire(chave, JANELA_SEGUNDOS).execute())
        except redis.RedisError as e:
            # fail-open porque o limite protege o sistema, nao e a funcao dele
            log.warning("redis indisponivel, passou sem limite: %s", e)
            return
        cabecalhos = {"X-RateLimit-Limit": str(maximo),
                      "X-RateLimit-Remaining": str(max(maximo - contagem, 0))}
        if contagem > maximo:
            cabecalhos["Retry-After"] = str(
                JANELA_SEGUNDOS - agora % JANELA_SEGUNDOS)
            raise HTTPException(status_code=429, headers=cabecalhos,
                                detail="limite de requisicoes excedido")
        response.headers.update(cabecalhos)

    return dependencia


# o do usuario roda depois do token, entao sem token e 401 e nao gasta cota.
limite_por_usuario = limitar("usuario", LIMITE_POR_MINUTO, usuario_atual)
limite_por_ip = limitar("login", LIMITE_LOGIN_POR_MINUTO, ip_do_cliente)


# loga metodo, rota e status de cada requisicao, nunca senha nem token.
@app.middleware("http")
async def registrar(request: Request, call_next):
    inicio = time.time()
    resposta = await call_next(request)
    ms = (time.time() - inicio) * 1000
    print(f"[gateway] {request.method} {request.url.path} "
          f"-> {resposta.status_code} ({ms:.1f}ms){rastreio.para_log()}")
    return resposta


# rota publica de proposito, porque e o healthcheck do deploy.
@app.get("/saude")
def saude():
    # o gateway esta de pe mesmo com a inferencia fora; o estado do disjuntor
    # so informa (fechado, aberto ou meio), nao derruba o healthcheck.
    return {"status": "ok", "disjuntor_inferencia": disjuntor_inferencia.estado}


# confere usuario e senha e devolve um token, com poucas tentativas por ip.
@app.post("/login", dependencies=[Depends(limite_por_ip)])
def login(credenciais: Credenciais):
    # os dois sempre e em tempo constante, em bytes pois str so aceita ascii
    usuario_ok = hmac.compare_digest(credenciais.usuario.encode(),
                                     GATEWAY_USUARIO.encode())
    senha_ok = hmac.compare_digest(credenciais.senha.encode(),
                                   GATEWAY_SENHA.encode())
    if not (usuario_ok and senha_ok):
        raise _nao_autorizado("usuario ou senha invalidos")

    agora = datetime.now(timezone.utc)
    token = jwt.encode(
        {"sub": credenciais.usuario,
         "iat": agora,
         "exp": agora + timedelta(minutes=JWT_EXPIRA_MINUTOS)},
        JWT_SEGREDO,
        algorithm=JWT_ALGORITMO,
    )
    return {"access_token": token, "token_type": "bearer",
            "expira_em": JWT_EXPIRA_MINUTOS * 60}


# uma tentativa so; rede, tempo-limite e 5xx viram falha transitoria.
def _uma_chamada(metodo: str, caminho: str, **kwargs) -> requests.Response:
    try:
        r = requests.request(metodo, f"{URL_INFERENCIA}{caminho}",
                             timeout=TIMEOUT_INFERENCIA, **kwargs)
    except requests.RequestException as e:
        raise FalhaTransitoria(type(e).__name__) from e
    if r.status_code >= 500:
        raise FalhaTransitoria(f"http {r.status_code}")
    return r


# chama a inferencia com tempo-limite, retentativa e disjuntor. o disjuntor
# fica por fora: a sequencia inteira de tentativas conta como uma falha so, e
# com ele aberto nem tenta, responde 503 na hora (falha rapida).
def _chamar_inferencia(metodo: str, caminho: str, **kwargs) -> dict:
    try:
        r = disjuntor_inferencia.chamar(
            com_retentativa, lambda: _uma_chamada(metodo, caminho, **kwargs),
            tentativas=INFERENCIA_TENTATIVAS,
            espera_base=INFERENCIA_ESPERA_BASE, nome="inferencia")
    except CircuitoAberto as e:
        raise HTTPException(
            status_code=503, detail="servico de inferencia indisponivel",
            headers={"Retry-After": str(max(1, int(e.restante + 0.999)))})
    except FalhaTransitoria:
        # o detalhe tecnico (endereco interno) fica so no log
        raise HTTPException(status_code=503,
                            detail="servico de inferencia indisponivel")
    if r.status_code >= 400:  # erro do cliente (4xx) volta igual
        try:
            detalhe = r.json().get("detail", r.reason)
        except ValueError:
            detalhe = r.reason
        raise HTTPException(status_code=r.status_code, detail=detalhe)
    return r.json()


# repassa o texto para a fila da inferencia e devolve o id (202, assincrono).
# o id e gerado aqui e vai junto: se uma retentativa repetir um POST que ja
# tinha chegado, a inferencia reconhece o id e nao enfileira duas vezes.
@app.post("/predict", status_code=202,
          dependencies=[Depends(limite_por_usuario)])
def predict(entrada: Entrada, usuario: str = Depends(usuario_atual)):
    return _chamar_inferencia(
        "POST", "/predict",
        json={"texto": entrada.texto, "id": str(uuid.uuid4())})


# consulta o resultado de uma tarefa pelo id devolvido no /predict.
# o tipo uuid barra com 422 qualquer id malformado antes de chegar na rede.
@app.get("/resultado/{tarefa_id}",
         dependencies=[Depends(limite_por_usuario)])
def resultado(tarefa_id: uuid.UUID, usuario: str = Depends(usuario_atual)):
    return _chamar_inferencia("GET", f"/resultado/{tarefa_id}")
