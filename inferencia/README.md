# Servico de inferencia

Trazido do C1.A2. Recebe o texto do gateway, coloca na fila do Redis e devolve
o id (202); o `worker` processa e grava o resultado.

| Arquivo | Papel |
|---|---|
| `app.py` | API REST: `POST /predict` (assincrona), `POST /predict-sync`, `GET /resultado/{id}`, `GET /saude` |
| `fila.py` | auxiliares da fila no Redis (tarefas, resultados e dead-letter) |
| `modelo.py` | classificador de sentimento (treinado no `docker build`) |
| `log.py` | log de requisicoes na saida padrao, sem o texto (so o tamanho) |
| `Dockerfile` | imagem do servico, porta 8001, usuario nao-root, healthcheck em `/saude` |

Ambiente: `REDIS_URL`. Nao fica exposto para fora: so o gateway fala com ele.
