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
- Os 5 agentes em `.claude/agents/` (`plan-dev`, `run-dev`, `plan-ops`, `run-ops`, `test-ops`)
  reescritos com papel/tom de voz, objetivo, modelo, effort e escopo pode/não-pode explícitos.
- `docs/guidelines/` e `docs/standards/style.md` removidos (conteúdo consolidado em `CLAUDE.md` e
  `architecture.md`); skills de apoio (`context7`, `postgres`, `docker-patterns`, etc.) instaladas.

## Próxima prioridade

- **Bootstrap de infraestrutura** (trilha `plan-ops` → `run-ops`): criar o `docker-compose.yml` da
  aplicação com os serviços `app` (imagem `mcr.microsoft.com/playwright/python`) e `postgres`,
  conforme `docs/standards/architecture.md` §7 — hoje só existe o compose do devcontainer (ambiente
  do Claude Code), não o da aplicação em si.
- Em paralelo/sequência: criar o bot no Telegram via @BotFather e obter `token`/`chat_id` (tarefa
  manual do usuário, não de agente) para popular o `.env` da aplicação.
- Depois da infra de banco disponível: iniciar a trilha `plan-dev` → `run-dev` → `test-ops` para o
  módulo `src/domain/` (regras de elegibilidade e deduplicação), que não depende de infraestrutura
  externa e pode ser desenvolvido em TDD isoladamente.

## Contexto necessário para a próxima tarefa

- `PRD.md` — o quê/porquê, escopo do MVP, seção 9 (arquitetura de pastas)
- `docs/standards/architecture.md` — §3 (schemas Postgres), §4 (ferramental), §7 (containerização)
  para o bootstrap de infra
- `docs/domain/regras_negocio.md` — regras de elegibilidade/deduplicação para o módulo `domain/`
- `.claude/agents/plan-ops.md` / `run-ops.md` — papel e restrições de cada agente na trilha de infra
