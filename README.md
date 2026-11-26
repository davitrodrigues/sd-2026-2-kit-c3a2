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

## No ar

A plataforma está publicada no **Railway**, só por HTTPS:

**https://gateway-production-f3318087.up.railway.app**

| Rota | O que é |
|---|---|
| [`/docs`](https://gateway-production-f3318087.up.railway.app/docs) | Documentação interativa (Swagger): `/login`, depois o botão *Authorize* com o token |
| [`/saude`](https://gateway-production-f3318087.up.railway.app/saude) | Healthcheck público: `{"status":"ok","disjuntor_inferencia":"fechado","disjuntor_vetorial":"fechado"}` |

**Conta de demonstração** do `/login`: usuário **`demo`**, senha **`c3a2-demo-741ec4dc`**.
Ela é pública de propósito: a entrega no AVA é só o link do repositório, e quem avalia
precisa conseguir testar. O abuso é contido pelo rate limit: 10 chamadas por minuto por
usuário (como todos entram com o mesmo usuário, é um teto global de 10 por minuto, que
também protege o crédito do Railway) e 5 tentativas de login por minuto por IP (veja
*Limitação conhecida*). O `JWT_SEGREDO`, que assina os tokens, continua só nas
variáveis do Railway. O passo a passo do teste está em [Testar na nuvem](#testar-na-nuvem)
e o do deploy em `deploy/INSTRUCOES.md`. A conta do Railway é de teste: quando o
crédito ou o prazo de 30 dias acabar, a URL sai do ar (veja *Custo*).

---

## Arquitetura

Cinco serviços, cada um no seu container, com o gateway como única porta de entrada:

```
cliente --HTTPS--> gateway (JWT, rate limit, tempo-limite, retentativa, disjuntores)
                     |
                     +-- POST /predict ------> inferencia --> Redis (fila) --> worker(s)
                     +-- GET /resultado/{id} -> inferencia <-- Redis (resultado) <--+
                     |
                     +-- POST /buscar -------> vetorial --> volume vetorial-dados
                                                            (documentos, vetores e vetorizador)
```

| Serviço | Papel | Estado |
|---|---|---|
| `gateway` (8000) | Única porta pública: login JWT, rate limit, tempo-limite, retentativa e **um disjuntor por serviço interno** | Nenhum (os contadores ficam no Redis) |
| `inferencia` (8001) | Recebe o texto, enfileira no Redis e devolve o id (202); consulta o resultado | Nenhum |
| `worker` (N réplicas) | Consome a fila, roda o modelo de sentimento e grava o resultado | Nenhum |
| `vetorial` (8002) | **Armazenamento vetorial** (do C2.A2): guarda os documentos com os vetores TF-IDF e devolve os `top_k` trechos mais parecidos com a pergunta (similaridade do cosseno) | Índice no volume `vetorial-dados` |
| `redis` | Fila, resultados e contadores do rate limit | Volume `redis-dados` |
| `jaeger` | Recebe os spans do rastreamento (só no compose) | Memória |

O **armazenamento vetorial** grava num arquivo só os documentos, os vetores e o
vetorizador que os gerou. Os três vão juntos porque o TF-IDF muda de dimensão a cada
ajuste, e a pergunta precisa ser vetorizada pelo mesmo vetorizador dos documentos. A
gravação é atômica (arquivo temporário + `os.replace`), então uma queda no meio não deixa
o índice pela metade. Na subida o serviço carrega o índice do volume. Com o volume vazio,
indexa os três textos da disciplina que vêm na imagem (`vetorial/documentos/`) e já
responde. `POST /indexar` acrescenta documentos sem apagar os anteriores, mas só existe na
rede interna: o gateway não expõe essa rota.

---

## Como começar

Só precisa de **Git** e **Docker** (com o Compose): os serviços, o Redis e o Jaeger
rodam em containers, então não é preciso instalar Python nem criar ambiente virtual.

```bash
# 1. Clone o repositório e entre na pasta
git clone https://github.com/davitrodrigues/sd-2026-2-kit-c3a2.git
cd sd-2026-2-kit-c3a2

# 2. Copie o arquivo de ambiente
cp .env.example .env

# 3. Suba a stack inteira com UM comando. O -d devolve o terminal; sem ele,
#    os logs ficam presos na tela e os testes abaixo vão em OUTRO terminal
docker compose up --build -d
docker compose logs -f   # opcional: acompanha os logs (Ctrl+C sai só do log)

# 4. Teste pelo gateway (nunca pelos serviços diretamente)
curl http://localhost:8000/saude        # pública: é o healthcheck do deploy

# 4a. Faça login com GATEWAY_USUARIO / GATEWAY_SENHA do seu .env
curl -X POST http://localhost:8000/login \
  -H "Content-Type: application/json" \
  -d '{"usuario":"admin","senha":"troque-esta-senha"}'
# -> {"access_token":"eyJ...","token_type":"bearer","expira_em":1800}

# 4b. Use o access_token nas rotas protegidas (sem ele a resposta é 401)
TOKEN="cole-aqui-o-access_token"
curl -X POST http://localhost:8000/predict \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"texto":"servico excelente"}'
# -> 202 {"id":"563b1b0b-..."}   (assíncrono: a tarefa foi para a fila)

# 4b'. Consulte o resultado com o id (o worker processa em segundo plano)
curl http://localhost:8000/resultado/563b1b0b-... -H "Authorization: Bearer $TOKEN"
# -> {"sentimento":"positivo","confianca":0.54,"status":"pronto",...}
#    status "na_fila" enquanto não terminou; 404 se o id não existir

# 4b''. Busca vetorial: os top_k trechos dos documentos mais parecidos com a
#       pergunta (top_k de 1 a 10, padrão 3; fora disso, 422)
curl -X POST http://localhost:8000/buscar \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"pergunta":"o que diz o teorema CAP","top_k":2}'
# -> {"resultados":[{"texto":"O teorema CAP afirma que...",
#      "origem":"teorema_cap.txt","score":0.2694},{...}]}
# Pelo navegador: http://localhost:8000/docs -> botão "Authorize" -> cole o token
```

**No Windows (PowerShell):** os `curl` acima são de bash. No PowerShell 5.1, `curl` é
apelido do `Invoke-WebRequest`, e o `curl.exe` estraga as aspas do JSON (a resposta
vira 422). O mesmo teste (passos 4 a 4b'') com `Invoke-RestMethod`:

```powershell
# 127.0.0.1 e não localhost: no Windows o localhost tenta o IPv6 antes e atrasa
$base = "http://127.0.0.1:8000"
Invoke-RestMethod "$base/saude"

# 4a. login com GATEWAY_USUARIO / GATEWAY_SENHA do .env, guardando o token
$login = @{ usuario = "admin"; senha = "troque-esta-senha" } | ConvertTo-Json
$token = (Invoke-RestMethod "$base/login" -Method Post `
  -ContentType "application/json" -Body $login).access_token
$auth = @{ Authorization = "Bearer $token" }

# 4b. envia o texto (charset=utf-8 para o acento chegar certo)
$corpo = @{ texto = "serviço excelente" } | ConvertTo-Json
$id = (Invoke-RestMethod "$base/predict" -Method Post -Headers $auth `
  -ContentType "application/json; charset=utf-8" -Body $corpo).id

# 4b'. consulta o resultado (o worker processa em segundo plano)
Start-Sleep -Seconds 1
Invoke-RestMethod "$base/resultado/$id" -Headers $auth | Format-List
# -> sentimento : positivo / confianca : ... / status : pronto / tempo_ms : ...

# 4b''. busca vetorial: os trechos mais parecidos com a pergunta
$busca = @{ pergunta = "o que diz o teorema CAP"; top_k = 2 } | ConvertTo-Json
(Invoke-RestMethod "$base/buscar" -Method Post -Headers $auth `
  -ContentType "application/json; charset=utf-8" -Body $busca).resultados |
  Format-List origem, score, texto
# -> origem : teorema_cap.txt / score : ... / texto : O teorema CAP afirma...
```

```bash
# 4c. Limite por minuto: LIMITE_POR_MINUTO chamadas por usuário do token e
#     LIMITE_LOGIN_POR_MINUTO tentativas de /login por IP. Passou disso, a
#     resposta é 429 com o header Retry-After (segundos até liberar).
for i in 1 2 3 4 5 6; do
  curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/login \
    -H "Content-Type: application/json" -d '{"usuario":"x","senha":"errada"}'
done
# -> 401 até estourar o limite do minuto e depois 429

# 4d. Cada serviço tem o seu Dockerfile (python:3.12-slim, usuário não-root).
#     O modelo é treinado no build, então a imagem já sobe pronta.
docker compose ps        # gateway, inferencia e vetorial aparecem como (healthy)
docker compose up -d --scale worker=3   # mais workers dividindo a fila

# 4e. O compose sobe redis -> inferencia e vetorial -> gateway na ordem certa
#     (espera o healthcheck de cada um) e WORKERS réplicas do worker (padrão 2).
#     Só o gateway tem porta pública; inferencia, vetorial e worker ficam na
#     rede interna e o redis só em 127.0.0.1. Tudo vem do .env (.env.example).
docker compose down      # para tudo (redis e índice vetorial ficam nos volumes)
docker compose down -v   # para tudo e apaga os volumes (redis e índice vetorial)

# 4f. Resiliência (veja a seção "Resiliência" abaixo). Para ver funcionando:
docker compose pause inferencia   # trava a inferência
#  -> 3 pedidos seguidos: 503 após ~9s cada (tempo-limite + 3 tentativas)
#  -> 4º pedido: 503 na hora (disjuntor aberto)
#  -> todo 503 vem com Retry-After (segundos para tentar de novo)
curl http://localhost:8000/saude  # {"disjuntor_inferencia":"aberto",...}
docker compose unpause inferencia # após 15s, o próximo pedido testa e fecha o disjuntor
docker compose stop vetorial      # derruba o armazenamento vetorial
#  -> /buscar: 503 com Retry-After; no 4º pedido, 503 na hora (disjuntor aberto)
#  -> /saude: "disjuntor_vetorial":"aberto", e o /predict continua 202
#     (cada serviço tem o seu disjuntor: a queda de um não derruba o outro)
docker compose start vetorial     # volta com o índice do volume, sem reindexar

# 4g. Rastreamento (veja a seção "Observabilidade" abaixo): faça um /predict ou
#     um /buscar e abra http://127.0.0.1:16686 -> Service "gateway" -> Find Traces

# 5. Para publicar a sua cópia na nuvem, siga deploy/INSTRUCOES.md
```

### Testar na nuvem

O mesmo fluxo do passo 4, trocando `http://127.0.0.1:8000` pela URL pública e usando
a conta de demonstração (usuário `demo`, senha `c3a2-demo-741ec4dc`, veja *No ar*):

```bash
BASE=https://gateway-production-f3318087.up.railway.app
curl $BASE/saude
curl -X POST $BASE/login -H "Content-Type: application/json" \
  -d '{"usuario":"demo","senha":"c3a2-demo-741ec4dc"}'
TOKEN="cole-aqui-o-access_token"
curl -X POST $BASE/predict -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"texto":"servico excelente"}'
curl $BASE/resultado/<id-devolvido-pelo-predict> -H "Authorization: Bearer $TOKEN"
curl -X POST $BASE/buscar -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"pergunta":"o que diz o teorema CAP","top_k":2}'
```

No PowerShell, o bloco do passo 4 serve inteiro: troque só a linha do `$base` por
`$base = "https://gateway-production-f3318087.up.railway.app"` e, no login, `admin` e
`troque-esta-senha` por `demo` e `c3a2-demo-741ec4dc`.

O que muda em relação ao compose:
- **HTTPS (tarefa 8):** o TLS é terminado na **borda do Railway**, que emite e renova
  sozinha o certificado (Let's Encrypt, `*.up.railway.app`, TLS 1.3). Um pedido em
  `http://` recebe **301 para `https://`**. Da borda até o container a requisição
  segue pela rede interna do Railway, por isso o gateway continua escutando HTTP na
  porta 8000 e não precisou de certificado nem de código novo.
- **Só o gateway é público.** Inferência, vetorial, worker e Redis ficam na rede
  privada do projeto, sem domínio; as portas 8001 e 8002 não respondem de fora.
- **Índice vetorial sem volume.** No Railway o `vetorial` roda sem volume: a cada
  deploy ele recria o índice na subida, com os documentos da imagem. Como o `/indexar`
  não é exposto, não há outro documento para perder (veja *Trade-offs*).
- **Rastreamento desligado.** Não há Jaeger no Railway: seria mais um serviço
  gastando o crédito de teste, e a interface dele não tem login para ficar exposta.
  Sem `OTEL_EXPORTER_OTLP_ENDPOINT`, o OpenTelemetry nem é configurado e os serviços
  rodam igual (veja *Observabilidade*). O rastreamento se demonstra no compose (passo 4g).

---

## Resiliência

| Onde | Mecanismo | Padrão (`.env`) |
|---|---|---|
| gateway → inferência | **tempo-limite** separado para conectar e para ler | `INFERENCIA_TIMEOUT_CONEXAO=1`, `INFERENCIA_TIMEOUT_LEITURA=3` (s) |
| gateway → inferência | **retentativa com espera progressiva** (0,2 s, 0,4 s… com jitter), só em falha transitória: rede, tempo-limite e 5xx. Erro 4xx não se repete. Esgotadas as tentativas, responde 503 com `Retry-After`: o valor que a inferência pediu ou, se ela não mandou (estava fora do ar), o `DISJUNTOR_ESPERA_SEGUNDOS` | `INFERENCIA_TENTATIVAS=3`, `INFERENCIA_ESPERA_BASE=0.2` |
| gateway → inferência | **circuit breaker** por fora das tentativas: abre após N falhas seguidas e responde 503 na hora com `Retry-After`; depois da espera deixa uma chamada de teste passar e fecha se ela der certo. Estado em `GET /saude` | `DISJUNTOR_LIMITE_FALHAS=3`, `DISJUNTOR_ESPERA_SEGUNDOS=15` |
| gateway → inferência | **idempotência**: o gateway gera o id da tarefa e a inferência só enfileira se o id ainda não existe (script Lua atômico no Redis), então repetir um `POST /predict` não duplica a tarefa | — |
| gateway → vetorial | o mesmo tempo-limite e a mesma retentativa (a busca só lê, então repetir é seguro), com um **disjuntor próprio**: com o vetorial fora, o `/buscar` responde 503 com `Retry-After` e o `/predict` segue normal. Estado em `GET /saude` (`disjuntor_vetorial`); os limites do disjuntor são os mesmos `DISJUNTOR_*` | `VETORIAL_TIMEOUT_CONEXAO=1`, `VETORIAL_TIMEOUT_LEITURA=3`, `VETORIAL_TENTATIVAS=3`, `VETORIAL_ESPERA_BASE=0.2` |
| vetorial → disco | **gravação atômica** do índice (arquivo temporário + `os.replace`): uma queda no meio deixa o índice anterior inteiro. Se gravar falhar, o `/indexar` responde erro e o índice em memória não muda | — |
| inferência / worker → Redis | tempo-limite curto e retentativa no próprio cliente Redis. Com o Redis fora, a inferência responde **503** (e não 500), que o gateway trata como falha transitória | `REDIS_TIMEOUT=1`, `REDIS_TENTATIVAS=1` |
| worker → Redis | com o Redis fora, o worker **não cai**: espera 1, 2, 4… s (teto 30 s, com jitter) e retoma sozinho quando ele volta | `WORKER_ESPERA_REDIS_BASE=1`, `WORKER_ESPERA_REDIS_MAXIMA=30` |
| worker | falha na inferência: até N tentativas e depois fila de descarte (dead-letter, do C1.A2) | `WORKER_MAX_TENTATIVAS=3` |
| gateway → Redis (rate limit) | *fail-open*: se o Redis cair, o limite deixa passar em vez de derrubar o gateway. Tempo-limite menor que o `REDIS_TIMEOUT`, porque com o Redis fora toda requisição paga essa espera | `LIMITE_REDIS_TIMEOUT=0.5` (s) |
| todos | `restart: unless-stopped` e healthchecks no compose | — |

Decisões e limites:
- **Retentativa só numa camada.** Se o gateway e a inferência repetissem as
  chamadas um por cima do outro, as tentativas se multiplicariam (3 × 3 = 9) e o
  cliente esperaria mais que o tempo-limite. Por isso o cliente Redis da
  inferência tenta pouco e falha logo, e quem repete é o gateway.
- **Um disjuntor por serviço.** Com um disjuntor só, as falhas do vetorial abririam
  o circuito também para a inferência, e uma busca fora do ar derrubaria a
  classificação. Separados, cada serviço falha sozinho.
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

Para ver: faça um `POST /predict` (passo 4b), abra **http://127.0.0.1:16686**, escolha
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

O `POST /buscar` vira um trace com o gateway e o vetorial:

```
gateway     POST /buscar                 (SERVER)
gateway       POST                       (CLIENT: requests -> vetorial)
vetorial        POST /buscar             (SERVER)
vetorial          buscar no indice       (INTERNAL: indice.versao, busca.top_k,
                                          busca.resultados)
```

O span `buscar no indice` mostra o tempo da busca separado do HTTP e qual versão do
índice respondeu. A pergunta não entra em nenhum span.

- **Gateway → inferência:** o contexto vai no header HTTP `traceparent`, pela
  instrumentação automática do FastAPI e do `requests`.
- **Pela fila:** o Redis não tem header, só guarda a mensagem. Por isso a inferência
  grava o `traceparent` **dentro da mensagem** (campo `rastreio`) e o worker abre o
  span de consumo como filho dele. Na retentativa a mensagem volta para a fila com
  o mesmo campo, então cada tentativa aparece no mesmo trace, marcada com erro.
- **Log ↔ trace:** as linhas de log dos serviços terminam em `trace_id=...`, o
  mesmo ID que se busca no Jaeger (ou em `/api/v3/traces/<trace_id>`).
- **Só liga com `OTEL_EXPORTER_OTLP_ENDPOINT`.** O compose aponta para
  `http://jaeger:4318`. No Railway não há Jaeger e a variável não é definida: nada é
  configurado e o serviço roda igual. Com o Jaeger fora do ar, os spans são
  descartados com um aviso só no log. A exportação é em lote e em segundo plano,
  então nenhuma requisição espera por ela.
- **LGPD:** nenhum span leva texto, pergunta, senha, token ou o IP de quem chamou. A
  instrumentação automática grava o IP, a porta e o navegador do cliente
  (`net.peer.ip`, `http.user_agent` e os equivalentes novos `client.address`,
  `user_agent.original`). Um filtro no exportador tira essas chaves antes de o span
  sair do processo. A fila só manda o id da tarefa, e o erro do modelo entra só com
  o tipo, sem a mensagem. O `/saude` não é rastreado, porque o healthcheck só faria
  ruído.

---

## Conformidade (LGPD)

A plataforma classifica o sentimento de um texto e busca trechos de documentos
parecidos com uma pergunta. O texto e a pergunta são enviados pelo próprio cliente e
**podem conter dado pessoal** (nome, e-mail, opinião sobre alguém), então o sistema
trata os dois como dado pessoal e guarda o mínimo pelo menor tempo.

| Dado | Finalidade | Onde fica | Por quanto tempo |
|---|---|---|---|
| Texto enviado no `/predict` | Classificar o sentimento (o único motivo de o serviço existir) | Na fila do Redis, só até um worker pegar a tarefa | Segundos (até ser consumido). Se um snapshot do Redis pegar a tarefa ainda na fila, ela fica no disco até o snapshot seguinte (~60 s). **Não vai para o log** (só o tamanho) e **não fica no resultado** |
| Resultado (`sentimento`, `confianca`, `status`) | Devolver a resposta no `GET /resultado/{id}` | Redis, chave `resultado:{id}` | `RESULTADO_TTL_SEGUNDOS` (padrão **24 h**); depois o Redis apaga sozinho |
| Pergunta enviada no `/buscar` | Achar os trechos mais parecidos | Só na memória, durante a requisição | **Não é gravada em lugar nenhum**: não entra no índice, no log (só `top_k`, quantos resultados e o tempo) nem no trace |
| Documentos do índice vetorial | Base da busca | Volume `vetorial-dados` (documentos, vetores e vetorizador) | Material público da disciplina (os três textos do C2.A2), sem dado pessoal. Ficam até o volume ser apagado (`docker compose down -v`); no Railway, até o próximo deploy |
| Tarefa que esgotou as tentativas (`WORKER_MAX_TENTATIVAS`, padrão 3) na fila de descarte | Investigar o erro | Redis, `tarefas:descarte` | Só **id, tentativas e mensagem de erro**, sem o texto. No máximo `DESCARTE_MAXIMO` itens (padrão 1000); os mais antigos saem primeiro |
| Usuário e senha do `/login` | Autenticar | Só na memória durante a requisição | Não são guardados nem logados. A comparação é em tempo constante |
| Usuário (dentro do token JWT) | Identificar quem chama e aplicar a cota | Só no token, que fica com o cliente; o servidor não guarda tokens | `JWT_EXPIRA_MINUTOS` (padrão 30 min) |
| IP do cliente / usuário no rate limit | Limitar tentativas de login e chamadas por minuto | Redis, como **apelido HMAC-SHA256 com segredo** (não dá para voltar ao IP) | 60 s (a chave expira com a janela) |
| Rastreamento (spans no Jaeger) | Depurar e medir a latência entre os serviços | Memória do Jaeger, interface só em 127.0.0.1. Só no compose: na nuvem o rastreamento está desligado | Até o Jaeger reiniciar (sem volume). Têm rota, status, tempos e id da tarefa; **nunca texto, senha, token ou IP do cliente** (filtrados no exportador) |
| Logs dos serviços | Operação e depuração | Saída padrão do container; no Railway, a aba de logs de cada serviço | O que a plataforma de hospedagem guardar. Têm método, rota, status, id da tarefa, tamanho da entrada, tempo e `trace_id`; **nunca texto, pergunta, senha, token ou IP** (o access log do uvicorn, que grava o IP de quem chama, está desligado no gateway, na inferência e no vetorial) |

Princípios aplicados (art. 6º da LGPD):
- **Finalidade e necessidade:** o texto só é usado para a classificação. Ele não
  serve para treinar o modelo, que já vem pronto do build, e não é compartilhado
  com terceiros. A pergunta do `/buscar` só é vetorizada para comparar com o índice e
  é descartada no fim da requisição; ela não é indexada. Nenhuma chamada sai para
  fora da rede interna.
- **Minimização:** o resultado não repete o texto e a fila de descarte não o guarda.
- **Prazo de retenção:** o resultado e os contadores do rate limit têm TTL; a
  tarefa sai da fila quando um worker a pega; a fila de descarte, que não tem o
  texto, é limitada por quantidade (`DESCARTE_MAXIMO`), não por tempo. No disco, o
  Redis guarda só um **snapshot do estado atual**, refeito a cada 60 s quando algo
  mudou (`--save 60 1`, sem AOF): tarefa já processada some do snapshot seguinte.
  O AOF ficou desligado de propósito: ele registra cada escrita e guardaria em
  disco o texto de toda tarefa, mesmo depois de processada.
- **Segurança:** só o gateway é exposto; o Redis, a inferência, o vetorial e o worker
  ficam na rede interna (o `/indexar` do vetorial não é alcançável de fora). As rotas
  exigem token e os segredos vêm do `.env`, que não vai para
  o git (na nuvem, das variáveis do Railway). Na nuvem o acesso é **só por HTTPS**
  (`http://` redireciona), então token, senha e texto não trafegam abertos na
  internet (tarefa 8).
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
para de aceitar trabalho. O índice vetorial fica à parte, no volume do serviço
`vetorial`, e não depende do Redis. Cada parte escolhe um lado de propósito:

| Parte | Escolha | Por quê |
|---|---|---|
| `/predict` e `/resultado` | **C** (consistência): Redis fora → 503 com `Retry-After` | Aceitar a tarefa sem conseguir enfileirar seria mentir para o cliente (202 de algo que nunca vai rodar) |
| Rate limit | **A** (disponibilidade): Redis fora → deixa passar (*fail-open*) | O limite protege o sistema mas não é a função dele. Derrubar o gateway por causa do contador seria pior |
| Circuit breaker | **A**, com estado local de cada réplica do gateway | Não depende de ninguém para decidir. As réplicas podem discordar por alguns segundos, e isso é aceitável |
| Resultado | **Consistência eventual**: o `POST /predict` responde 202 e o resultado aparece depois | É o preço da fila assíncrona, que absorve picos e deixa escalar os workers |
| Worker | **No máximo uma entrega**: a tarefa sai da fila no `BLPOP` | Mais simples. Pelo menos uma entrega pediria `BLMOVE` + lista de processamento (ver Resiliência) |
| Busca vetorial | **A** (disponibilidade): serve do índice persistido, que carrega do volume na subida, sem consultar ninguém | Com o Redis fora, o `/buscar` continua respondendo (o rate limit deixa passar). Fica com **uma réplica só**: o volume é de um container por vez, e com várias réplicas cada uma teria a sua cópia do índice, um `/indexar` chegaria a uma só e as respostas divergiriam até todas reindexarem |
| Persistência do Redis | **Privacidade acima de durabilidade**: snapshot a cada 60 s, sem AOF | O AOF guardaria em disco o texto de toda tarefa (ver LGPD). O custo: numa queda brusca do Redis (processo morto, máquina desligada) perde-se o que mudou desde o último snapshot, **até ~60 s de tarefas na fila** e de resultados. Num desligamento normal (`docker compose down`) o Redis grava o snapshot antes de sair e não perde nada |

Para tolerar a queda do Redis, o próximo passo seria Redis com réplica + Sentinel
(ou um Redis gerenciado). Aí entra o trade-off clássico: a replicação do Redis é
assíncrona, e um *failover* pode perder as últimas escritas.

### Latência

| Caminho | Tempo típico | Pior caso |
|---|---|---|
| `POST /predict` (gateway → inferência → Redis) | Poucos ms: só valida e enfileira | ~9 s com a inferência travada (3 tentativas × 3 s de leitura + espera); com o disjuntor aberto, **503 imediato** |
| Inferência no worker (TF-IDF + regressão logística) | Da ordem de milissegundos por texto | Cresce com o tamanho da fila: o tempo de espera ≈ tamanho da fila ÷ (workers × vazão de cada um) |
| `GET /resultado/{id}` | Poucos ms (uma leitura no Redis) | Igual ao `/predict` |
| `POST /buscar` (gateway → vetorial) | Poucos ms: vetoriza a pergunta e calcula o cosseno contra cada documento (medido no compose: ~1 ms de busca e ~7 ms no gateway, com 4 documentos) | Cresce em linha com o número de documentos (busca exaustiva). Com o vetorial parado, 3,5 a 4,5 s (3 tentativas, medido); travado, ~9 s como a inferência; com o disjuntor aberto, **503 imediato** |
| Tempo total para o cliente ver o resultado | Latência da fila + **intervalo de polling** do cliente | — |

Decisões: o modelo é treinado **no build** e carregado **uma vez** na subida, então
nenhuma requisição paga esse custo. O processamento é **assíncrono** porque, com
modelos mais pesados (um LLM, por exemplo), segurar a conexão HTTP escalaria mal. O
custo é o cliente ter que consultar depois. Com este modelo, que é muito rápido, a
rota síncrona da inferência (`/predict-sync`) responderia mais rápido, mas sem
proteção contra picos.

A busca vetorial é **síncrona** (o cliente recebe os trechos na mesma resposta),
porque custa milissegundos e não ocupa os workers. Ela compara a pergunta com todos os
documentos, o que é instantâneo para os textos da disciplina; com milhares de
documentos, o próximo passo seria um índice aproximado (FAISS, HNSW) ou um banco
vetorial.

### Custo

- **Onde está publicado:** Railway, numa **conta de teste** (US$ 5 de crédito,
  válidos por 30 dias), com 5 serviços: Redis (template do Railway, com volume),
  inferência, 1 worker, vetorial e gateway. O crédito é gasto pelo uso de CPU,
  memória, disco e rede dos cinco, ligados o tempo todo. Quando o crédito ou o prazo acabar, o
  Railway para os serviços e **a URL pública sai do ar**; mantê-la exigiria um plano
  pago. O Jaeger fica só no compose local e não consome crédito.
- **Por que não o Render:** no plano grátis do Render não há *background worker*
  gratuito, e os serviços web gratuitos não recebem tráfego da rede privada, então o
  gateway não alcançaria a inferência.
- **O vetorial é um quinto serviço ligado o tempo todo**, e isso custa crédito como os
  outros. Ele é leve: TF-IDF em CPU, ~100 MiB de memória parado e um índice de 11 KB
  com os 4 documentos do teste (medido no compose). A alternativa de pôr a busca dentro
  da inferência economizaria um serviço, mas juntaria duas funções que falham e
  escalam de forma diferente.
- **Imagens enxutas:** `python:3.12-slim`, sem GPU (o modelo é scikit-learn e roda
  em CPU), então cada serviço cabe na menor instância.
- **Cold start:** se os serviços forem configurados para dormir sem uso (para poupar
  crédito), a primeira requisição depois disso paga a subida do container. Como o
  modelo já vem treinado na imagem, essa subida é a menor possível.
- **Escala onde custa:** só os workers precisam de mais réplicas quando a fila
  cresce (`WORKERS` no compose, réplicas/HPA no Kubernetes, *Replicas* no Railway,
  onde cada réplica a mais também gasta crédito). O gateway e a inferência só
  repassam e são leves.
- **O rate limit também controla custo:** um cliente sozinho não consegue gerar
  trabalho ilimitado nos workers.
- **O TTL dos resultados** (LGPD) também segura a memória do Redis, que é o recurso
  mais caro de manter em plano gerenciado.

### Limitação conhecida: o IP atrás do proxy

No Railway o gateway recebe a conexão do proxy da borda e vê o IP dele, não o do
cliente; por isso o limite do `/login` por IP (`LIMITE_LOGIN_POR_MINUTO`) é dividido
entre todos os clientes, e quem errar a senha várias vezes pode travar o login dos
outros até o minuto virar. Ficou assim de propósito: confiar no `X-Forwarded-For` sem
restringir de onde ele vem deixaria o cliente forjar o IP e escapar do limite (o
limite das rotas protegidas é por usuário do token e não é afetado).

---

## Kubernetes (extensão opcional)

A pasta `k8s/` tem os manifests da mesma stack do compose: namespace, ConfigMap,
Secret, Redis com volume, inferência, vetorial com volume (uma réplica), workers (com
HPA por CPU) e gateway. Feito para cluster local (minikube, kind ou o Kubernetes do
Docker Desktop):

```bash
# 1. gere as imagens com os nomes usados nos manifests
docker build -t plataforma-ia/gateway:1.0 ./gateway
docker build -t plataforma-ia/inferencia:1.0 ./inferencia
docker build -t plataforma-ia/vetorial:1.0 ./vetorial
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
├── vetorial/               # armazenamento vetorial (do C2.A2) + Dockerfile
│   ├── app.py              # /buscar, /indexar (só rede interna) e /saude
│   ├── embeddings.py       # vetorizador TF-IDF e similaridade do cosseno
│   ├── armazenamento.py    # grava e lê o índice no volume (gravação atômica)
│   └── documentos/         # textos da disciplina indexados num volume vazio
├── deploy/INSTRUCOES.md    # TAREFAS 5 e 8: passo a passo do deploy no Railway
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

**E se eu não tiver internet no laboratório?** Só o primeiro `docker compose up --build`
precisa de internet, para baixar as imagens e as dependências. Depois disso tudo roda
offline: o modelo é treinado no build, com uma base embutida, e nenhum serviço chama
API externa.

**Posso trocar a linguagem?** O kit é em Python porque é o ecossistema usado nas aulas.
Se quiser usar outra linguagem, converse com o professor antes.

**Posso usar IA para me ajudar a programar?** Sim. Este é um trabalho prático feito fora de
sala, e usar ferramentas de IA é realista. O que se avalia é o **sistema funcionando** e as
**decisões de arquitetura** — que você precisa saber explicar.
