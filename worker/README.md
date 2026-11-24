# Worker de fila

Trazido do C1.A2. Consome a fila `tarefas` do Redis, roda a inferencia e grava
o resultado. Em caso de falha a tarefa volta para a fila; apos 3 tentativas vai
para a fila de descarte (`tarefas:descarte`).

| Arquivo | Papel |
|---|---|
| `worker.py` | laco principal, retentativa e dead-letter; encerra limpo no `SIGTERM` |
| `fila.py` / `modelo.py` / `log.py` | copias proprias do servico (cada imagem e autocontida) |
| `Dockerfile` | imagem do worker, sem porta exposta, usuario nao-root |

Ambiente: `REDIS_URL`. Escala horizontal: `docker compose up --scale worker=3`.
