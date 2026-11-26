# rastreio: rastreamento distribuido (Aula 15), manda os spans por otlp para
# o jaeger; o mesmo arquivo em gateway, inferencia e worker.
#
# so liga com OTEL_EXPORTER_OTLP_ENDPOINT definido; sem ele (deploy sem
# jaeger) nada e configurado e todo span vira no-op, sem custo nem erro.
import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (BatchSpanProcessor, SpanExporter,
                                            SpanExportResult)

# o que a instrumentacao automatica grava sobre quem chamou (ip, porta e
# navegador), nas convencoes antiga e nova; e dado pessoal (lgpd)
_DADO_PESSOAL = frozenset({
    "net.peer.ip", "net.peer.port", "client.address", "client.port",
    "http.client_ip", "http.user_agent", "user_agent.original"})


# o mesmo span, visto sem os atributos de dado pessoal.
class _SpanSemDadoPessoal:

    def __init__(self, span):
        self._span = span

    def __getattr__(self, nome):
        return getattr(self._span, nome)

    @property
    def attributes(self):
        return {chave: valor for chave, valor in self._span.attributes.items()
                if chave not in _DADO_PESSOAL}


# filtra cada span antes de sair do processo e, com o jaeger fora, avisa uma
# vez so em vez de um traceback a cada lote.
class _Exportador(SpanExporter):

    def __init__(self, servico: str):
        self._otlp = OTLPSpanExporter()  # le OTEL_EXPORTER_OTLP_ENDPOINT
        self._servico = servico
        self._fora = False

    def export(self, spans):
        try:
            resultado = self._otlp.export(
                [_SpanSemDadoPessoal(span) for span in spans])
        except Exception as erro:  # noqa: BLE001
            if not self._fora:
                print(f"[{self._servico}] jaeger indisponivel "
                      f"({type(erro).__name__}), spans descartados",
                      flush=True)
            self._fora = True
            return SpanExportResult.FAILURE
        if self._fora and resultado is SpanExportResult.SUCCESS:
            print(f"[{self._servico}] jaeger de volta", flush=True)
            self._fora = False
        return resultado

    def shutdown(self):
        self._otlp.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._otlp.force_flush(timeout_millis)


# liga o rastreamento se houver endpoint otlp; devolve se ficou ligado.
def configurar(servico: str) -> bool:
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not endpoint:
        print(f"[{servico}] rastreamento desligado "
              f"(sem OTEL_EXPORTER_OTLP_ENDPOINT)", flush=True)
        return False
    provedor = TracerProvider(resource=Resource.create(
        {"service.name": os.getenv("OTEL_SERVICE_NAME") or servico}))
    # em lote e numa thread a parte: exportar nunca atrasa a requisicao
    provedor.add_span_processor(BatchSpanProcessor(_Exportador(servico)))
    trace.set_tracer_provider(provedor)
    print(f"[{servico}] rastreamento ligado, exportando para {endpoint}",
          flush=True)
    return True


# instrumenta as rotas do fastapi, menos o /saude (healthcheck so faz ruido).
def instrumentar_fastapi(app) -> None:
    # import aqui porque o worker tambem usa este modulo e nao tem fastapi
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    FastAPIInstrumentor.instrument_app(
        app, excluded_urls="/saude",
        # sem um span a cada leitura e escrita interna do asgi
        exclude_spans=["receive", "send"])


# trecho " trace_id=..." para a linha de log levar ao mesmo pedido no jaeger.
def para_log() -> str:
    contexto = trace.get_current_span().get_span_context()
    return f" trace_id={contexto.trace_id:032x}" if contexto.is_valid else ""
