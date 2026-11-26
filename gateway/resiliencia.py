# resiliencia das chamadas do gateway (Aula 11): retentativa com espera
# progressiva e disjuntor (circuit breaker). o tempo-limite fica no requests.
#
# disjuntor trazido do C2.A2: fechado deixa passar tudo, aberto recusa na hora
# sem tentar, e meio deixa so uma chamada de teste passar para ver se voltou.
import logging
import random
import threading
import time

log = logging.getLogger("uvicorn.error")


# falha que vale a pena tentar de novo: rede, tempo-limite ou 5xx.
class FalhaTransitoria(Exception):

    # retry_after e o que o servico pediu para esperar, quando ele disse.
    def __init__(self, mensagem="", retry_after=None):
        super().__init__(mensagem)
        self.retry_after = retry_after


# erro de quando o disjuntor recusa a chamada; diz quanto falta para o teste.
class CircuitoAberto(Exception):

    def __init__(self, mensagem="disjuntor aberto: chamada recusada",
                 restante=0.0):
        super().__init__(mensagem)
        self.restante = restante


class CircuitBreaker:

    # so os erros da lista contam como falha; o resto passa sem contar.
    def __init__(self, limite_falhas=5, espera_segundos=30,
                 conta_como_falha=(Exception,), nome="disjuntor"):
        self.limite_falhas = limite_falhas
        self.espera_segundos = espera_segundos
        self.conta_como_falha = conta_como_falha
        self.nome = nome
        self.falhas = 0
        self._estado = "fechado"
        self.aberto_em = 0.0
        self._teste = None  # marca da chamada de teste que esta rodando
        self._trava = threading.Lock()  # so uma thread mexe no estado

    # le o estado ja contando a espera, mesmo que ninguem tenha chamado.
    @property
    def estado(self):
        with self._trava:
            self._conferir_espera()
            return self._estado

    def chamar(self, funcao, *args, **kwargs):
        with self._trava:
            self._conferir_espera()
            if self._estado == "aberto":
                raise CircuitoAberto(
                    f"{self.nome} aberto: chamada recusada",
                    self.espera_segundos
                    - (time.monotonic() - self.aberto_em))
            teste = None
            if self._estado == "meio":
                if self._teste is not None:
                    raise CircuitoAberto(
                        f"{self.nome} em teste: chamada recusada",
                        self.espera_segundos)
                teste = self._teste = object()
        try:
            resultado = funcao(*args, **kwargs)
        except self.conta_como_falha:
            self._registrar_falha(teste)
            raise
        except BaseException:
            # erro que nao e do servico: so libera a vaga de teste
            with self._trava:
                if teste is not None and self._teste is teste:
                    self._teste = None
            raise
        self._registrar_sucesso()
        return resultado

    # passada a espera, o aberto vira meio e libera uma chamada de teste.
    def _conferir_espera(self):
        if (self._estado == "aberto"
                and time.monotonic() - self.aberto_em
                >= self.espera_segundos):
            self._estado = "meio"
            log.info("%s: espera acabou, deixa uma chamada de teste",
                     self.nome)

    def _registrar_falha(self, teste):
        with self._trava:
            self.falhas += 1
            if self.falhas >= self.limite_falhas or self._estado == "meio":
                if teste is not None:
                    log.warning("%s: chamada de teste falhou, aberto de novo",
                                self.nome)
                elif self._estado == "fechado":
                    log.warning("%s: aberto apos %d falhas seguidas",
                                self.nome, self.falhas)
                self._estado = "aberto"
                self.aberto_em = time.monotonic()
                self._teste = None

    def _registrar_sucesso(self):
        with self._trava:
            if self._estado != "fechado":
                log.info("%s: servico respondeu, fechado de novo", self.nome)
            self.falhas = 0
            self._estado = "fechado"
            self._teste = None


# tenta de novo so em falha transitoria, esperando base, 2*base, 4*base...
# (ate o teto), com jitter para varios clientes nao voltarem todos juntos.
def com_retentativa(funcao, *, tentativas=3, espera_base=0.2,
                    espera_maxima=2.0, nome="chamada"):
    for tentativa in range(1, tentativas + 1):
        try:
            return funcao()
        except FalhaTransitoria as e:
            if tentativa == tentativas:
                log.warning("%s: tentativa %d/%d falhou (%s); desistindo",
                            nome, tentativa, tentativas, e)
                raise
            espera = min(espera_maxima, espera_base * 2 ** (tentativa - 1))
            espera = random.uniform(espera / 2, espera)  # jitter
            log.warning("%s: tentativa %d/%d falhou (%s); nova em %.2fs",
                        nome, tentativa, tentativas, e, espera)
            time.sleep(espera)
