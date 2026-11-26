# embeddings (do C2.A2): transforma texto em vetor com tf-idf, que roda
# offline e sem baixar modelo.
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer


class Vetorizador:

    def __init__(self):
        # tira o acento, para a pergunta acentuada achar o texto sem acento
        self._tfidf = TfidfVectorizer(ngram_range=(1, 2), min_df=1,
                                      strip_accents="unicode")
        self._ajustado = False

    # aprende o vocabulario; cada ajuste muda o tamanho dos vetores.
    def ajustar(self, textos):
        self._tfidf.fit(textos)
        self._ajustado = True

    # devolve o vetor do texto no vocabulario aprendido no ajuste.
    def vetorizar(self, texto):
        if not self._ajustado:
            raise RuntimeError("chame ajustar() antes de vetorizar()")
        return self._tfidf.transform([texto]).toarray()[0].tolist()


# similaridade do cosseno: 0 e nada em comum, 1 e o mesmo texto.
def similaridade(a, b):
    va, vb = np.array(a), np.array(b)
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))
