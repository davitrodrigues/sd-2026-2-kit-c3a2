# Worker de fila

Trazido do C1.A2. Consome a fila `tarefas` do Redis, roda a inferencia e grava
o resultado. Em caso de falha a tarefa volta para a fila; apos
`WORKER_MAX_TENTATIVAS` tentativas (padrao 3) vai para a fila de descarte
(`tarefas:descarte`).

| Arquivo | Papel |
|---|---|
| `worker.py` | laco principal, retentativa e dead-letter; espera progressiva se o Redis cair; encerra limpo no `SIGTERM` |
| `fila.py` / `modelo.py` / `log.py` | copias proprias do servico (cada imagem e autocontida) |
| `Dockerfile` | imagem do worker, sem porta exposta, usuario nao-root |

Ambiente: `REDIS_URL`, `REDIS_TIMEOUT`, `REDIS_TENTATIVAS`, `WORKER_ESPERA_REDIS_BASE`, `WORKER_ESPERA_REDIS_MAXIMA`, `WORKER_MAX_TENTATIVAS`. Escala horizontal: `docker compose up --scale worker=3`.
