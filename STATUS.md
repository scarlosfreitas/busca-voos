# STATUS

> **Ponto de partida obrigatório.** Antes de qualquer tarefa, leia este arquivo: ele diz o estado
> atual do projeto, o que acabou de ser feito e qual é a próxima prioridade. A partir daqui, siga
> o princípio da **injeção de contexto sob demanda** — carregue apenas os arquivos que a tarefa
> atual exige (`PRD.md`, `docs/domain/`, `docs/standards/`, o plano relevante em
> `.claude/plans/`), em vez de tentar ler tudo de uma vez.

## Estado atual

**Todo o código de aplicação do MVP está implementado e testado.** As 5 camadas de
`docs/standards/architecture.md` §2 existem, cada uma fechando a trilha completa
`dev-planner → dev-runner → qa`:

- `src/domain/` — modelos (`Flight`/`Route`/`Alert`), elegibilidade, deduplicação.
- `src/persistence/` — engine/conexão Postgres, repositórios bronze/silver/gold, migration Alembic.
- `src/extraction/` — Playwright + stealth, parser puro do payload da Gol, hierarquia de erros.
- `src/notification/` — composição e envio de mensagens via Telegram.
- `src/orchestration/` — `run_daily_search` (função pura e total) + asset/job/schedule Dagster
  diário, colando as 4 camadas acima.

Suíte completa: **137 passed, 3 skipped** (skips são recursos opcionais puláveis por design —
Playwright real, Telegram real, job Dagster real — quando não configurados/disponíveis). `ruff
check`/`ruff format --check` limpos em todo `src/`, exceto 5 issues de lint + 2 arquivos de
formatação pré-existentes em `test/domain/` (não tocados, fora do escopo de qualquer tarefa até
agora — ver "Próxima prioridade").

`workspace.yaml` (code location do Dagster) criado e validado localmente (`dagster definitions
validate` → sucesso). **O que falta para o MVP estar 100% homologado (`PRD.md` §8) é infraestrutura
que só um host com Docker + rede real + credenciais reais pode validar** — ver próxima prioridade.

## Feito recentemente (topo)

- Criado `/workspace/workspace.yaml`, apontando para `src/orchestration/assets.py:defs`
  (`working_directory: src` para colocar `src/` no `sys.path`, já que `pyproject.toml` tem
  `[tool.uv] package = false`). Validado localmente com `uv run dagster definitions validate -w
  workspace.yaml` → sucesso. Plano `.claude/plans/2026-07-24-ops-workspace-yaml-validacao-stack.md`
  (Passos 1-2 executados no devcontainer; Passos 3-7 — rede/build/up Docker real — pendentes,
  exigem host com Docker, ver `LESSONS_LEARNED.md`).
- Executada a trilha completa `dev-planner → dev-runner → qa` para `src/orchestration/` (plano
  `.claude/plans/2026-07-24-dev-orchestration.md`, **último módulo de código do MVP**): asset Dagster
  fino sobre a função pura total `run_daily_search`, controle manual de transação
  (bronze/silver/gold atômicos; marcador de falha de extração sobrevive). O QA encontrou um bug real
  de totalidade (`gold.last_alerted_prices`/`gold.record_alerts` escapavam do tratamento de exceção)
  — corrigido pelo `dev-runner` num segundo ciclo, com novo `RunStatus.FAILED_GOLD_RECORD` para
  falha de persistência pós-notificação sem duplicar alerta. Suíte final: **137 passed, 3 skipped**.
  Commitado (`c8fed09`, `979058e` era o commit anterior de notification).
- Executada a trilha completa para `src/notification/` (plano
  `.claude/plans/2026-07-24-dev-notification.md`): `telegram.py` — composição pura de mensagens
  (`format_price`/`format_flight_alert_message`/`format_failure_message`) + envio via `httpx`
  síncrono (`send_telegram_message`, `NotificationError` tipada). QA adicionou 10 testes de
  cobertura extra (preço 0/negativo, HTTP 200+`ok:false`, caracteres especiais). Commitado (`979058e`).
- Executada a trilha completa para `src/extraction/` (plano `.claude/plans/2026-07-24-dev-extraction.md`):
  `browser.py` (stealth via `playwright-stealth`, timeout 5min) + `gol.py` (`parse_gol_response`
  puro/testável com fixtures sintéticas + `capture_gol_search` I/O). **Pendência conhecida**: o
  shape do payload JSON da Gol é sintético — nunca capturado do site real (sem rede externa/browser
  gráfico neste devcontainer). Precisa de validação manual futura com Playwright instalado
  (`playwright install`) e rede real, ajustando `GOL_TRIPS_KEY`/`GOL_SEARCH_URL`/
  `GOL_AVAILABILITY_URL_FRAGMENT` se o shape real divergir. Commitado (`51a9d89`).
- Executada a trilha completa para `src/persistence/` (plano `.claude/plans/2026-07-24-dev-persistence.md`):
  `db.py`/`repositories.py`/`tables.py` + migration Alembic inicial das tabelas
  bronze/silver/gold. QA validou contra Postgres real (rede `busca-voos-net`) e escreveu 6 testes de
  integração adicionais (append-only, isolamento por rota, `last_alerted_prices` via `MAX(alerted_at)`).
  Commitado (`bcd613f`).
- Commitada a implementação de `src/domain/` (models/eligibility/deduplication), já pronta de sessão
  anterior — `bcaecee`.
- `.devcontainer/Dockerfile`/`postCreate.sh`: adicionado `zip`/`unzip` e instalação de ferramenta de
  monitoramento de consumo de tokens (`bun` + `claude-usage`) — `320846c`.

## Próxima prioridade

1. **Validação manual em host com Docker** (Passos 3-7 de
   `.claude/plans/2026-07-24-ops-workspace-yaml-validacao-stack.md`): `docker network create
   busca-voos-net` (se ainda não existir), subir `postgres`, `docker compose build app` / `up -d
   app`, confirmar UI do Dagster em `127.0.0.1:3000`, log sem erro de import do code location, e
   `app` resolvendo `postgres` pela rede. Ver `LESSONS_LEARNED.md` — Docker não existe neste
   devcontainer, é um passo estruturalmente manual do usuário.
2. **Criar o bot no Telegram via @BotFather** (tarefa manual do usuário) e popular
   `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` no `.env` da raiz — pré-requisito para o critério de
   aceite "Entrega da Mensagem" do `PRD.md` §8.
3. **Validar a captura real contra o site da Gol** (com Playwright instalado e rede real, fora deste
   devcontainer): confirmar/ajustar o shape do payload em `src/extraction/gol.py`
   (`GOL_TRIPS_KEY`/`GOL_SEARCH_URL`/`GOL_AVAILABILITY_URL_FRAGMENT` são placeholders sintéticos
   hoje) — é o único ponto do MVP nunca validado contra o mundo real. Só depois disso os critérios
   de aceite "Acesso e Evasão", "Execução da Rota Alvo" e "Captura via Interceptação" do `PRD.md` §8
   podem ser considerados homologados.
4. Depois de 1-3: rodar o job real (`RUN_ORCHESTRATION_INTEGRATION=1` ou via UI do Dagster) uma vez
   de ponta a ponta com dados reais, para fechar a homologação completa do MVP.
5. Limpeza menor, não bloqueante: 5 issues de lint + 2 arquivos de formatação pendentes em
   `test/domain/` (pré-existentes, nunca tocados por nenhuma trilha até agora — `qa`/`dev-runner`
   não podem editar testes fora do próprio escopo da tarefa corrente). Rodar `ruff check`/`ruff
   format` em `test/domain/` isoladamente quando for conveniente.

## Contexto necessário para a próxima tarefa

- `PRD.md` §8 — critérios de aceite do MVP, para saber o que ainda falta homologar.
- `.claude/plans/2026-07-24-ops-workspace-yaml-validacao-stack.md` — passos exatos de validação Docker.
- `.claude/plans/2026-07-24-dev-extraction.md` — pendência do shape real do payload da Gol.
- `docs/standards/architecture.md` §7 (containerização) e §6 (tratamento de erros/timeouts).
- `LESSONS_LEARNED.md` — limitações de ambiente conhecidas (Docker indisponível no devcontainer).
