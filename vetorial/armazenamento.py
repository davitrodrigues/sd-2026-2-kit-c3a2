# armazenamento (do C2.A2): grava e le do disco o indice (documentos, vetores
# e o vetorizador que os gerou), sempre juntos num arquivo so.
import logging
import os
import tempfile

import joblib

log = logging.getLogger("uvicorn.error")

# DIR_DADOS e o volume: o indice sobrevive ao restart do container
CAMINHO = os.path.abspath(
    os.path.join(os.getenv("DIR_DADOS", "dados"), "indice.joblib"))
CHAVES = {"versao", "documentos", "vetorizador"}


# grava num temporario e troca de nome: nunca fica arquivo pela metade.
def salvar(estado, caminho=CAMINHO):
    pasta = os.path.dirname(caminho)
    os.makedirs(pasta, exist_ok=True)
    # termina em .joblib para o .gitignore ignorar o que sobrar se der erro
    fd, temporario = tempfile.mkstemp(dir=pasta, suffix=".tmp.joblib")
    try:
        with os.fdopen(fd, "wb") as f:
            joblib.dump(estado, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporario, caminho)  # atomico no mesmo disco
    except BaseException:
        if os.path.exists(temporario):
            os.remove(temporario)
        raise


# devolve o indice salvo, ou nada se o arquivo faltar ou estiver estragado.
def carregar(caminho=CAMINHO):
    if not os.path.exists(caminho):
        return None
    try:
        # joblib.load roda codigo do arquivo (pickle): so le o que este
        # servico gravou no proprio volume, nunca arquivo vindo de fora
        estado = joblib.load(caminho)
    except Exception as e:
        log.warning("indice em %s esta corrompido (%s); ignorando",
                    caminho, type(e).__name__)
        return None
    if not isinstance(estado, dict) or not CHAVES <= estado.keys():
        log.warning("indice em %s nao tem o formato esperado; ignorando",
                    caminho)
        return None
    return estado
