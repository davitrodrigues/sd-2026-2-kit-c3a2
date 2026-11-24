# Kit de Partida — C3.A2: Plataforma de IA como Serviço (projeto integrador)

**Sistemas Distribuídos e Computação em Nuvem · FAESA · 2026/2**
Prof. Howard Cruz Roatti · Lançado na Aula 13 (05/11) · Entrega na Aula 17 (26/11)

---

## O que é isto

O projeto que fecha o semestre. Você pega tudo o que construiu e transforma numa
plataforma de verdade: **conteinerizada, publicada na internet, observável e protegida**.
Ao final você terá um sistema distribuído completo e público — material de portfólio
para entrevista de emprego.

> **Sobre a IA neste trabalho:** todo contato com inteligência artificial aqui é
> **chamada de biblioteca ou de API**. Você **não vai treinar modelos** nem precisar de
> matemática de aprendizado de máquina. O modelo já vem pronto e configurado.
> A sua nota vem da **engenharia distribuída**: arquitetura, comunicação, resiliência e
> execução reproduzível — a sofisticação do modelo **não pontua**.

---

## Como começar

```bash
# 1. Clone o kit e entre na pasta
git clone https://github.com/howardroatti/sd-2026-2-kit-c3a2.git
cd sd-2026-2-kit-c3a2

# 2. Crie e ative o ambiente virtual
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# 3. Instale as dependências
pip install -r requirements.txt
```

```bash
# 4. Copie o arquivo de ambiente
cp .env.example .env

# 5. Suba a stack inteira com UM comando
docker compose up --build

# 6. Teste pelo gateway (nunca pelos serviços diretamente)
curl http://localhost:8000/saude        # pública: é o healthcheck do deploy

# 6a. Faça login com GATEWAY_USUARIO / GATEWAY_SENHA do seu .env
curl -X POST http://localhost:8000/login \
  -H "Content-Type: application/json" \
  -d '{"usuario":"admin","senha":"troque-esta-senha"}'
# -> {"access_token":"eyJ...","token_type":"bearer","expira_em":1800}

# 6b. Use o access_token nas rotas protegidas (sem ele a resposta é 401)
TOKEN="cole-aqui-o-access_token"
curl -X POST http://localhost:8000/predict \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"texto":"servico excelente"}'
# -> 202 {"id":"563b1b0b-..."}   (assíncrono: a tarefa foi para a fila)

# 6b'. Consulte o resultado com o id (o worker processa em segundo plano)
curl http://localhost:8000/resultado/563b1b0b-... -H "Authorization: Bearer $TOKEN"
# -> {"sentimento":"positivo","confianca":0.54,"status":"pronto",...}
#    status "na_fila" enquanto não terminou; 404 se o id não existir
# Pelo navegador: http://localhost:8000/docs -> botão "Authorize" -> cole o token

# 6c. Limite por minuto: LIMITE_POR_MINUTO chamadas por usuário do token e
#     LIMITE_LOGIN_POR_MINUTO tentativas de /login por IP. Passou disso, a
#     resposta é 429 com o header Retry-After (segundos até liberar).
for i in 1 2 3 4 5 6; do
  curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/login \
    -H "Content-Type: application/json" -d '{"usuario":"x","senha":"errada"}'
done
# -> 401 até estourar o limite do minuto e depois 429

# 6d. Cada serviço tem o seu Dockerfile (python:3.12-slim, usuário não-root).
#     O modelo é treinado no build, então a imagem já sobe pronta.
docker compose ps        # gateway e inferencia aparecem como (healthy)
docker compose up -d --scale worker=3   # mais workers dividindo a fila

# 6e. O compose sobe redis -> inferencia -> gateway na ordem certa (espera o
#     healthcheck de cada um) e WORKERS réplicas do worker (padrão 2).
#     Só o gateway tem porta pública; inferencia e worker ficam na rede interna
#     e o redis só em 127.0.0.1. Tudo vem do .env (veja .env.example).
docker compose down      # para tudo (os dados do redis ficam no volume)
docker compose down -v   # para tudo e apaga o volume do redis

# 6f. Resiliência (veja a seção "Resiliência" abaixo). Para ver funcionando:
docker compose pause inferencia   # trava a inferência
#  -> 3 pedidos seguidos: 503 após ~9s cada (tempo-limite + 3 tentativas)
#  -> 4º pedido: 503 na hora com Retry-After (disjuntor aberto)
curl http://localhost:8000/saude  # {"disjuntor_inferencia":"aberto"}
docker compose unpause inferencia # após 15s o disjuntor testa e fecha sozinho

# 7. Publique na nuvem seguindo deploy/INSTRUCOES.md
```

---

## Resiliência

| Onde | Mecanismo | Padrão (`.env`) |
|---|---|---|
| gateway → inferência | **tempo-limite** separado para conectar e para ler | `INFERENCIA_TIMEOUT_CONEXAO=1`, `INFERENCIA_TIMEOUT_LEITURA=3` (s) |
| gateway → inferência | **retentativa com espera progressiva** (0,2 s, 0,4 s… com jitter), só em falha transitória: rede, tempo-limite e 5xx. Erro 4xx não se repete | `INFERENCIA_TENTATIVAS=3`, `INFERENCIA_ESPERA_BASE=0.2` |
| gateway → inferência | **circuit breaker** por fora das tentativas: abre após N falhas seguidas e responde 503 na hora com `Retry-After`; depois da espera deixa uma chamada de teste passar e fecha se ela der certo. Estado em `GET /saude` | `DISJUNTOR_LIMITE_FALHAS=3`, `DISJUNTOR_ESPERA_SEGUNDOS=15` |
| gateway → inferência | **idempotência**: o gateway gera o id da tarefa e a inferência só enfileira se o id ainda não existe (script Lua atômico no Redis), então repetir um `POST /predict` não duplica a tarefa | — |
| inferência / worker → Redis | tempo-limite curto e retentativa no próprio cliente Redis. Com o Redis fora, a inferência responde **503** (e não 500), que o gateway trata como falha transitória | `REDIS_TIMEOUT=1`, `REDIS_TENTATIVAS=1` |
| worker → Redis | com o Redis fora, o worker **não cai**: espera 1, 2, 4… s (teto 30 s, com jitter) e retoma sozinho quando ele volta | `WORKER_ESPERA_REDIS_BASE=1`, `WORKER_ESPERA_REDIS_MAXIMA=30` |
| worker | falha na inferência: até 3 tentativas e depois fila de descarte (dead-letter, do C1.A2) | — |
| gateway → Redis (rate limit) | *fail-open*: se o Redis cair, o limite deixa passar em vez de derrubar o gateway | — |
| todos | `restart: unless-stopped` e healthchecks no compose | — |

Decisões e limites:
- **Retentativa só numa camada.** Se o gateway e a inferência repetissem as
  chamadas um por cima do outro, as tentativas se multiplicariam (3 × 3 = 9) e o
  cliente esperaria mais que o tempo-limite. Por isso o cliente Redis da
  inferência tenta pouco e falha logo, e quem repete é o gateway.
- **O disjuntor fica na memória de cada réplica do gateway.** Com várias réplicas,
  cada uma abre o seu sozinha. Isso é aceitável: o pior caso é algumas falhas a
  mais até todas abrirem.
- **O worker entrega no máximo uma vez.** Se o Redis cair entre o `BLPOP` e a
  gravação do resultado, aquela tarefa se perde (o id aparece no log). Garantir
  pelo menos uma entrega exigiria uma fila com confirmação (`BLMOVE` + lista de
  processamento).
- `dns_opt` no compose: um container parado some do DNS do Docker e a consulta
  levaria ~4 s para falhar. O resolvedor desiste em 1 s para a falha ser rápida.

---

## Estrutura do projeto

```
sd-2026-2-kit-c3a2/
├── gateway/
│   ├── app.py              # TAREFAS 1 e 2 (JWT e rate limit)
│   ├── resiliencia.py      # TAREFA 6 (retentativa e circuit breaker)
│   └── Dockerfile          # TAREFA 3
├── inferencia/             # API de inferência do C1.A2 + Dockerfile (TAREFA 3)
├── worker/                 # worker de fila do C1.A2 + Dockerfile (TAREFA 3)
├── deploy/INSTRUCOES.md    # passo a passo do free tier
├── Dockerfile.exemplo      # modelo para os demais serviços
├── docker-compose.yml      # TAREFA 4 (stack inteira com um comando)
└── TAREFAS.md              # <- comece por aqui
```

---

## O que você precisa fazer

Abra o arquivo **`TAREFAS.md`**: ele lista o núcleo obrigatório item a item, indicando
o arquivo e a aula de referência de cada um.

---

## Como você será avaliado

| Critério | Pontos |
|---|---|
| Arquitetura e decomposição em serviços | 1,5 |
| Comunicação funcionando (REST / gRPC / mensageria) | 1,5 |
| Resiliência e tratamento de falhas | 1,0 |
| Execução reproduzível (README, container, deploy) | 1,0 |
| **Sofisticação do modelo de IA** | **não pontua** |
| **Total** | **5,0** |

**Entrega:** no seu repositório do GitHub, **sem apresentação oral**. Grupos livres.

---

## Aulas de referência

- **Aula 13** — Nuvem, containers e o primeiro deploy
- **Aula 14** — Orquestração, serverless e borda
- **Aula 15** — Observabilidade e rastreamento distribuído
- **Aula 16** — Segurança, LGPD e revisão para o ENADE

---

## Dúvidas frequentes

**Preciso saber machine learning?** Não. O modelo já está pronto e você só chama uma função.

**E se eu não tiver internet no laboratório?** Tudo neste kit funciona offline. O modelo é
treinado localmente e o cliente de LLM tem modo simulado.

**Posso trocar a linguagem?** O kit é em Python porque é o ecossistema usado nas aulas.
Se quiser usar outra linguagem, converse com o professor antes.

**Posso usar IA para me ajudar a programar?** Sim. Este é um trabalho prático feito fora de
sala, e usar ferramentas de IA é realista. O que se avalia é o **sistema funcionando** e as
**decisões de arquitetura** — que você precisa saber explicar.
