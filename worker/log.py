"""Registro das requisicoes recebidas pelo servico.

Escreve na saida padrao (e nao em arquivo) porque no container quem coleta o
log e o docker / a plataforma de nuvem. Nunca registra o texto, so o tamanho.
"""
import time


def registrar_requisicao(identificador: str, tamanho_entrada: int,
                         inicio: float, servico: str) -> None:
    """Imprime uma linha com os dados da requisicao (sem dado pessoal)."""
    tempo_ms = round((time.perf_counter() - inicio) * 1000, 2)
    print(f"[{servico}] id={identificador} tamanho_entrada={tamanho_entrada} "
          f"tempo_resposta_ms={tempo_ms}", flush=True)
