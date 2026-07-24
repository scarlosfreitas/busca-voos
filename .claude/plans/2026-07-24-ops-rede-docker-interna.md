# 2026-07-24 — Plano de Infra: rede Docker interna compartilhada entre os dois composes

## 1. Diagnóstico (estado real observado)

Baseado na leitura direta dos arquivos (não em suposição):

- **Dois projetos compose distintos e isolados em rede:**
  - `/workspace/.devcontainer/docker-compose.yml` sobe `app` (container do Claude Code,
    `command: sleep infinity`) **e** `postgres` (`postgres:16-bookworm`, healthcheck `pg_isready`).
    Não há nenhum bloco `networks:` — ambos rodam na rede `default` implícita do projeto compose do
    devcontainer.
  - `/workspace/docker-compose.yml` (raiz) sobe apenas `app` (Dagster, build de `/workspace/Dockerfile`),
    `DATABASE_URL=postgresql+psycopg://...@postgres:5432/...`. Também sem bloco `networks:`.
- **Por que o hostname `postgres` não resolve hoje:** cada `docker compose up` cria a sua própria
  rede bridge (`<projeto>_default`). O `app` da raiz e o `postgres` do devcontainer estão em redes
  diferentes; o DNS embutido do Docker só resolve nomes de serviço **dentro da mesma rede**. Isso
  está registrado como bloqueio no cabeçalho de `/workspace/docker-compose.yml` (linhas 1-21).
- **Nome do projeto compose do devcontainer é instável:** o VS Code Dev Containers gera o nome do
  projeto (e, portanto, o nome da rede `default`) de forma não determinística para quem executa. Um
  `docker network connect <rede-auto> busca-voos-app` exigiria descobrir esse nome a cada máquina —
  frágil. **Uma rede `external` nomeada elimina essa dependência.**
- **Exposição de portas atual:**
  - `postgres` (devcontainer): `127.0.0.1:${POSTGRES_PORT:-5432}:5432` — exposto ao host "para
    inspeção".
  - `app` (raiz): `127.0.0.1:3000:3000` — UI do Dagster.
- **`.devcontainer/.env`** já fornece `POSTGRES_USER/PASSWORD/DB` e `POSTGRES_PORT=5432`. O `.env`
  da raiz (consumido por `env_file` do `app` da raiz) precisa dos mesmos `POSTGRES_USER/PASSWORD/DB`
  para interpolar `DATABASE_URL` — fora do escopo desta rodada, mas é pré-condição.
- **Docker indisponível dentro do devcontainer** (confirmado no plano anterior). A criação da rede e
  os `docker compose up` são executados **no host** por quem opera (usuário/`infra-runner`).

## 2. Objetivo (estado final desejado)

- Uma **rede Docker bridge nomeada e externa** (`busca-voos-net`), criada **uma vez** no host, à
  qual ambos os projetos compose se conectam via `external: true`. Assim o `app` (raiz) resolve o
  hostname `postgres` (devcontainer) de forma determinística, independente do nome do projeto
  compose.
- **Rede interna por padrão, expondo ao host só o necessário:**
  - **Mantém** `127.0.0.1:3000:3000` (UI do Dagster) — acesso do host é a razão de existir da UI.
  - **Remove** a publicação de `postgres` ao host. O `app` (raiz) e o `app` (dev) falam com o
    `postgres` pela rede interna; inspeção via `psql` continua possível por
    `docker compose exec postgres psql ...` sem porta publicada. Ver D2 (RESOLVIDA: remover —
    decisão do usuário em 2026-07-24, "a rede do docker deve ser interna, expondo apenas as portas
    necessárias").
- Comentário-bloqueio no topo de `/workspace/docker-compose.yml` **substituído** por uma nota
  curta descrevendo a solução (rede compartilhada), já que o bloqueio deixa de existir.

**Decisão de arquitetura da rede (D1, resolvida abaixo):** rede `external: true` nomeada
`busca-voos-net`, criada manualmente no host **antes** de qualquer `docker compose up`. Preferida ao
`docker network connect` pós-hoc por ser determinística e declarativa (fica versionada nos dois
composes).

## 3. Passos (comando/conteúdo exato + critério de verificação)

> Execução no **host** (onde há Docker). O `infra-runner` edita os arquivos; o `docker compose up`
> e a criação da rede rodam no host. Caminhos absolutos a partir de `/workspace`.

### Passo 0 — Pré-condição de ambiente (bloqueante)
No host-alvo:
```bash
docker --version && docker compose version
```
**Verificação:** ambos retornam versão sem erro. Dentro do devcontainer atual isto falha (127) — se
for o caso, parar: os passos de `up`/criação de rede só rodam no host.

### Passo 1 — Criar a rede compartilhada no host (antes de qualquer `up`)
```bash
docker network create busca-voos-net
```
Driver default `bridge` (single-host) é o correto aqui. Idempotência: se já existir, o comando
retorna erro "already exists" — seguro ignorar. Para checar antes:
```bash
docker network inspect busca-voos-net >/dev/null 2>&1 || docker network create busca-voos-net
```
**Verificação:**
```bash
docker network ls --filter name=busca-voos-net --format '{{.Name}} {{.Driver}}'
```
imprime `busca-voos-net bridge`.

### Passo 2 — Editar `/workspace/.devcontainer/docker-compose.yml`
**2a. Serviço `postgres`: remover a publicação de porta ao host** (D2 resolvida: remover).
Remover o bloco:
```yaml
    ports:
      - "127.0.0.1:${POSTGRES_PORT:-5432}:5432"
```

**2b. Serviço `postgres`: anexá-lo à rede `default` (onde já está o `app` do devcontainer) E à
rede compartilhada.** Adicionar, dentro do serviço `postgres` (ex.: logo após `image:`/`environment`
ou antes de `volumes:`):
```yaml
    networks:
      - default
      - shared
```
> Motivo do `default` explícito: ao declarar `networks:` num serviço, o Docker deixa de anexá-lo
> automaticamente à rede `default`. Sem `- default`, o `app` (dev) — que permanece na `default`
> implícita — perderia a resolução do hostname `postgres`. Mantendo as duas, o `app` (dev) fala com
> o `postgres` pela `default` (comportamento atual preservado) e o `app` (raiz) fala pela `shared`.

**2c. Declarar o bloco top-level `networks`** ao final do arquivo (irmão de `volumes:`):
```yaml
networks:
  shared:
    external: true
    name: busca-voos-net
```
Resultado esperado do serviço `postgres` (referência):
```yaml
  postgres:
    image: postgres:16-bookworm
    container_name: ${CONTAINER_NAME}-postgres
    environment:
      - POSTGRES_USER=${POSTGRES_USER}
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - POSTGRES_DB=${POSTGRES_DB}
      - TZ=America/Sao_Paulo
    networks:
      - default
      - shared
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ../scripts/init-db.sql:/docker-entrypoint-initdb.d/10-init-schemas.sql:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 5s
      timeout: 3s
      retries: 10
    restart: unless-stopped
```
> Nota: com a remoção do `ports`, a variável `POSTGRES_PORT` em `.devcontainer/.env` deixa de ser
> usada por este compose. Pode ser mantida (inofensiva, serve de referência) ou removida numa
> limpeza posterior — não bloqueante.

**Verificação (no host):**
```bash
docker compose -f /workspace/.devcontainer/docker-compose.yml config
```
renderiza sem erro; a chave `networks.shared` aparece com `external: true` e `name: busca-voos-net`;
o serviço `postgres` lista `default` e `shared`; **não** há `ports` em `postgres`.

### Passo 3 — Editar `/workspace/docker-compose.yml` (raiz)
**3a. Serviço `app`: anexá-lo à rede compartilhada.** Adicionar dentro do serviço `app` (ex.: após
`ports:` ou antes de `volumes:`):
```yaml
    networks:
      - shared
```
**3b. Declarar o bloco top-level `networks`** (irmão de `volumes:`, ao final):
```yaml
networks:
  shared:
    external: true
    name: busca-voos-net
```
> O `app` da raiz não precisa da rede `default` do projeto raiz — o único par de que ele depende
> (`postgres`) está na `shared`. Manter só `shared` reforça "apenas o necessário".

**Verificação (no host, com `/workspace/.env` presente):**
```bash
docker compose -f /workspace/docker-compose.yml config
```
renderiza sem erro; `services.app.networks` = `[shared]`; `networks.shared` = `external: true`,
`name: busca-voos-net`; `DATABASE_URL` continua apontando para `@postgres:5432` (nunca `localhost`).

### Passo 4 — Atualizar o comentário-bloqueio no topo de `/workspace/docker-compose.yml`
Substituir as linhas 1-21 (todo o bloco "ATENÇÃO — REDE ... mesma rede docker.") por um cabeçalho
enxuto que descreve a solução:
```yaml
# Compose da APLICAÇÃO (busca-voos). Separado do compose do devcontainer
# (.devcontainer/docker-compose.yml), que é apenas o ambiente do Claude Code.
#
# REDE: 'app' (aqui) e 'postgres' (.devcontainer/docker-compose.yml) são projetos compose
# diferentes, mas compartilham a rede docker externa 'busca-voos-net' (external: true nos dois
# arquivos). Isso permite que 'app' resolva o hostname 'postgres' pela rede interna.
# Pré-requisito no host, UMA vez, antes de qualquer `docker compose up`:
#     docker network create busca-voos-net
# O 'postgres' NÃO é publicado ao host; o acesso é só pela rede interna (inspeção via
# `docker compose -f .devcontainer/docker-compose.yml exec postgres psql ...`).
```
As linhas 33-35 (comentário interno em `environment:` que referencia "a nota de REDE no topo") podem
ser mantidas ou simplificadas para "host = nome do serviço 'postgres', resolvido pela rede
compartilhada 'busca-voos-net'." — não bloqueante.

**Verificação:** `docker compose -f /workspace/docker-compose.yml config` continua válido; o texto de
"bloqueio"/"não é possível resolver apenas editando este compose" não existe mais no arquivo.

### Passo 5 — Validação ponta a ponta (no host)
Ordem importa: o `postgres` (devcontainer) precisa estar de pé antes do `app` (raiz).
```bash
# 1) rede já criada (Passo 1)
# 2) sobe o postgres via projeto do devcontainer
docker compose -f /workspace/.devcontainer/docker-compose.yml up -d postgres
docker compose -f /workspace/.devcontainer/docker-compose.yml ps        # postgres 'healthy' em <60s
# 3) confere que o postgres entrou na rede compartilhada
docker network inspect busca-voos-net --format '{{range .Containers}}{{.Name}} {{end}}'
#    -> deve listar 'busca-voos-postgres'
# 4) sobe o app da raiz e testa a resolução do hostname pela rede interna
docker compose -f /workspace/docker-compose.yml up -d app
docker compose -f /workspace/docker-compose.yml exec app \
  python -c "import socket; print(socket.gethostbyname('postgres'))"
#    -> imprime um IP da subnet de busca-voos-net (resolução OK)
```
**Verificação:** o `getent`/`gethostbyname` de `postgres` resolve a partir do `app` da raiz; a UI do
Dagster responde em `http://127.0.0.1:3000`; `docker port busca-voos-postgres` **não** lista `5432`
publicado.

## 4. Riscos e decisões

- **D1 — RESOLVIDO.** Rede `external: true` nomeada `busca-voos-net`, criada manualmente no host
  (Passo 1), declarada nos dois composes. Preferida ao `docker network connect` por ser
  determinística e versionada.
- **D2 — RESOLVIDO: remover a exposição do Postgres ao host.** Decisão do usuário em 2026-07-24:
  "a rede do docker deve ser interna, expondo apenas as portas necessárias". `app` (raiz) e `app`
  (dev) já alcançam `postgres` pela rede interna; inspeção manual continua viável via
  `docker compose ... exec postgres psql`. Menor superfície exposta ao host.
- **Risco — ordem de subida entre projetos compose.** `depends_on: condition: service_healthy`
  **não** funciona entre projetos compose diferentes; o `app` (raiz) não pode depender do
  `postgres` (devcontainer). Mitigações: (a) subir o devcontainer/`postgres` **antes** do `app`
  (raiz) — Passo 5; (b) o `app` (raiz) tem `restart: unless-stopped`, então se subir antes do banco
  ficar `healthy`, reinicia até conectar. Não é bloqueante, mas o operador deve seguir a ordem do
  Passo 5.
- **Risco — rede inexistente no `up`.** Com `external: true`, se `busca-voos-net` não existir, o
  `docker compose up` **falha** com "network busca-voos-net declared as external, but could not be
  found". O Passo 1 é pré-requisito obrigatório; mitigado pelo one-liner idempotente.
- **Pré-condição fora de escopo desta rodada.** O `.env` da raiz precisa conter
  `POSTGRES_USER/PASSWORD/DB` iguais aos do `.devcontainer/.env` para o `DATABASE_URL` do `app`
  (raiz) casar com as credenciais do `postgres`. Divergência = falha de autenticação (não de rede).
  Confirmar antes do Passo 5.
- **Observação — driver de rede.** `bridge` (default) cobre single-host, que é o cenário do MVP. Se
  no futuro os composes rodarem em hosts diferentes (produção K3s/Proxmox, pós-MVP), esta solução de
  rede bridge compartilhada não se aplica — seria outra topologia (overlay/serviço nomeado no
  cluster), fora do escopo atual.
