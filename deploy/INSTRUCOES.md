# Deploy em nuvem: Railway (TAREFAS 5 e 8)

A versão publicada está em **https://gateway-production-f3318087.up.railway.app**.
Este é o passo a passo de como ela foi montada, para repetir numa conta sua.

## O que roda lá

Um projeto do Railway com **4 serviços**, todos deste repositório (branch `main`),
com novo deploy automático a cada push. Cada um usa o `Dockerfile` da própria pasta,
a mesma imagem do compose.

| Serviço | Origem | Rede | Variáveis |
|---|---|---|---|
| `Redis` | template de banco do Railway, com volume | só privada | criadas pelo template |
| `inferencia` | repositório, Root Directory `/inferencia` | só privada (porta 8001) | `REDIS_URL` |
| `worker` | repositório, Root Directory `/worker`, 1 réplica | só privada (sem porta) | `REDIS_URL` |
| `gateway` | repositório, Root Directory `/gateway` | **pública, HTTPS** (porta 8000) | `REDIS_URL`, `URL_INFERENCIA`, `JWT_SEGREDO`, `GATEWAY_USUARIO`, `GATEWAY_SENHA` |

Só o gateway tem domínio. Inferência, worker e Redis conversam pela rede privada do
projeto e não respondem de fora, como no compose.

**Por que não o Render:** no plano grátis do Render não há *background worker*
gratuito (o worker não teria onde rodar), e os serviços web gratuitos não recebem
tráfego da rede privada, então o gateway não alcançaria a inferência.

## Passo a passo

1. Crie a conta em railway.app entrando com o GitHub. A conta de teste dá US$ 5 de
   crédito por 30 dias; acabou o crédito ou o prazo, os serviços param.
2. Crie um projeto e adicione o **Redis** pelo template de banco (*Database → Redis*).
   Ele já vem com volume e com a variável `REDIS_URL`.
3. Adicione **três serviços a partir do repositório do GitHub** (o seu fork) e, em
   cada um, configure em *Settings*:
   - **Source → Root Directory:** `/inferencia`, `/worker` e `/gateway`;
   - **nome do serviço:** `inferencia`, `worker` e `gateway`. O nome importa: é ele
     que aparece nas referências `${{...}}` do passo 4;
   - no `worker`, **Deploy → Replicas:** 1 (mais réplicas dividem a fila, mas gastam
     mais crédito).
4. Defina as **variáveis** na aba *Variables* de cada serviço (o *Raw Editor* aceita
   colar tudo de uma vez). O Railway troca `${{Servico.VARIAVEL}}` pelo valor do outro
   serviço:

   `inferencia` e `worker`:
   ```
   REDIS_URL=${{Redis.REDIS_URL}}
   ```

   `gateway`:
   ```
   REDIS_URL=${{Redis.REDIS_URL}}
   URL_INFERENCIA=http://${{inferencia.RAILWAY_PRIVATE_DOMAIN}}:8001
   JWT_SEGREDO=<segredo gerado>
   GATEWAY_USUARIO=<usuario do login>
   GATEWAY_SENHA=<senha gerada>
   ```

   O gateway **não sobe** sem `JWT_SEGREDO`, `GATEWAY_USUARIO` e `GATEWAY_SENHA`, e sem
   `REDIS_URL` ele procuraria o Redis em `localhost`. Gere o segredo e a senha com o
   comando abaixo, uma vez para cada, e cole direto no painel, **nunca num arquivo do
   repositório** (ele é público):
   ```
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
   As demais variáveis (limites, tempos-limite, TTL) têm padrão no código. **Não**
   defina `OTEL_EXPORTER_OTLP_ENDPOINT`: não há Jaeger no Railway e, sem ela, o
   rastreamento fica desligado e os serviços rodam igual.
5. **Domínio público, só no gateway:** *Settings → Networking → Generate Domain*,
   porta **8000**. O Railway entrega um endereço `*.up.railway.app` com **HTTPS**
   (tarefa 8): o TLS é terminado na borda dele, com certificado Let's Encrypt emitido
   e renovado sozinho, e `http://` redireciona (301) para `https://`. O gateway segue
   escutando HTTP na porta 8000 dentro da rede do Railway e não precisa de certificado.
6. Aguarde os quatro serviços ficarem ativos. Daí em diante, cada push na `main`
   gera um deploy novo.

## Como testar

```bash
BASE=https://<seu-dominio>.up.railway.app
curl $BASE/saude                    # 200 {"status":"ok","disjuntor_inferencia":"fechado"}
curl -I http://<seu-dominio>.up.railway.app/saude   # 301 para https://
curl -X POST $BASE/predict          # 401: sem token
```

O fluxo completo (login → predict → resultado) é o do passo 4 do README, trocando
`http://127.0.0.1:8000` pela URL `https://`; está pronto na seção *Testar na nuvem*.
`/docs` também funciona pela URL pública.

## Se der 503 no `/predict`

O `/saude` responde 200 mesmo com a inferência inalcançável (ele só informa o estado
do disjuntor). Se o `/predict` voltar **503** e o `/saude` mostrar o disjuntor
`aberto`, o gateway não está alcançando a inferência pela rede privada. A rede
privada do Railway é IPv6, e a inferência escuta só em IPv4 (`--host 0.0.0.0`). A
correção é, na inferência, *Settings → Deploy → Custom Start Command*:

```
uvicorn app:app --host :: --port 8001 --no-access-log
```

Com `--host ::` ela aceita IPv6 e IPv4. O `--no-access-log` continua lá para o log
não gravar o IP de quem chama (LGPD).
