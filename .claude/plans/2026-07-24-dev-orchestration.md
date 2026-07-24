# Plano dev — módulo `src/orchestration/` (job diário Dagster que cola todas as camadas)

> Especificação (contrato + testes que falham) para o `dev-runner`. **Último módulo de código do
> MVP.** Fontes de verdade: `docs/standards/architecture.md` §1 (pipeline completo), §6 (toda falha
> capturada, logada via `context.log`, propagada p/ notificação de erro — nunca crash silencioso);
> `docs/domain/regras_negocio.md` — Regras de Execução / Elegibilidade / Deduplicação / Notificação /
> Persistência / Validações. Escopo (`architecture.md` §2): `src/orchestration/assets.py`
> (assets/jobs Dagster). `orchestration` **consome** as APIs já implementadas de `extraction`,
> `persistence`, `notification`, `domain` — não redesenha nenhuma delas.

## Objetivo

Encadear, num run diário: `extraction` (captura Gol) → `bronze` (raw) → mapear/validar →
`silver` (voos normalizados) → `domain` (elegibilidade + deduplicação com histórico de `gold`) →
`gold` + `notification` (alerta de voos) — e, se a execução falhar em qualquer ponto, disparar a
**notificação de erro** independente. O `dev-planner` entrega o contrato (assinaturas, dataclass de
saída, protocolos de dependência) e a suíte que hoje falha por `NotImplementedError` (unitários da
lógica pura com fakes) ou pula automaticamente (integração do job Dagster real). O `dev-runner`
implementa os corpos **sem alterar assinaturas nem testes**.

## Decisão-chave: lógica de decisão PURA × casca fina do Dagster

O run real toca Playwright + Postgres + Telegram — nada disso roda em unit test. Então a **lógica de
orquestração** (o que persistir em cada camada, quais voos notificar, como tratar cada falha) é
extraída numa função pura, `run_daily_search`, com **todas** as dependências injetadas como
protocolos/callables. O `@asset`/job/schedule do Dagster é uma **casca fina** que só: (1) constrói os
colaboradores reais (captura async, repositórios ligados a uma conexão, notifier Telegram,
`context.log`) e (2) delega a decisão para `run_daily_search`, depois faz commit/rollback da
transação e sinaliza falha ao UI do Dagster conforme o `RunOutcome` retornado.

Assim os 6 casos de borda são 100% unit-testáveis com fakes; o job real é coberto só por teste de
integração pulável (mesma convenção de skip de `persistence`/`extraction`/`notification`).

## Decisão-chave: granularidade = 1 asset (casca) sobre 1 função pura

Optei por **um único asset Dagster** (`daily_flight_search`), casca fina sobre `run_daily_search`, em
vez de um asset por camada bronze/silver/gold. Razão de testabilidade e de invariante: a regra "toda
falha → exatamente **uma** notificação de erro, nunca crash não-observável" (`architecture.md` §6;
Regra de Notificação — 0/1 alerta + 0/1 erro mutuamente exclusivos) precisa viver num **único ponto
testável**. Espalhar o try/except por vários assets (com passagem de dependência no grafo) fragmenta
essa invariante e dificulta garantir "0 ou 1 erro por run". Um asset fino sobre uma função pura total
concentra a decisão onde ela é testável.

## Estrutura entregue

```
src/orchestration/
├── __init__.py    # reexport da superfície pública (defs + lógica pura), padrão das outras camadas
└── assets.py      # constantes + protocolos + RunStatus/RunOutcome
                   #   + captured_to_flight / to_valid_flights / build_alert (PUROS)
                   #   + run_daily_search (PURO, o coração)
                   #   + TelegramNotifier / capture_sync / daily_flight_search @asset (casca I/O)
                   #   + daily_flight_search_job / _schedule / defs (wiring Dagster)
test/orchestration/
├── __init__.py
├── conftest.py                 # fakes in-memory (Bronze/Silver/Gold/Notifier/Logger) + builders
├── test_mapping.py             # unit puro do mapeamento CapturedFlight→Flight + validações (7)
├── test_run_daily_search.py    # unit puro dos 6 casos de borda + bônus (12)
├── test_definitions.py         # estrutural da casca Dagster (schedule diário/job/asset) (4, passam)
└── test_job_integration.py     # execução do job real — pulável (opt-in RUN_ORCHESTRATION_INTEGRATION=1)
```

Fiel a `architecture.md` §2 (o módulo lista exatamente `assets.py`). Único arquivo extra é o
`__init__.py` de reexport (mesmo padrão de `extraction`/`notification`).

## Contrato a implementar (dev-runner)

### Constantes (`assets.py`)
- `MONITORED_ROUTE = Route(...)` derivada de `extraction.gol.MVP_SEARCH_PARAMS` — **fonte única** da
  rota/data monitorada (`architecture.md` §5, nunca re-hardcodar MCP/BSB/2026-09-01).
- `CARRIER_NAMES = {"G3": "GOL"}` — tradução código→nome de cia (cosmético, não é regra de negócio;
  código desconhecido cai no próprio código como fallback).
- `DAILY_CRON = "0 9 * * *"` — hora arbitrária (Regra de Execução: 1x/dia, sem horário fixo). Schedule
  não-particionado ⇒ **sem catch-up/backfill** (Regra de Execução — sem compensação).

### Protocolos injetáveis (structural typing; os objetos reais já os satisfazem)
- `CaptureFn` — `() -> GolCaptureResult` **síncrono** (a casca adapta o `capture_gol_search` async via
  `asyncio.run`; qualquer falha vem como subclasse de `ExtractionError`).
- `BronzeWriter` / `SilverWriter` / `GoldStore` — espelham `BronzeRepository`/`SilverRepository`/
  `GoldRepository` (os repos reais satisfazem estruturalmente).
- `Notifier` — `.send(text) -> None`; a decisão compõe a mensagem com as `format_*` puras da
  `notification` e entrega o texto pronto; falha de entrega levanta `NotificationError`.
- `PipelineLogger` — subconjunto de `context.log` (`info`/`warning`/`error`); o logger do Dagster o
  satisfaz (`architecture.md` §6 — sem lib de logging extra).

### Saída
- `RunStatus` (enum): `SUCCESS_ALERTED`, `SUCCESS_NO_ALERT`, `FAILED_EXTRACTION`,
  `FAILED_PERSISTENCE`, `FAILED_NOTIFICATION`; `.is_failure` cobre os três `FAILED_*`.
- `RunOutcome` (frozen dataclass): `status`, `execution_id`, `eligible_count`, `notified_count`,
  `should_commit` (sinal p/ a casca commitar × rollback), `error`, `message`. É o **contrato** entre
  `run_daily_search` e a casca.

### Helpers puros de mapeamento (hoje `NotImplementedError`)
1. `captured_to_flight(captured, route) -> Flight`
   - `flight_number` = designador completo `"{carrier}-{number}"` (`"G3"`+`"1234"` → `"G3-1234"`, a
     "Identificador do voo" da dedup); `carrier` traduzido via `CARRIER_NAMES`; `price` fica `Decimal`.
   - Valida com `domain.models.validate_flight` (preço não-positivo/campo faltante →
     `InvalidFlightError`, **single-sourced** em `domain`).
2. `to_valid_flights(captured_seq, monitored_route, logger) -> list[Flight]`
   - Reconstrói a rota de cada capturado; se **≠ monitored_route** (outra rota/data) → **descarta**
     (log warning) — Validação "rota deve corresponder à monitorada".
   - Senão mapeia via `captured_to_flight`; se `InvalidFlightError` (ex.: preço 0/negativo — "falha de
     extração daquele voo, não voo elegível") → **descarta** (log warning). Um voo ruim **não** derruba
     o run. Ordem preservada. Nunca propaga exceção por 1 registro ruim.
3. `build_alert(flight, alerted_at) -> Alert` — `flight_id`/`price`/`currency` do voo, `alerted_at` =
   timestamp do run (o "último preço alertado" que a próxima dedup lê).

### Lógica de decisão pura — `run_daily_search(*, route, search_date, capture, bronze, silver, gold, notify, logger, execution_id, now) -> RunOutcome` (hoje `NotImplementedError`)
Função **total** (nunca levanta para modo de falha tratado; nunca crash — `architecture.md` §6).
Fluxo e casos de borda 1:1 com `regras_negocio.md`:

1. **Extração.** `capture()`.
   - Levanta `ExtractionError` (qualquer subclasse) → **(d)**: grava marcador de falha no bronze
     (`save_raw_response(success=False, payload=None, error_message=str(exc))` — sem silver/gold, sem
     dado de voo inválido), compõe erro com `format_failure_message(exc, search_date, route)` e
     `notify.send`; loga. Retorna `FAILED_EXTRACTION` (`should_commit=True` — o marcador é metadado
     válido do run).
   - Se o `notify.send` do erro **também** levantar `NotificationError` → **(f)**: `logger.error` e
     **não** re-levanta. Run segue `FAILED_EXTRACTION`.
2. **Bronze (sucesso).** `save_raw_response(success=True, payload=result.raw_payload, ...)`. Se este —
   ou qualquer write posterior — levantar → **(e)**: loga, tenta notificação de erro (engolindo um
   `NotificationError` aninhado com log), retorna `FAILED_PERSISTENCE` com `should_commit=False` (a
   casca faz rollback → sem dado parcial; "bronze persistido ⇔ run bem-sucedido" só vale se a
   transação inteira commitar).
3. **Silver + domínio.** `to_valid_flights` (descarta inválidos/outra-rota, não-fatal) →
   `silver.save_flights` → `select_eligible` (MVP: identidade).
4. **Deduplicação.** `gold.last_alerted_prices(route)` → `select_flights_to_notify`.
   - Vazio → **(a)** (0 elegíveis / captura vazia) ou **(b)** (todos deduplicados, preço igual):
     **nada** é enviado, gold intocado. Retorna `SUCCESS_NO_ALERT`.
5. **Alerta.** Não-vazio → **(c)**: compõe **uma** mensagem com `format_flight_alert_message` e
   `notify.send` **primeiro**; só em sucesso faz `gold.record_alerts` (gold guarda só preços
   **efetivamente enviados** — definição de "último preço alertado"). Retorna `SUCCESS_ALERTED`.
   - Se o `notify.send` do alerta levantar `NotificationError` → **não** grava gold (próximo run
     retenta), loga, retorna `FAILED_NOTIFICATION` (`should_commit=True` — bronze/silver são dados
     capturados válidos que valem a retenção; só o gold foi retido).

### Casca fina Dagster (I/O; só integração) — hoje `NotImplementedError`
- `TelegramNotifier` (adapter): `.send` delega a `notification.send_telegram_message(text, config)`.
- `capture_sync()`: adapta `capture_gol_search(MVP_SEARCH_PARAMS)` async → `CaptureFn` via `asyncio.run`.
- `daily_flight_search` `@asset(context)`: gera `execution_id`(uuid4)/`now`; abre escopo transacional
  em `get_engine`; monta repos + `TelegramNotifier.from_env` + `context.log`; chama `run_daily_search`
  com `capture_sync`; **commit se `outcome.should_commit` senão rollback**; se `outcome.is_failure`
  levanta `dagster.Failure` (surfaça no UI) **após** a notificação já ter sido tentada pela função pura.
- `daily_flight_search_job` (`define_asset_job`), `daily_flight_search_schedule`
  (`ScheduleDefinition`, `DAILY_CRON`, sem catch-up), `defs` (`Definitions`) — wiring construído em
  import (não executa corpos), entrypoint único do pipeline (sem HTTP/frontend — `architecture.md` §1).

## Decisões de design / casos de borda resolvidos

- **Marcador de falha no bronze (d).** Falha de extração **grava** uma linha bronze `success=False`
  (a coluna existe justamente p/ isso — ver `BronzeRepository.save_raw_response`/`tables.py`). Isso é
  metadado válido do run (histórico da falha), **não** "dado inválido"; silver/gold não recebem nada.
- **Atomicidade da persistência (e).** bronze+silver+gold numa **única transação** dona da casca. Se
  qualquer write falha, a função pura sinaliza `should_commit=False` e a casca faz rollback → o run
  não deixa dado parcial. `run_daily_search` **não** re-levanta o erro de persistência (para não
  crashar a casca) — ela o traduz em notificação + `RunOutcome`.
- **Ordem alerta→gold (c).** Envia o alerta **antes** de gravar gold, porque "último preço alertado =
  efetivamente enviado". Se o envio do alerta falha, gold não é tocado (retry no próximo run) →
  `FAILED_NOTIFICATION`, mas bronze/silver ficam (dados capturados válidos).
- **Função total, casca decide o UI.** A função pura nunca crasha; retorna `RunOutcome`. A casca é
  quem levanta `Failure` para marcar o run como falho no Dagster — depois de a notificação já ter sido
  disparada. Edge (f) (Telegram do erro também cai) é engolido+logado dentro da pura → nunca vira
  crash não-observável.
- **Validações single-sourced.** Preço positivo / campos obrigatórios ficam em
  `domain.validate_flight` (não reimplementados aqui). A checagem "rota == monitorada" é um **filtro**
  de orquestração (precisa da rota monitorada como contexto) e vive em `to_valid_flights`, referenciando
  a Validação correspondente — não é regra de negócio reexplicada.
- **Rota/data = fonte única.** `MONITORED_ROUTE` deriva de `MVP_SEARCH_PARAMS` (`architecture.md` §5).
- **Sem catch-up.** Schedule não-particionado não faz backfill (Regra de Execução — sem compensação).

## Testes — `test/orchestration/`

Config herdada de `pyproject.toml` (`pythonpath=["src"]`, `testpaths=["test"]`). `conftest.py` traz
fakes in-memory que espelham os protocolos (`FakeBronze`/`FakeSilver`/`FakeGold`/`FakeNotifier`/
`FakeLogger`, cada um configurável para levantar) + builders (`make_captured`/`make_flight`/
`make_capture_result`/`capture_returning`/`capture_raising`).

### Unit — mapeamento (`test_mapping.py`, 7) — falham por `NotImplementedError`
- designador `G3-1234` + tradução `G3→GOL` + `flight_id` estável; fallback de cia desconhecida;
  preço 0 → `InvalidFlightError`; descarta preço inválido mantendo válidos (+warning); descarta voo de
  outra rota (+warning); ordem preservada; entrada vazia / data diferente → lista vazia.

### Unit — decisão (`test_run_daily_search.py`, 12) — falham por `NotImplementedError`
- **(a)** captura vazia → bronze `success=True`, nada enviado, gold intocado, `SUCCESS_NO_ALERT`.
- **(b)** todos deduplicados (preço igual) → nada enviado, gold intocado, silver ainda gravado (retenção).
- **(c)** voo novo → 1 alerta + gold gravado com o preço; e voo com preço alterado → 1 alerta.
- **(d)** `parametrize` sobre `BlockedError`/`ExtractionTimeoutError`/`MalformedPayloadError` → 1
  notificação de erro, silver/gold vazios, bronze marcador `success=False`, logado, `FAILED_EXTRACTION`.
- **(e)** silver levanta / bronze levanta → 1 notificação de erro, `should_commit=False`,
  `FAILED_PERSISTENCE`, sem exceção escapando.
- **(f)** extração falha **e** o `send` do erro falha → função **retorna** (sem exceção), envio
  tentado, `logger.error` presente.
- **bônus:** falha ao enviar o **alerta** → `FAILED_NOTIFICATION`, gold **não** gravado, logado.
- **guarda:** `SUCCESS_NO_ALERT` nunca grava gold.

### Estrutural — casca (`test_definitions.py`, 4) — **passam** (wiring construído em import)
- `defs` é `Definitions`; cron diário (5 campos, dia/mês/semana curinga → 1 tick/dia, sem backfill);
  schedule aponta o job; job resolve o asset de orquestração. Assertions tolerantes a versão do Dagster.

### Integração — job real (`test_job_integration.py`, 1) — **pulável**
- `skipif RUN_ORCHESTRATION_INTEGRATION != "1"` (executa Playwright+Postgres+Telegram). Ainda pula em
  `NotImplementedError` e em ambiente indisponível. `execute_in_process(raise_on_error=False)`.

Estado da suíte de orchestration (`uv run pytest test/orchestration/`): **19 failed, 4 passed, 1
skipped** — as 19 falhas são todas `NotImplementedError` (motivo certo). Suíte total do repo: **19
failed, 96 passed, 20 skipped** (todas as 19 falhas são deste módulo; nenhuma regressão nas demais).
`ruff check`/`format --check` limpos em `src/orchestration/` e `test/orchestration/`.

## Ambiguidades / pendências para o dev-runner (IMPORTANTE)

1. **Modelo de transação na casca.** O contrato exige bronze+silver+gold numa transação e
   commit/rollback conforme `outcome.should_commit`. O `connection_scope` fornecido auto-commita na
   saída limpa e rollback em exceção — como a função pura **não** re-levanta, a casca precisa de
   controle **manual** (`conn = engine.connect(); tx = conn.begin(); ...; tx.commit()/rollback()`),
   **não** o `connection_scope` puro. Decidir isso é do `dev-runner` (afeta só a casca, não a lógica pura).
2. **Marcador de falha do bronze fora da transação principal (d).** Na falha de extração, o marcador
   `success=False` deve ser **commitado** (é o registro da falha) mesmo sem silver/gold. Se o
   `dev-runner` usar transação única, basta commitar quando `should_commit=True`. Alternativa: uma
   transação curta só para o marcador. Contrato: o marcador precisa **sobreviver**; o mecanismo é livre.
3. **`asyncio.run` em `capture_sync`.** Se o job rodar dentro de um event loop (Dagster costuma rodar
   em thread sync — ok), `asyncio.run` funciona; se algum dia rodar em contexto async, trocar por
   `anyio`/loop dedicado. MVP: `asyncio.run` basta.
4. **Layout das mensagens é da `notification`.** `run_daily_search` só decide **quando/qual** função
   `format_*` chamar e entrega o texto ao `Notifier`; conteúdo/diagramação já é contrato de
   `notification` (ver `2026-07-24-dev-notification.md`). Os testes de orchestration afirmam
   contagem de envios / alertas gravados, **não** o texto (desacopla da formatação).
5. **`CARRIER_NAMES`.** MVP só Gol (`G3→GOL`). Fallback = próprio código. Estender quando houver mais
   cia (não é regra de negócio — é rótulo de exibição).
6. **`workspace.yaml`/code location.** Para `dagster dev` carregar `defs`, o repo precisará apontar o
   code location para `orchestration` (ou `orchestration.assets:defs`). Isso é wiring de projeto/infra
   (Dockerfile já roda `dagster dev`) — fora do escopo deste módulo de código, sinalizar ao
   `infra-runner`/humano.

## Fora de escopo (não fazer aqui)

- Implementar/alterar `extraction`/`persistence`/`notification`/`domain` — já entregues; só consumir.
- Criar `workspace.yaml` / configurar code location / validar `dagster dev` num host — trilha de infra.
- Rodar o job real ponta a ponta (browser+Postgres+Telegram) — passo manual do operador com
  credenciais (`RUN_ORCHESTRATION_INTEGRATION=1`).
- Migrations Alembic das tabelas (bronze/silver/gold) — escopo de `persistence`/infra.
