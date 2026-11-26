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

# 6g. Rastreamento (veja a seção "Observabilidade" abaixo): faça um /predict e
#     abra http://127.0.0.1:16686 -> Service "gateway" -> Find Traces

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

## Observabilidade

Rastreamento distribuído com **OpenTelemetry**, exportado por OTLP para o **Jaeger**
(sobe junto no compose). Um pedido vira **um trace só**, do gateway até o worker,
passando pela fila.

Para ver: faça um `POST /predict` (passo 6), abra **http://127.0.0.1:16686**, escolha
o serviço `gateway` e clique em *Find Traces*. O trace do `POST /predict` tem esta
árvore, com spans dos três serviços e o mesmo trace ID:

```
gateway     POST /predict                (SERVER)
gateway       POST                       (CLIENT: requests -> inferencia)
inferencia      POST /predict            (SERVER)
inferencia        enfileirar tarefas     (PRODUCER)
worker              processar tarefas    (CONSUMER, atributo tarefa.tentativa)
worker                modelo prever      (INTERNAL)
```

- **Gateway → inferência:** o contexto vai no header HTTP `traceparent`, pela
  instrumentação automática do FastAPI e do `requests`.
- **Pela fila:** o Redis não tem header, só guarda a mensagem. Por isso a inferência
  grava o `traceparent` **dentro da mensagem** (campo `rastreio`) e o worker abre o
  span de consumo como filho dele. Na retentativa a mensagem volta para a fila com
  o mesmo campo, então cada tentativa aparece no mesmo trace, marcada com erro.
- **Log ↔ trace:** as linhas de log dos três serviços terminam em `trace_id=...`, o
  mesmo ID que se busca no Jaeger (ou em `/api/v3/traces/<trace_id>`).
- **Só liga com `OTEL_EXPORTER_OTLP_ENDPOINT`.** O compose aponta para
  `http://jaeger:4318`. Na nuvem, sem Jaeger, basta não definir a variável: nada é
  configurado e o serviço roda igual. Com o Jaeger fora do ar, os spans são
  descartados com um aviso só no log. A exportação é em lote e em segundo plano,
  então nenhuma requisição espera por ela.
- **LGPD:** nenhum span leva texto, senha, token ou o IP de quem chamou. A
  instrumentação automática grava o IP, a porta e o navegador do cliente
  (`net.peer.ip`, `http.user_agent` e os equivalentes novos `client.address`,
  `user_agent.original`). Um filtro no exportador tira essas chaves antes de o span
  sair do processo. A fila só manda o id da tarefa, e o erro do modelo entra só com
  o tipo, sem a mensagem. O `/saude` não é rastreado, porque o healthcheck só faria
  ruído.

---

## Conformidade (LGPD)

A plataforma classifica o sentimento de um texto. O texto é enviado pelo próprio
cliente e **pode conter dado pessoal** (nome, e-mail, opinião sobre alguém), então
o sistema trata o texto como dado pessoal e guarda o mínimo pelo menor tempo.

| Dado | Finalidade | Onde fica | Por quanto tempo |
|---|---|---|---|
| Texto enviado no `/predict` | Classificar o sentimento (o único motivo de o serviço existir) | Na fila do Redis, só até um worker pegar a tarefa | Segundos (até ser consumido). **Não vai para o log** (só o tamanho) e **não fica no resultado** |
| Resultado (`sentimento`, `confianca`, `status`) | Devolver a resposta no `GET /resultado/{id}` | Redis, chave `resultado:{id}` | `RESULTADO_TTL_SEGUNDOS` (padrão **24 h**); depois o Redis apaga sozinho |
| Tarefa que falhou 3 vezes (fila de descarte) | Investigar o erro | Redis, `tarefas:descarte` | Só **id, tentativas e mensagem de erro**, sem o texto. No máximo `DESCARTE_MAXIMO` itens (padrão 1000); os mais antigos saem primeiro |
| Usuário e senha do `/login` | Autenticar | Só na memória durante a requisição | Não são guardados nem logados. A comparação é em tempo constante |
| Usuário (dentro do token JWT) | Identificar quem chama e aplicar a cota | Só no token, que fica com o cliente; o servidor não guarda tokens | `JWT_EXPIRA_MINUTOS` (padrão 30 min) |
| IP do cliente / usuário no rate limit | Limitar tentativas de login e chamadas por minuto | Redis, como **apelido HMAC-SHA256 com segredo** (não dá para voltar ao IP) | 60 s (a chave expira com a janela) |
| Rastreamento (spans no Jaeger) | Depurar e medir a latência entre os serviços | Memória do Jaeger, interface só em 127.0.0.1 | Até o Jaeger reiniciar (sem volume). Têm rota, status, tempos e id da tarefa; **nunca texto, senha, token ou IP do cliente** (filtrados no exportador) |
| Logs dos serviços | Operação e depuração | Saída padrão do container | O que a plataforma de hospedagem guardar. Têm método, rota, status, id da tarefa, tamanho da entrada, tempo e `trace_id`; **nunca texto, senha, token ou IP** (o access log do uvicorn está desligado no gateway porque registrava o IP) |

Princípios aplicados (art. 6º da LGPD):
- **Finalidade e necessidade:** o texto só é usado para a classificação. Ele não
  serve para treinar o modelo, que já vem pronto do build, e não é compartilhado
  com terceiros. Nenhuma chamada sai para fora da rede interna.
- **Minimização:** o resultado não repete o texto e a fila de descarte não o guarda.
- **Prazo de retenção:** tudo no Redis tem TTL. O volume do Redis (AOF) mantém só o
  que ainda não expirou.
- **Segurança:** só o gateway é exposto; o Redis, a inferência e o worker ficam na
  rede interna. As rotas exigem token e os segredos vêm do `.env`, que não vai para
  o git. Na nuvem o tráfego deve passar por HTTPS (tarefa 8).
- **Direitos do titular:** como nada é guardado por mais de 24 h e o resultado só
  pode ser achado pelo id aleatório (UUID), não há base de usuários para consultar.
  Para apagar um resultado antes do prazo, o operador remove a chave
  `resultado:{id}` no Redis.

Recomendação de uso: não envie dados sensíveis (art. 5º, II: saúde, religião,
biometria etc.). O serviço não precisa deles para classificar sentimento.

---

## Trade-offs: CAP, custo e latência

### CAP

O estado compartilhado fica num **único Redis** (fila, resultados e contadores do
rate limit). Com uma instância só não há réplica para divergir, então o sistema é
**consistente**. O preço disso é a disponibilidade: se o Redis cai, quem depende dele
para de aceitar trabalho. Cada parte escolhe um lado de propósito:

| Parte | Escolha | Por quê |
|---|---|---|
| `/predict` e `/resultado` | **C** (consistência): Redis fora → 503 com `Retry-After` | Aceitar a tarefa sem conseguir enfileirar seria mentir para o cliente (202 de algo que nunca vai rodar) |
| Rate limit | **A** (disponibilidade): Redis fora → deixa passar (*fail-open*) | O limite protege o sistema mas não é a função dele. Derrubar o gateway por causa do contador seria pior |
| Circuit breaker | **A**, com estado local de cada réplica do gateway | Não depende de ninguém para decidir. As réplicas podem discordar por alguns segundos, e isso é aceitável |
| Resultado | **Consistência eventual**: o `POST /predict` responde 202 e o resultado aparece depois | É o preço da fila assíncrona, que absorve picos e deixa escalar os workers |
| Worker | **No máximo uma entrega**: a tarefa sai da fila no `BLPOP` | Mais simples. Pelo menos uma entrega pediria `BLMOVE` + lista de processamento (ver Resiliência) |

Para tolerar a queda do Redis, o próximo passo seria Redis com réplica + Sentinel
(ou um Redis gerenciado). Aí entra o trade-off clássico: a replicação do Redis é
assíncrona, e um *failover* pode perder as últimas escritas.

### Latência

| Caminho | Tempo típico | Pior caso |
|---|---|---|
| `POST /predict` (gateway → inferência → Redis) | Poucos ms: só valida e enfileira | ~9 s com a inferência travada (3 tentativas × 3 s de leitura + espera); com o disjuntor aberto, **503 imediato** |
| Inferência no worker (TF-IDF + regressão logística) | Da ordem de milissegundos por texto | Cresce com o tamanho da fila: o tempo de espera ≈ tamanho da fila ÷ (workers × vazão de cada um) |
| `GET /resultado/{id}` | Poucos ms (uma leitura no Redis) | Igual ao `/predict` |
| Tempo total para o cliente ver o resultado | Latência da fila + **intervalo de polling** do cliente | — |

Decisões: o modelo é treinado **no build** e carregado **uma vez** na subida, então
nenhuma requisição paga esse custo. O processamento é **assíncrono** porque, com
modelos mais pesados (um LLM, por exemplo), segurar a conexão HTTP escalaria mal. O
custo é o cliente ter que consultar depois. Com este modelo, que é muito rápido, a
rota síncrona da inferência (`/predict-sync`) responderia mais rápido, mas sem
proteção contra picos.

### Custo

- **Imagens enxutas:** `python:3.12-slim`, sem GPU (o modelo é scikit-learn e roda
  em CPU). Cabe com folga no menor plano free tier.
- **Free tier:** instâncias gratuitas costumam "dormir" quando ficam sem uso, e a
  primeira requisição depois disso paga a subida do container (*cold start*, dezenas
  de segundos). Como o modelo já vem treinado na imagem, essa subida é a menor
  possível.
- **Escala onde custa:** só os workers precisam de mais réplicas quando a fila
  cresce (`WORKERS` no compose, réplicas/HPA no Kubernetes). O gateway e a inferência
  só repassam e são leves.
- **O rate limit também controla custo:** um cliente sozinho não consegue gerar
  trabalho ilimitado nos workers.
- **O TTL dos resultados** (LGPD) também segura a memória do Redis, que é o recurso
  mais caro de manter em plano gerenciado.

---

## Kubernetes (extensão opcional)

A pasta `k8s/` tem os manifests da mesma stack do compose: namespace, ConfigMap,
Secret, Redis com volume, inferência, workers (com HPA por CPU) e gateway. Feito
para cluster local (minikube, kind ou o Kubernetes do Docker Desktop):

```bash
# 1. gere as imagens com os nomes usados nos manifests
docker build -t plataforma-ia/gateway:1.0 ./gateway
docker build -t plataforma-ia/inferencia:1.0 ./inferencia
docker build -t plataforma-ia/worker:1.0 ./worker
#    minikube: rode antes  eval $(minikube docker-env)
#    kind:     kind load docker-image plataforma-ia/gateway:1.0 (e as outras)

# 2. TROQUE os valores de k8s/secret.yaml e aplique tudo de uma vez
kubectl apply -k k8s/

# 3. acesse o gateway (único Service exposto)
kubectl -n plataforma-ia port-forward svc/gateway 8000:8000
curl http://localhost:8000/saude

kubectl -n plataforma-ia get pods,hpa    # acompanhar
kubectl delete -k k8s/                   # remover tudo
```

O HPA dos workers precisa do `metrics-server` (`minikube addons enable metrics-server`).

---

## Estrutura do projeto

```
sd-2026-2-kit-c3a2/
├── gateway/
│   ├── app.py              # TAREFAS 1 e 2 (JWT e rate limit)
│   ├── resiliencia.py      # TAREFA 6 (retentativa e circuit breaker)
│   ├── rastreio.py         # TAREFA 7 (rastreamento; igual em inferencia/ e worker/)
│   └── Dockerfile          # TAREFA 3
├── inferencia/             # API de inferência do C1.A2 + Dockerfile (TAREFA 3)
├── worker/                 # worker de fila do C1.A2 + Dockerfile (TAREFA 3)
├── deploy/INSTRUCOES.md    # passo a passo do free tier
├── Dockerfile.exemplo      # modelo para os demais serviços
├── docker-compose.yml      # TAREFA 4 (stack inteira com um comando)
├── k8s/                    # extensao: manifests de Kubernetes (kubectl apply -k)
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
