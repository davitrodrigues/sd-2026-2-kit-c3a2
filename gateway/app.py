# gateway: porta de entrada unica, confere o token e repassa para a inferencia.
#
# rodar: uvicorn app:app --port 8000
# obrigatorias no ambiente: JWT_SEGREDO, GATEWAY_USUARIO e GATEWAY_SENHA
import hmac
import os
import time
from datetime import datetime, timedelta, timezone

import jwt
import requests
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel


# le uma variavel obrigatoria e recusa subir sem ela, em vez de usar um padrao.
def _env_obrigatoria(nome: str) -> str:
    valor = os.getenv(nome)
    if not valor or not valor.strip():
        raise RuntimeError(f"variavel de ambiente obrigatoria ausente: {nome}")
    return valor


app = FastAPI(title="Gateway - C3.A2")
URL_INFERENCIA = os.getenv("URL_INFERENCIA", "http://localhost:8001")

JWT_SEGREDO = _env_obrigatoria("JWT_SEGREDO")
GATEWAY_USUARIO = _env_obrigatoria("GATEWAY_USUARIO")
GATEWAY_SENHA = _env_obrigatoria("GATEWAY_SENHA")
JWT_EXPIRA_MINUTOS = int(os.getenv("JWT_EXPIRA_MINUTOS", "30"))
JWT_ALGORITMO = "HS256"


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


# loga metodo, rota e status de cada requisicao, nunca senha nem token.
@app.middleware("http")
async def registrar(request: Request, call_next):
    inicio = time.time()
    resposta = await call_next(request)
    ms = (time.time() - inicio) * 1000
    print(f"[gateway] {request.method} {request.url.path} "
          f"-> {resposta.status_code} ({ms:.1f}ms)")
    return resposta


# rota publica de proposito, porque e o healthcheck do deploy.
@app.get("/saude")
def saude():
    return {"status": "ok"}


# confere usuario e senha e devolve um token com validade.
@app.post("/login")
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


# repassa o texto para a inferencia, so para quem tem token valido.
@app.post("/predict")
def predict(entrada: Entrada, usuario: str = Depends(usuario_atual)):
    # tarefa 2: rate limit por cliente, com usuario como chave
    try:
        r = requests.post(f"{URL_INFERENCIA}/predict",
                          json=entrada.model_dump(), timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        raise HTTPException(status_code=503,
                            detail=f"servico de inferencia indisponivel: {e}")
