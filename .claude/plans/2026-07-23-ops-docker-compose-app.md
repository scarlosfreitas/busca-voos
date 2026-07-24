# 2026-07-23 — Plano de Infra: `docker-compose.yml` da aplicação (`app` + `postgres`)

## 1. Diagnóstico (estado real observado)

- **Único compose existente é o de DEV:** `.devcontainer/docker-compose.yml` sobe um serviço `app`
  que é `debian:bookworm-slim` (Node + Chrome + Claude Code) com `command: sleep infinity`. É o
  ambiente do Claude Code, **não** a aplicação. Confirmado pelo `.devcontainer/Dockerfile` (linha
  1: "Infra de DESENVOLVIMENTO; o Dockerfile/compose de produção virão na raiz").
- **`.devcontainer/.env`** contém apenas `DOCKER_IMAGE_NAME`, `DOCKER_IMAGE_TAG`, `CONTAINER_NAME`
  — nada de segredos de aplicação. É referenciado só pelo compose de dev.
- **`.gitignore`** ignora `.devcontainer/.env`, mas **não** ignora um `.env` na raiz (que a
  aplicação vai precisar).
- **Não existe** `docker-compose.yml`, `Dockerfile`, `pyproject.toml`, `uv.lock` na raiz. `src/` e
  `test/` têm apenas READMEs-marcador. `scripts/` tem só `clean.sh` e `plugins.sh` — **não há**
  `init-db.sql`.
- **Docker indisponível neste container:** `which docker` falha; `docker ps` retorna 127. O
  devcontainer não expõe o daemon Docker.
- **Convenções do projeto (skills instaladas):** `docker-patterns/SKILL.md` recomenda pin de
  versão (nunca `:latest`), non-root, healthcheck no Postgres com
  `depends_on: condition: service_healthy`, expor portas só em `127.0.0.1`, segredos via
  `env_file` gitignored, schemas via script em `/docker-entrypoint-initdb.d`.
  `docs/standards/architecture.md` §4 fixa `uv` + `pyproject.toml`/`uv.lock`, `alembic` para
  tabelas (schemas via init), logging pelo Dagster.
- **Padrões que o compose precisa honrar** (`architecture.md` §3/§5/§7 + `PRD.md` §6): schemas
  `bronze`/`silver`/`gold`; segredos só via `.env`; sem `localhost` hardcoded (usar nome de
  serviço); timeouts Playwright de 5+ min; campo de proxy pronto mas vazio.

## 2. Objetivo (estado final desejado) — REVISADO após decisão do usuário

**Decisão do usuário (substitui a proposta original de compose separado na raiz):** o serviço
`postgres` é adicionado como serviço-irmão **dentro de `.devcontainer/docker-compose.yml`** (o
mesmo compose que já sobe o container de desenvolvimento), não em um compose novo na raiz. Isso
resolve o bloqueio D1 (Docker indisponível dentro do devcontainer): como o `postgres` sobe no
**mesmo** `docker compose up` que o host já usa para levantar o devcontainer, o container `app`
(dev) enxerga o `postgres` pela rede do compose usando o nome do serviço — sem precisar de Docker
acessível *dentro* do devcontainer.

- Portas do `postgres` expostas ao host, com os valores parametrizados em `.devcontainer/.env`
  (ex.: `POSTGRES_PORT=5432`), seguindo o padrão já usado nesse arquivo (`DOCKER_IMAGE_NAME`,
  `CONTAINER_NAME`, etc.).
- Instalação de dependências Python **inteiramente via `uv`** (`uv sync`, `pyproject.toml` +
  `uv.lock`) — sem `pip install` manual, confirmando `architecture.md` §4.
- O serviço `app` da aplicação (imagem `mcr.microsoft.com/playwright/python` rodando Dagster)
  **fica para uma etapa posterior**: por ora, se/quando existir, sobe com `command: sleep infinity`
  como placeholder, já que não há código Dagster (`src/orchestration`, `workspace.yaml`) ainda —
  evita crash-loop.
- Schemas `bronze`/`silver`/`gold` continuam via `scripts/init-db.sql` montado em
  `/docker-entrypoint-initdb.d`.

**Execução desta rodada:** por decisão do usuário, esta tarefa fica **registrada como plano**, mas
a execução (`run-ops` criando/editando `.devcontainer/docker-compose.yml`, `.devcontainer/.env`,
`scripts/init-db.sql`, `pyproject.toml`) **não roda agora** — apenas o registro do plano foi
publicado. Retomar com o `run-ops` quando o usuário pedir.

## 3. Passos (comando/conteúdo exato + critério de verificação)

> O `run-ops` cria/edita os arquivos abaixo. Todos os caminhos são absolutos a partir de
> `/workspace`.

### Passo 0 — Pré-condição de ambiente (bloqueante)
Confirmar em **qual host** o compose vai rodar e que ali existe Docker. Rodar no host-alvo:
```bash
docker --version && docker compose version
```
**Verificação:** ambos retornam versão sem erro. Se rodar dentro do devcontainer atual, isto
**falhará** (127) — nesse caso, parar e resolver a decisão em aberto D1 antes de prosseguir.

### Passo 1 — `/workspace/scripts/init-db.sql` (criação dos schemas Medallion)
```sql
-- Schemas da arquitetura Medallion (architecture.md §3).
-- Apenas os SCHEMAS; as TABELAS são criadas por migrations Alembic (architecture.md §4).
CREATE SCHEMA IF NOT EXISTS bronze;
CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS gold;
```
**Verificação:** após subir o postgres (Passo 6), `docker compose exec postgres psql -U
"$POSTGRES_USER" -d "$POSTGRES_DB" -c "\dn"` lista `bronze`, `silver`, `gold`.

### Passo 2 — `/workspace/.env.example` (template commitado, sem valores reais)
```dotenv
# ── PostgreSQL ────────────────────────────────────────────────
POSTGRES_USER=buscavoos
POSTGRES_PASSWORD=troque-por-uma-senha-forte
POSTGRES_DB=buscavoos

# ── Telegram (bot a criar via @BotFather) ─────────────────────
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# ── Playwright ────────────────────────────────────────────────
# Timeout alto (5+ min) exigido pelo PRD §6 / architecture.md §6
PLAYWRIGHT_TIMEOUT_MS=300000

# ── Proxy residencial ─────────────────────────────────────────
# Provedor a definir (Bright Data/Oxylabs). Deixar VAZIO até contratar;
# o MVP roda sem proxy. Formato futuro: http://user:pass@host:port
PROXY_URL=

# ── Build ─────────────────────────────────────────────────────
APP_IMAGE_TAG=dev
```
**Verificação:** `git status` mostra `.env.example` como novo arquivo rastreável; não contém
nenhum segredo real.

### Passo 3 — `/workspace/.env` (real, NÃO commitado — criado pelo usuário)
O `run-ops` **não** preenche segredos. Instrução: copiar o exemplo e preencher no host:
```bash
cp /workspace/.env.example /workspace/.env
# editar POSTGRES_PASSWORD, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
```
**Verificação:** `/workspace/.env` existe, tem `POSTGRES_PASSWORD` preenchido; `git check-ignore
/workspace/.env` retorna o caminho (ou seja, está ignorado — depende do Passo 4).

### Passo 4 — Editar `/workspace/.gitignore` (ignorar o `.env` da raiz)
Adicionar sob a seção "Segredos / config local", logo após a linha `.devcontainer/.env`:
```gitignore
# .env da APLICAÇÃO na raiz (segredos: Postgres, Telegram, proxy)
/.env
```
**Verificação:** `git check-ignore /workspace/.env` imprime `/workspace/.env`. `git status`
**não** lista `.env`.

### Passo 5 — `/workspace/Dockerfile` (imagem da aplicação)
```dockerfile
# syntax=docker/dockerfile:1
# Imagem base oficial da Microsoft com browsers + libs de SO do Playwright (PRD §6).
# ATENÇÃO: a tag DEVE casar com a versão de 'playwright' no pyproject.toml (ver D3).
FROM mcr.microsoft.com/playwright/python:v1.55.0-noble

# Gerenciador de dependências uv (architecture.md §4)
COPY --from=ghcr.io/astral-sh/uv:0.9.9 /uv /uvx /bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DAGSTER_HOME=/opt/dagster/dagster_home

WORKDIR /app

# Camada de dependências (cache eficiente): copia só os manifestos primeiro.
COPY pyproject.toml ./
# Usa uv.lock se existir (build reprodutível); senão resolve na hora (bootstrap).
COPY uv.loc[k] ./
RUN if [ -f uv.lock ]; then uv sync --frozen --no-install-project; \
    else uv sync --no-install-project; fi

# Código da aplicação
COPY src/ ./src/
COPY workspace.yaml ./

RUN mkdir -p /opt/dagster/dagster_home

EXPOSE 3000
# Sobe daemon + UI do Dagster (logs visíveis na UI, architecture.md §4).
# 'dagster dev' é adequado para o deploy LOCAL do MVP; produção separaria
# webserver/daemon (ver D4).
CMD ["uv", "run", "dagster", "dev", "-w", "workspace.yaml", "-h", "0.0.0.0", "-p", "3000"]
```
Notas: o `COPY uv.loc[k]` é um glob que não falha se o arquivo não existir. `workspace.yaml` e
`src/orchestration` **ainda não existem** — a imagem builda, mas o container `app` só sobe de fato
após a trilha `plan-dev` entregar o código do Dagster (ver D2/D4 e sequência).
**Verificação:** no host, `docker compose build app` conclui sem erro e `docker run --rm
busca-voos-app:dev uv run python -c "import playwright; print('ok')"` imprime `ok`.

### Passo 6 — `/workspace/docker-compose.yml` (aplicação — raiz)
```yaml
# Compose da APLICAÇÃO (busca-voos). Separado do compose do devcontainer
# (.devcontainer/docker-compose.yml), que é apenas o ambiente do Claude Code.
services:
  app:
    build:
      context: .
      dockerfile: Dockerfile
    image: busca-voos-app:${APP_IMAGE_TAG:-dev}
    container_name: busca-voos-app
    env_file:
      - .env
    environment:
      TZ: America/Sao_Paulo
      # Sem localhost hardcoded: host = nome do serviço 'postgres' (architecture.md §7)
      DATABASE_URL: postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
      DAGSTER_HOME: /opt/dagster/dagster_home
      PLAYWRIGHT_TIMEOUT_MS: ${PLAYWRIGHT_TIMEOUT_MS:-300000}
      PROXY_URL: ${PROXY_URL:-}
    depends_on:
      postgres:
        condition: service_healthy
    ports:
      - "127.0.0.1:3000:3000"   # UI do Dagster, só acessível do host
    volumes:
      - dagster_home:/opt/dagster/dagster_home
    restart: unless-stopped

  postgres:
    image: postgres:16-bookworm
    container_name: busca-voos-postgres
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    ports:
      - "127.0.0.1:5432:5432"   # exposto só ao host para inspeção; app usa a rede interna
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./scripts/init-db.sql:/docker-entrypoint-initdb.d/10-init-schemas.sql:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 5s
      timeout: 3s
      retries: 10
    restart: unless-stopped

volumes:
  pgdata:
  dagster_home:
```
**Verificação:**
- `docker compose config` (no host, com `.env` presente) renderiza sem erro e mostra
  `DATABASE_URL` apontando para `@postgres:5432` (nunca `localhost`) e `PROXY_URL` vazio.
- `docker compose up -d postgres` → `docker compose ps` mostra `postgres` como `healthy` em <60s.
- Schemas conferidos pelo critério do Passo 1.

### Passo 7 — `/workspace/.dockerignore`
```gitignore
.git
.venv
__pycache__/
*.py[cod]
.env
.env.*
.devcontainer/
.claude/
.agents/
docs/
test/
*.md
docker-compose.yml
Dockerfile
.dockerignore
scripts/clean.sh
scripts/plugins.sh
```
**Verificação:** `docker compose build app` não copia `.env` nem `.git` para a imagem (`docker run
--rm busca-voos-app:dev ls -a /app` não lista `.env`).

### Passo 8 — `/workspace/pyproject.toml` (mínimo — ver decisão D2)
**Somente se aprovado D2.** Versões a fixar pelo `plan-dev`:
```toml
[project]
name = "busca-voos"
version = "0.1.0"
description = "Monitoramento e alerta de passagens aéreas (Gol) via Playwright + Dagster."
requires-python = ">=3.11"
dependencies = [
    "dagster",
    "dagster-webserver",
    "playwright",
    "playwright-stealth",
    "sqlalchemy",
    "psycopg[binary]",
    "alembic",
    "python-telegram-bot",
]

[dependency-groups]
dev = ["ruff", "pytest"]

[tool.uv]
package = false
```
**Verificação:** `uv lock` (no host ou no build) resolve sem conflito e gera `uv.lock`; `docker
compose build app` conclui.

## 4. Decisões — status após resposta do usuário (2026-07-23)

- **D1 — RESOLVIDO.** `postgres` entra como serviço-irmão em `.devcontainer/docker-compose.yml`
  (não compose separado na raiz). Ver seção 2. Os Passos 5–7 (Dockerfile/compose/dockerignore da
  aplicação na raiz) ficam **adiados** — só fazem sentido quando o serviço `app` de produção for
  desenhado separadamente do devcontainer.
- **D2 — RESOLVIDO.** Instalação 100% via `uv` (`pyproject.toml` + `uv.lock`, `uv sync`), sem
  `pip install` manual — confirma `architecture.md` §4. `pyproject.toml` mínimo ainda a criar
  quando o `run-ops` for acionado.
- **D3 — Ainda em aberto.** Tag da imagem `mcr.microsoft.com/playwright/python` precisa casar com
  a versão de `playwright` fixada no `pyproject.toml` — decisão do `plan-dev`/`run-ops` na próxima
  execução.
- **D4 — RESOLVIDO.** Placeholder `command: sleep infinity` para qualquer serviço `app` de
  produção até existir código Dagster (`src/orchestration`, `workspace.yaml`).
- **D5 — Ainda em aberto**, mas menos urgente dado D1: como o `postgres` agora sobe junto do
  devcontainer, `src/domain/` pode começar a ser desenvolvido (via `plan-dev`) assim que o
  `run-ops` aplicar o Passo 1 (schemas) e a nova versão dos Passos do `.devcontainer/`.
- **Execução:** adiada a pedido do usuário nesta rodada — apenas o registro do plano foi
  commitado/publicado. Retomar com `run-ops` quando solicitado.
- **Risco menor — non-root.** A imagem Playwright roda como root por padrão; hardening
  (`user: pwuser`) fica para iteração posterior.
- **Risco menor — exposição de portas.** Porta do `postgres` exposta ao host conforme pedido pelo
  usuário; revisar se deve ficar restrita a `127.0.0.1` quando o `run-ops` for acionado.
