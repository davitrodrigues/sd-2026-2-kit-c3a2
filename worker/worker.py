# worker (vindo do C1.A2): consome a fila do redis, roda a inferencia e grava
# o resultado. em caso de falha a tarefa volta para a fila; apos 3 tentativas
# vai para a fila de descarte (dead-letter) e o cliente ve status "falhou".
#
# rodar: python worker.py
# ambiente: REDIS_URL
# escala horizontal: docker compose up --scale worker=3
import os
import random
import signal
import time

import redis

import fila
from log import registrar_requisicao
from modelo import carregar_modelo

MAX_TENTATIVAS = 3
# espera progressiva quando o redis cai: 1, 2, 4, 8... ate o teto
ESPERA_REDIS_BASE = float(os.getenv("WORKER_ESPERA_REDIS_BASE", "1"))
ESPERA_REDIS_MAXIMA = float(os.getenv("WORKER_ESPERA_REDIS_MAXIMA", "30"))

_rodando = True


# o docker stop manda SIGTERM; termina a tarefa atual e sai, sem esperar o
# SIGKILL de 10s depois e sem perder a tarefa que estava no meio.
def _parar(_sinal, _quadro):
    global _rodando
    _rodando = False
    print("[worker] sinal de parada recebido, encerrando...", flush=True)


# dorme em passos curtos para o SIGTERM nao esperar a espera inteira.
def _dormir(segundos: float) -> None:
    fim = time.monotonic() + segundos
    while _rodando and time.monotonic() < fim:
        time.sleep(min(0.5, fim - time.monotonic()))


def processar(modelo, tarefa: dict) -> None:
    inicio = time.perf_counter()
    try:
        resultado = modelo.prever(tarefa["texto"])
        # o cliente ja tem o texto; guardar de novo no redis seria dado
        # pessoal sem necessidade (minimizacao, LGPD)
        resultado.pop("texto", None)
        resultado["status"] = "pronto"
        resultado["tempo_ms"] = round((time.perf_counter() - inicio) * 1000, 2)
        fila.guardar_resultado(tarefa["id"], resultado)
    except redis.RedisError:
        # falha da fila, nao da tarefa: reenfileirar tambem falharia, entao
        # sobe para o laco principal esperar o redis voltar
        print(f"[worker] redis caiu durante {tarefa['id']}; tarefa perdida "
              f"(entrega no maximo uma vez)", flush=True)
        raise
    except Exception as erro:  # noqa: BLE001
        tarefa["tentativas"] = tarefa.get("tentativas", 0) + 1
        if tarefa["tentativas"] < MAX_TENTATIVAS:
            print(f"[worker] ERRO em {tarefa['id']}: {erro} "
                  f"(tentativa {tarefa['tentativas']} de {MAX_TENTATIVAS}, "
                  f"voltando para a fila)", flush=True)
            fila.reenfileirar(tarefa)
        else:
            print(f"[worker] DESCARTE de {tarefa['id']} apos "
                  f"{tarefa['tentativas']} tentativas: {erro}", flush=True)
            fila.descartar(tarefa, str(erro))
            fila.guardar_resultado(tarefa["id"], {
                "status": "falhou",
                "erro": str(erro),
                "tentativas": tarefa["tentativas"],
            })
    finally:
        registrar_requisicao(tarefa["id"], len(tarefa["texto"]), inicio,
                             "worker")


def main():
    signal.signal(signal.SIGTERM, _parar)
    signal.signal(signal.SIGINT, _parar)

    print("[worker] carregando modelo...", flush=True)
    modelo = carregar_modelo()
    print("[worker] pronto. aguardando tarefas", flush=True)

    falhas_seguidas = 0
    while _rodando:
        try:
            # timeout curto para checar _rodando com frequencia
            tarefa = fila.proxima_tarefa()
            if tarefa is not None:
                processar(modelo, tarefa)
        except redis.RedisError as erro:
            # em vez de morrer (e o container reiniciar em loop), espera cada
            # vez mais, com jitter para os workers nao voltarem todos juntos
            falhas_seguidas += 1
            espera = min(ESPERA_REDIS_MAXIMA,
                         ESPERA_REDIS_BASE * 2 ** (falhas_seguidas - 1))
            espera = random.uniform(espera / 2, espera)
            print(f"[worker] redis indisponivel ({type(erro).__name__}), "
                  f"falha {falhas_seguidas}; nova tentativa em {espera:.1f}s",
                  flush=True)
            _dormir(espera)
            continue
        if falhas_seguidas:
            print("[worker] redis de volta, retomando", flush=True)
            falhas_seguidas = 0

    print("[worker] encerrado", flush=True)


if __name__ == "__main__":
    main()
