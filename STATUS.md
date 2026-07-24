# STATUS

> **Ponto de partida obrigatório.** Antes de qualquer tarefa, leia este arquivo: ele diz o estado
> atual do projeto, o que acabou de ser feito e qual é a próxima prioridade. A partir daqui, siga
> o princípio da **injeção de contexto sob demanda** — carregue apenas os arquivos que a tarefa
> atual exige (`PRD.md`, `docs/domain/`, `docs/standards/`, o plano relevante em
> `.claude/plans/`), em vez de tentar ler tudo de uma vez.

## Estado atual

Fase de planejamento concluída para o MVP: produto, regras de negócio, arquitetura técnica e o
time de subagentes estão totalmente especificados. Nenhum código de aplicação foi escrito ainda —
`src/` e `test/` contêm apenas os READMEs-marcador originais do template.

## Feito recentemente

- Executado o plano `.claude/plans/2026-07-24-ops-rede-docker-interna.md` (rede Docker interna):
  criada rede compartilhada `busca-voos-net` (`external: true`) declarada tanto em
  `.devcontainer/docker-compose.yml` (serviço `postgres`, também ligado a `default` para preservar
  acesso do `app` de dev) quanto em `/workspace/docker-compose.yml` (serviço `app`, raiz). Removida
  a publicação de `127.0.0.1:5432` do `postgres` ao host — acesso agora só pela rede interna
  (inspeção via `docker compose exec postgres psql`), por decisão do usuário ("rede interna,
  expondo apenas as portas necessárias"). Comentário-bloqueio no topo de `docker-compose.yml` da
  raiz substituído por uma nota curta descrevendo a solução. **Pendente** (requer host com Docker):
  `docker network create busca-voos-net` antes do primeiro `up`, e a validação ponta a ponta
  (Passo 5 do plano — `postgres` healthy, `app` resolvendo o hostname `postgres` pela rede).
- Criada a estrutura de pastas de `src/` (`domain/`, `extraction/`, `persistence/`,
  `notification/`, `orchestration/`, `utils/`, cada uma com `__init__.py`), conforme
  `docs/standards/architecture.md` §2 — só o esqueleto de módulos, nenhuma regra de negócio
  implementada ainda.
- Executado (via `infra-runner`) o plano `.claude/plans/2026-07-23-ops-docker-compose-app.md`
  (Passos 5-8, completando o que ficara adiado): criado `/workspace/Dockerfile` (imagem
  `mcr.microsoft.com/playwright/python:v1.55.0-noble`, `uv sync`, `CMD dagster dev`); criado
  `/workspace/docker-compose.yml` (raiz, só o serviço `app` — **sem** duplicar `postgres`, que já
  existe em `.devcontainer/docker-compose.yml`; comentário no arquivo documenta que `app` e
  `postgres` estão em redes docker-compose separadas por padrão e que ligá-los exige configuração
  manual no host, ver arquivo); criado `/workspace/.dockerignore` e `/workspace/pyproject.toml`
  (dependencies dagster/playwright/sqlalchemy/psycopg/alembic/python-telegram-bot); `uv lock`
  rodado com sucesso, gerou `/workspace/uv.lock`. Criado também `/workspace/.env.example` e
  adicionado `/.env` ao `.gitignore` da raiz (pré-requisitos do `docker-compose.yml` novo).
  **Não verificado**: Docker indisponível neste devcontainer — não foi possível rodar `docker
  compose build`/`up` para confirmar o build da imagem `app` nem a conectividade real com o
  `postgres`. D3 (tag da imagem Playwright) ficou fixada em `v1.55.0-noble`; a resolução de rede
  `app`↔`postgres` continua em aberto (ver comentário no topo de `docker-compose.yml`).
- Executado (via `infra-runner`) o plano `.claude/plans/2026-07-23-ops-docker-compose-app.md`
  (Passos 1-4, adaptados ao alvo revisado por D1): criado `scripts/init-db.sql` (schemas
  `bronze`/`silver`/`gold`); adicionado serviço-irmão `postgres` (imagem `postgres:16-bookworm`,
  healthcheck `pg_isready`, porta em `127.0.0.1:${POSTGRES_PORT}`, volume `pgdata`) em
  `.devcontainer/docker-compose.yml`; populadas `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB`/
  `POSTGRES_PORT` em `.devcontainer/.env` (não versionado). **Não verificado**: Docker é
  indisponível dentro deste devcontainer — falta rodar `docker compose up -d postgres` num host com
  Docker e confirmar `postgres` healthy + schemas via `\dn`.
- `PRD.md` fechado: escopo do MVP (só Gol, só ida, rota fixa Macapá/MCP → Brasília/BSB,
  01/09/2026), stack (Python, Playwright + stealth, Dagster, **PostgreSQL** via docker-compose,
  Telegram), critérios de aceite e arquitetura de pastas.
- `docs/domain/regras_negocio.md` preenchido: glossário e as 5 regras de negócio (execução,
  elegibilidade, deduplicação, notificação, persistência) com casos de borda e validações.
- `docs/standards/architecture.md` preenchido: pipeline Medallion em schemas Postgres
  (bronze/silver/gold), estrutura de `src/` (`domain/extraction/persistence/notification/
  orchestration/utils`), ferramental (`uv`, `ruff`, `alembic`), containerização e testes.
- `CLAUDE.md` criado na raiz: fluxo de trabalho obrigatório, roteamento de contexto, convenções de
  código (inglês no código, português na documentação, Conventional Commits, trunk-based).
- Os 5 agentes em `.claude/agents/` (`dev-planner`, `dev-runner`, `infra-planner`, `infra-runner`, `qa`)
  reescritos com papel/tom de voz, objetivo, modelo, effort e escopo pode/não-pode explícitos.
- `docs/guidelines/` e `docs/standards/style.md` removidos (conteúdo consolidado em `CLAUDE.md` e
  `architecture.md`); skills de apoio (`context7`, `postgres`, `docker-patterns`, etc.) instaladas.

## Próxima prioridade

- **Validar a infra de rede/postgres** num host com Docker disponível (fora deste devcontainer,
  ver [[project_docker_not_in_devcontainer]]): rodar `docker network create busca-voos-net` (uma
  vez), depois `docker compose -f .devcontainer/docker-compose.yml up -d postgres` e confirmar
  `healthy` + schemas `bronze`/`silver`/`gold` via `\dn`; em seguida `docker compose -f
  docker-compose.yml up -d app` e confirmar que `app` resolve o hostname `postgres` pela rede
  `busca-voos-net` (Passo 5 de `.claude/plans/2026-07-24-ops-rede-docker-interna.md`). Ação manual
  do usuário.
- Com o banco confirmado: iniciar a trilha `dev-planner` → `dev-runner` → `qa` para o módulo
  `src/domain/` (regras de elegibilidade e deduplicação), que não depende de infraestrutura externa
  e pode ser desenvolvido em TDD isoladamente.
- Em paralelo: criar o bot no Telegram via @BotFather e obter `token`/`chat_id` (tarefa manual do
  usuário) para popular o `.env` da raiz.
- Quando `src/orchestration` e `workspace.yaml` existirem (trilha `dev-planner`/`dev-runner`),
  validar `docker compose build app` / `docker compose up app` num host com Docker.

## Contexto necessário para a próxima tarefa

- `PRD.md` — o quê/porquê, escopo do MVP, seção 9 (arquitetura de pastas)
- `docs/standards/architecture.md` — §3 (schemas Postgres), §4 (ferramental), §7 (containerização)
  para o bootstrap de infra
- `docs/domain/regras_negocio.md` — regras de elegibilidade/deduplicação para o módulo `domain/`
- `.claude/agents/infra-planner.md` / `infra-runner.md` — papel e restrições de cada agente na trilha de infra
