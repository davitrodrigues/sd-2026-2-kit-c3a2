"""
Auxiliares de fila (Redis), vindos do C1.A2.

A fila guarda tarefas pendentes e os resultados prontos.
Conceito da Aula 8: quem pede nao espera; um worker processa depois.

Resiliencia (Aula 11): o cliente tem tempo-limite curto e tenta de novo, com
espera progressiva, em erro de conexao; quem chama recebe redis.RedisError
se o redis continuar fora depois disso.
"""
import json
import os
import uuid

import redis
from redis.backoff import ExponentialBackoff
from redis.retry import Retry

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_TIMEOUT = float(os.getenv("REDIS_TIMEOUT", "1"))
REDIS_TENTATIVAS = int(os.getenv("REDIS_TENTATIVAS", "1"))
FILA_TAREFAS = "tarefas"
FILA_DESCARTE = "tarefas:descarte"
PREFIXO_RESULTADO = "resultado:"

# so enfileira se o id ainda nao existe, tudo atomico dentro do redis: assim
# um pedido repetido (retentativa do gateway) nao gera tarefa duplicada.
_ENFILEIRAR_UMA_VEZ = """
if redis.call('SET', KEYS[1], ARGV[1], 'NX') then
  redis.call('RPUSH', KEYS[2], ARGV[2])
  return 1
end
return 0
"""

ESPERA_FILA = 2  # segundos que o blpop do worker espera por uma tarefa

_cliente = None
_cliente_bloqueante = None


def _novo_cliente(timeout_leitura: float):
    return redis.from_url(
        REDIS_URL, decode_responses=True,
        socket_connect_timeout=REDIS_TIMEOUT,
        socket_timeout=timeout_leitura,
        # espera 0.1, 0.2, 0.4... (teto 2s) entre as tentativas
        retry=Retry(ExponentialBackoff(cap=2, base=0.1), REDIS_TENTATIVAS),
        retry_on_error=[redis.ConnectionError, redis.TimeoutError],
        health_check_interval=30,
    )


# comandos normais: tempo-limite curto, para um redis travado virar erro
# rapido (e 503 no gateway) em vez de segurar a requisicao.
def cliente():
    global _cliente
    if _cliente is None:
        _cliente = _novo_cliente(REDIS_TIMEOUT)
    return _cliente


# so o blpop do worker: a leitura precisa de folga alem da espera da fila,
# senao uma fila vazia pareceria um redis lento.
def cliente_bloqueante():
    global _cliente_bloqueante
    if _cliente_bloqueante is None:
        _cliente_bloqueante = _novo_cliente(REDIS_TIMEOUT + ESPERA_FILA)
    return _cliente_bloqueante


def enfileirar(texto: str, tarefa_id: str | None = None) -> str:
    """Coloca uma tarefa na fila e devolve o id para consulta posterior.

    Com o mesmo tarefa_id, chamar de novo nao enfileira outra vez (idempotente).
    """
    tarefa_id = tarefa_id or str(uuid.uuid4())
    cliente().eval(
        _ENFILEIRAR_UMA_VEZ, 2,
        PREFIXO_RESULTADO + tarefa_id, FILA_TAREFAS,
        json.dumps({"status": "na_fila"}),
        json.dumps({"id": tarefa_id, "texto": texto}))
    return tarefa_id


def proxima_tarefa():
    """Bloqueia ate chegar tarefa (ou ESPERA_FILA). Usado pelo worker."""
    item = cliente_bloqueante().blpop(FILA_TAREFAS, timeout=ESPERA_FILA)
    if item is None:
        return None
    return json.loads(item[1])


def guardar_resultado(tarefa_id: str, resultado: dict) -> None:
    cliente().set(PREFIXO_RESULTADO + tarefa_id, json.dumps(resultado))


def buscar_resultado(tarefa_id: str):
    bruto = cliente().get(PREFIXO_RESULTADO + tarefa_id)
    return json.loads(bruto) if bruto else None


def reenfileirar(tarefa: dict) -> None:
    """Devolve a tarefa para o fim da fila, para o worker tentar de novo."""
    cliente().rpush(FILA_TAREFAS, json.dumps(tarefa))


def descartar(tarefa: dict, erro: str) -> None:
    """Manda a tarefa para a fila de descarte, com o motivo da falha."""
    cliente().rpush(FILA_DESCARTE, json.dumps({"tarefa": tarefa, "erro": erro}))


def tamanho_descarte() -> int:
    return cliente().llen(FILA_DESCARTE)
