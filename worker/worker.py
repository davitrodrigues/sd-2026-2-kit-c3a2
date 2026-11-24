# worker (vindo do C1.A2): consome a fila do redis, roda a inferencia e grava
# o resultado. em caso de falha a tarefa volta para a fila; apos 3 tentativas
# vai para a fila de descarte (dead-letter) e o cliente ve status "falhou".
#
# rodar: python worker.py
# ambiente: REDIS_URL
# escala horizontal: docker compose up --scale worker=3
import signal
import time

import fila
from log import registrar_requisicao
from modelo import carregar_modelo

MAX_TENTATIVAS = 3

_rodando = True


# o docker stop manda SIGTERM; termina a tarefa atual e sai, sem esperar o
# SIGKILL de 10s depois e sem perder a tarefa que estava no meio.
def _parar(_sinal, _quadro):
    global _rodando
    _rodando = False
    print("[worker] sinal de parada recebido, encerrando...", flush=True)


def processar(modelo, tarefa: dict) -> None:
    inicio = time.perf_counter()
    try:
        resultado = modelo.prever(tarefa["texto"])
        resultado["status"] = "pronto"
        resultado["tempo_ms"] = round((time.perf_counter() - inicio) * 1000, 2)
        fila.guardar_resultado(tarefa["id"], resultado)
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

    while _rodando:
        # timeout curto para checar _rodando com frequencia
        tarefa = fila.proxima_tarefa(timeout=2)
        if tarefa is not None:
            processar(modelo, tarefa)

    print("[worker] encerrado", flush=True)


if __name__ == "__main__":
    main()
