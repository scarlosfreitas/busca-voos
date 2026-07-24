# 2026-07-24 — Plano de Infra: criar workspace.yaml e validar a stack completa (docker-compose)

## 1. Diagnóstico (estado real observado)

Baseado em leitura de arquivos + comandos somente-leitura (não em suposição):

- **`workspace.yaml` NÃO existe na raiz** (`ls: cannot access 'workspace.yaml': No such file or
  directory`). O `/workspace/Dockerfile` faz `COPY workspace.yaml ./` (linha 25) e
  `CMD ["uv","run","dagster","dev","-w","workspace.yaml", ...]` (linha 33). **O build quebra hoje no
  passo do COPY** — arquivo ausente.
- **O code location alvo é `src/orchestration/assets.py`, símbolo `defs`** (objeto
  `dagster.Definitions`, linhas 685-689). O módulo usa **imports absolutos sem prefixo `src.`**
  (`from domain.deduplication import ...`, `from extraction.gol import ...`, etc., linhas 54-72).
- **`src` NÃO é instalado como pacote:** `pyproject.toml` tem `[tool.uv] package = false`. O
  `pythonpath = ["src"]` em `[tool.pytest.ini_options]` **só vale para o pytest** — não afeta o
  runtime do `dagster dev`. O Dockerfile faz `uv sync --no-install-project` e copia `src/` para
  `/app/src/`, **sem** definir `PYTHONPATH`. Logo, para o Dagster resolver `domain`/`extraction`/…
  é preciso pôr `src` no `sys.path` **via o próprio `workspace.yaml`** (chave `working_directory`).
- **Ambiente local de validação disponível:** `uv` (`/usr/local/bin/uv`), `uv.lock` presente
  (424 KB), `dagster 1.13.15`. Permite validar o workspace **fora de container** antes do build.
- **Docker indisponível dentro do devcontainer:** `docker: command not found` (confirmado; também
  registrado na memória do projeto). **Todos os passos de rede/build/up (3–7) rodam no HOST.**
- **Rede compartilhada `busca-voos-net`:** ambos os composes declaram `networks.shared` como
  `external: true`, `name: busca-voos-net` (ver plano `2026-07-24-ops-rede-docker-interna.md`, já
  aplicado nos arquivos). Pré-requisito: a rede existir no host **antes** de qualquer `up`.
- **`.env` da raiz OK:** `/workspace/.env` contém `POSTGRES_USER/PASSWORD/DB`, `TELEGRAM_*`,
  `PLAYWRIGHT_TIMEOUT_MS`, `PROXY_URL`, `APP_IMAGE_TAG` — cobre a interpolação de `DATABASE_URL` e o
  `env_file` do serviço `app` da raiz.
- **`app` (raiz) NÃO tem `healthcheck`** no `docker-compose.yml`. `docker compose ps` não mostrará
  `healthy`; a verificação de subida é por log + HTTP na porta 3000.

### Validação já executada por este planner (somente-leitura, fora do projeto)

Reproduzido no scratchpad o mecanismo de carregamento exato do `workspace.yaml` proposto:

- `dagster definitions validate -f src/orchestration/assets.py -d src` → **"All code locations
  passed validation."**
- Um `workspace.yaml` com `python_file` + `working_directory: src` + `attribute: defs` →
  **"Validation successful for code location assets.py:defs."**
- Rodando de um **cwd diferente** (`/tmp`), com paths relativos no yaml → ainda válido: confirma que
  `relative_path` e `working_directory` resolvem **relativo ao diretório do `workspace.yaml`**, que
  é exatamente o cenário do container (`workspace.yaml` em `/app`, `src` em `/app/src`).

## 2. Objetivo (estado final desejado)

1. `/workspace/workspace.yaml` existente, apontando para `src/orchestration/assets.py` (símbolo
   `defs`), com `src` no `sys.path` via `working_directory`.
2. Workspace validando localmente (`uv run dagster definitions validate`) sem erro.
3. Stack subindo via os dois composes na rede `busca-voos-net`: `postgres` (devcontainer) +
   `app`/Dagster (raiz), com a UI respondendo em `127.0.0.1:3000` e o code location carregado sem
   erro de import, resolvendo o hostname `postgres` pela rede interna.

## 3. Passos (comando/conteúdo exato + critério de verificação)

> Passos 1–2 podem rodar **no devcontainer** (há `uv`+`dagster`). Passos 3–7 rodam **no HOST**
> (Docker indisponível no devcontainer). Caminhos absolutos a partir de `/workspace`.

### Passo 1 — Criar `/workspace/workspace.yaml`
Conteúdo **exato** (validado por este planner com dagster 1.13.15):
```yaml
# Code location do pipeline (architecture.md §1: um único entrypoint, sem API/frontend).
# 'working_directory: src' coloca /app/src no sys.path para resolver os imports absolutos do
# módulo (from domain..., from extraction..., etc.), já que pyproject tem [tool.uv] package = false
# (src NÃO é instalado como pacote; pythonpath=["src"] do pytest não vale no runtime do dagster).
# 'relative_path'/'working_directory' resolvem relativo à pasta deste arquivo (=/app no container).
load_from:
  - python_file:
      relative_path: src/orchestration/assets.py
      working_directory: src
      attribute: defs
```
**Verificação:** `test -f /workspace/workspace.yaml` retorna 0; o conteúdo bate com o acima.

### Passo 2 — Validar o workspace localmente (fora de container; iteração rápida)
No devcontainer ou host com `uv`, a partir de `/workspace`:
```bash
cd /workspace && env -u DAGSTER_HOME uv run dagster definitions validate -w workspace.yaml
```
> `env -u DAGSTER_HOME`: se `DAGSTER_HOME` estiver exportado apontando para diretório inexistente,
> o comando aborta antes de validar. Sem a var, o Dagster usa uma instância temporária.
> O comando emite um `SupersessionWarning` sugerindo `dg check defs` — é só aviso, ignorar.

**Verificação:** saída contém `Validation successful for code location assets.py:defs.` e
`All code locations passed validation.`; **exit code 0**. Se falhar aqui (ex.: `ModuleNotFoundError:
domain`), **parar** — o problema é de `workspace.yaml`/`working_directory`, não vale gastar um build
Docker. Corrigir o Passo 1 e repetir.

### Passo 3 — Garantir a rede compartilhada no host (idempotente)
No **host**:
```bash
docker network inspect busca-voos-net >/dev/null 2>&1 || docker network create busca-voos-net
```
**Verificação:**
```bash
docker network ls --filter name=busca-voos-net --format '{{.Name}} {{.Driver}}'
```
imprime `busca-voos-net bridge`.

### Passo 4 — Garantir o `postgres` de pé (devcontainer compose) na rede compartilhada
No **host**:
```bash
docker compose -f /workspace/.devcontainer/docker-compose.yml ps
# Se 'postgres' não estiver 'healthy', subir/atualizar só o postgres:
docker compose -f /workspace/.devcontainer/docker-compose.yml up -d postgres
```
**Verificação:**
```bash
docker compose -f /workspace/.devcontainer/docker-compose.yml ps        # postgres 'healthy' em <60s
docker network inspect busca-voos-net --format '{{range .Containers}}{{.Name}} {{end}}'
#   -> deve listar o container do postgres (ex.: '<CONTAINER_NAME>-postgres')
```

### Passo 5 — Build + up do serviço `app` (compose da raiz)
No **host**, a partir de `/workspace` (onde estão `docker-compose.yml`, `Dockerfile`, `.env`):
```bash
cd /workspace
docker compose build app          # COPY workspace.yaml agora encontra o arquivo (Passo 1)
docker compose up -d app
```
**Verificação (build):** o build conclui sem erro; em especial **não** falha em
`COPY workspace.yaml ./` (regressão original) nem no `uv sync`.
**Verificação (up):** `docker compose ps` mostra `busca-voos-app` em estado `running` (NÃO há
`healthcheck` neste serviço — não espere `healthy`).

### Passo 6 — Validar a subida do `app` (code location + rede + UI)
No **host**:
```bash
# 6a. Code location carregou sem erro de import no boot do dagster dev:
docker compose -f /workspace/docker-compose.yml logs app | tail -40
#   -> procurar 'Serving dagster-webserver on http://0.0.0.0:3000' e a ausência de
#      'Error loading repository location' / ModuleNotFoundError / traceback.

# 6b. UI respondendo no host:
curl -sSf -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/server_info
#   -> 200

# 6c. Resolução do hostname 'postgres' pela rede interna, a partir do app:
docker compose -f /workspace/docker-compose.yml exec app \
  python -c "import socket; print(socket.gethostbyname('postgres'))"
#   -> imprime um IP da subnet de busca-voos-net (resolução OK)
```
**Verificação:** (6a) log de subida do webserver + sem traceback de import; (6b) HTTP 200; (6c)
`postgres` resolve para um IP. Os três juntos comprovam que a stack completa sobe e o code location
carrega dentro do container.

### Passo 7 — Rollback / diagnóstico se o build ou o boot falhar
- **Falha de import do code location dentro do container** (ex.: `ModuleNotFoundError: domain` no
  log do 6a): reproduzir o carregamento isolado dentro da imagem, sem depender do daemon:
  ```bash
  docker compose -f /workspace/docker-compose.yml run --rm --no-deps --entrypoint sh app -c \
    "cd /app && env -u DAGSTER_HOME uv run dagster definitions validate -w workspace.yaml"
  ```
  - Se falhar aqui, checar dentro da imagem: `docker compose run --rm --entrypoint sh app -c
    'ls -la /app /app/src && grep -n "package" /app/pyproject.toml && cat /app/workspace.yaml'`.
    Causa provável: `working_directory: src` ausente/errado no `workspace.yaml`, ou `src/` não
    copiado. **Volta para o infra-planner** se o `workspace.yaml` precisar de outra estratégia
    (ex.: `PYTHONPATH=src` no Dockerfile em vez de `working_directory`). Não improvisar edição do
    Dockerfile na execução.
- **Falha no `COPY workspace.yaml`**: o Passo 1 não foi aplicado ou o arquivo está fora de
  `/workspace`. Recriar e refazer `docker compose build app`.
- **Derrubar apenas o `app` da raiz sem afetar o postgres nem os volumes:**
  ```bash
  docker compose -f /workspace/docker-compose.yml down
  ```
  (SEM `-v` — preserva o volume `dagster_home`; o `postgres`/`pgdata` pertence ao outro projeto
  compose e não é tocado.)

## 4. Riscos e decisões em aberto

- **D1 — RESOLVIDO: como pôr `src` no path no runtime.** Escolhido `working_directory: src` no
  `workspace.yaml` (validado localmente), em vez de `PYTHONPATH=src` no Dockerfile ou
  `package = true`. Motivo: mantém a config de carregamento junto ao code location, não altera o
  contrato de build nem o `pyproject.toml`. Alternativa (fallback do Passo 7): `ENV PYTHONPATH=/app/src`
  no Dockerfile — só se o `working_directory` se mostrar insuficiente no container.
- **`attribute: defs` explícito.** Há vários símbolos top-level no módulo (`daily_flight_search_job`,
  `daily_flight_search_schedule`, `defs`). Fixar `attribute: defs` evita ambiguidade de
  auto-detecção do Dagster.
- **Ordem entre projetos compose (herdado do plano de rede).** `depends_on` não cruza projetos
  compose; subir `postgres` (Passo 4) **antes** do `app` (Passo 5). O `app` tem
  `restart: unless-stopped` como mitigação, mas seguir a ordem evita ruído de reinício.
- **`app` da raiz sem healthcheck.** A verificação de saúde é manual (log + `curl :3000`), não via
  `docker compose ps`. Se desejável no futuro, adicionar `healthcheck` HTTP ao serviço `app` — fora
  do escopo desta rodada.
- **Segredos.** `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`/`PROXY_URL` vêm do `/workspace/.env` (não
  commitado). Este plano não gera nem inspeciona valores; apenas confirma que as **chaves** existem.
  Nota: o `.env` da raiz tem `GIT_TOKKEN` (aparente typo), irrelevante para esta stack.
- **Pré-condição de credenciais.** `POSTGRES_USER/PASSWORD/DB` do `/workspace/.env` devem ser iguais
  aos usados pelo container `postgres` (`.devcontainer/.env`); divergência gera falha de
  autenticação (não de rede) só no primeiro job que tocar o banco — não bloqueia a subida da UI.
