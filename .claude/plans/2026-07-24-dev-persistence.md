# Plano dev — módulo `src/persistence/` (db, tables, repositories, migrations)

> Especificação (contrato + testes que falham) para o `dev-runner`. Fonte de verdade das regras:
> `docs/domain/regras_negocio.md`. Padrões técnicos: `docs/standards/architecture.md` §3 (Medallion
> no Postgres), §4 (uv/ruff/alembic), §5 (segredos via env), §7 (containerização), §8 (testes).
> Escopo: camada de acesso a dados (bronze/silver/gold). Depende de `domain/` (para dentro); NUNCA o
> contrário.

## Objetivo

Persistir e ler as três camadas Medallion no Postgres: gravar payload bruto em `bronze`, voos
normalizados em `silver`, e o histórico de "último preço alertado" em `gold` — produzindo o
`Mapping[str, Decimal]` que `domain.deduplication.select_flights_to_notify` consome. O `dev-planner`
entrega o contrato (assinaturas, docstrings, schema das tabelas + migration Alembic) e a suíte que
hoje falha por `NotImplementedError` (unitários) ou é pulada automaticamente (integração sem
Postgres). O `dev-runner` implementa os corpos sem alterar assinaturas nem os testes.

## Estrutura entregue

```
src/persistence/
├── db.py            # URL de conexão via env + Engine singleton + connection_scope (contrato)
├── tables.py        # SQLAlchemy Core MetaData + Table (schema puro — JÁ ESCRITO, é o contrato de dados)
└── repositories.py  # BronzeRepository / SilverRepository / GoldRepository + mappers puros (contrato)
alembic.ini
migrations/
├── env.py           # target_metadata = persistence.tables.metadata; url via build_database_url()
├── script.py.mako
└── versions/20260724_0001_initial_medallion_tables.py   # DDL das 3 tabelas (JÁ ESCRITO)
```

Nota de estrutura: `architecture.md` §2 lista `db.py` + `repositories.py` como módulos "propostos".
Adicionei `tables.py` para isolar a definição de schema (dado, não regra de negócio) — mantém `db.py`
focado em conexão e `repositories.py` focado em I/O. Decisão documentada aqui para o `dev-runner` não
tratar como divergência.

## Modelo de dados (`src/persistence/tables.py`) — schema já escrito (não reimplementar)

Convenções `architecture.md` §3: `snake_case` singular; `execution_id` (UUID) + `captured_at`
(timestamptz UTC) em bronze/silver; append-only; sem purge. `id` BIGINT autoincrement como PK técnica.

- `bronze.raw_search_response` — payload cru interceptado + metadados de execução:
  `execution_id`, `route_origin`, `route_destination`, `departure_date`, `captured_at`, `success`
  (bool), `payload` (JSONB, **nullable** em falha), `error_message` (text, nullable). Índice em
  `execution_id`.
- `silver.flight` — voos normalizados: `execution_id`, `captured_at`, rota (`route_origin`/
  `route_destination`/`departure_date`), `carrier`, `flight_number`, `departure_time` (time),
  `price` `NUMERIC(12,2)`, `currency`, `flight_id` (chave de dedup denormalizada). Índices em
  `execution_id` e `flight_id`.
- `gold.flight_alert` — histórico append-only de alertas efetivamente enviados (projeção do
  `domain.models.Alert`): `execution_id`, `flight_id`, `price` `NUMERIC(12,2)`, `currency`,
  `alerted_at` (timestamptz). Índice composto `(flight_id, alerted_at)`. O "último preço alertado" é
  derivado (max `alerted_at` por `flight_id`), não é uma coluna mutável — fiel a "histórico" +
  retenção indefinida de §3.

## Contrato a implementar (dev-runner)

### `src/persistence/db.py`
1. `build_database_url() -> str` (hoje `NotImplementedError`; contrato 100% fixado pelos testes)
   - Se `DATABASE_URL` setado e não-vazio → retorna verbatim (override para secret manager em prod).
   - Senão monta `postgresql+psycopg://{user}:{password}@{host}:{port}/{db}` a partir de env:
     obrigatórias `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB`; opcionais `POSTGRES_HOST`
     (default `postgres` — nome do serviço docker, **nunca localhost**, §7) e `POSTGRES_PORT`
     (default `5432`).
   - Faltando obrigatória → `RuntimeError` **nomeando a variável** (fail-fast). Usar
     `sqlalchemy.URL.create(...)` para escapar senha; com credenciais simples renderiza a URL acima.
2. `get_engine() -> Engine` — Engine singleton lazy a partir de `build_database_url()`, semântica
   SQLAlchemy 2.0 (`future=True`).
3. `connection_scope() -> AbstractContextManager[Connection]` — `with connection_scope() as conn:`
   abre conexão do `get_engine()` numa transação (`engine.begin()`): commit no sucesso, rollback na
   exceção.

### `src/persistence/repositories.py`
Helpers puros (unit-testáveis, sem DB) — hoje `NotImplementedError`:
4. `flight_to_silver_row(flight, *, execution_id, captured_at) -> dict` — projeta `Flight` nas
   colunas de `silver.flight` (exceto `id`); `flight_id` vem de `Flight.flight_id`; `price` continua
   `Decimal`.
5. `alert_to_gold_row(alert, *, execution_id) -> dict` — projeta `Alert` nas colunas de
   `gold.flight_alert` (exceto `id`).

Repositórios (recebem `Connection` no `__init__`) — corpos `NotImplementedError`:
6. `BronzeRepository.save_raw_response(*, execution_id, route, captured_at, success, payload, error_message=None) -> int`
   — insere 1 linha (payload verbatim como JSONB; `payload=None` permitido em falha), retorna `id`.
   É a gravação que torna a execução "bem-sucedida" (Regra de Persistência / Validações).
7. `SilverRepository.save_flights(*, execution_id, captured_at, flights) -> list[int]` — 1 linha por
   voo via `flight_to_silver_row`, preservando ordem nos ids; entrada vazia → `[]`.
8. `GoldRepository.record_alerts(*, execution_id, alerts) -> list[int]` — append 1 linha por `Alert`
   via `alert_to_gold_row`, preservando ordem; nunca atualiza/deleta linhas anteriores; vazio → `[]`.
9. `GoldRepository.last_alerted_prices(route) -> dict[str, Decimal]` — para cada `flight_id` da rota
   com ≥1 alerta, o `price` do alerta mais recente (max `alerted_at`). Ausência = nunca alertado
   (dedup trata como primeira ocorrência). Filtro por prefixo de rota no `flight_id`
   (`{origin}-{destination}-{YYYY-MM-DD}-...`). É exatamente o `Mapping` que
   `domain.deduplication.select_flights_to_notify` espera.

### Migrations
10. Migration inicial `0001_initial` já escrita (DDL das 3 tabelas + `CREATE SCHEMA IF NOT EXISTS`
    idempotente, mantida em sincronia com `tables.py`). O `dev-runner`/infra roda
    `uv run alembic upgrade head` contra o Postgres (depende de `build_database_url` implementado, que
    o `env.py` usa). `alembic revision --autogenerate` futuro faz diff contra `tables.metadata`.

## Decisões de design / casos de borda resolvidos

- **`gold` = histórico append-only, não upsert de "preço atual".** "Último preço alertado" é derivado
  (max `alerted_at` por `flight_id`), fiel a "histórico" + retenção indefinida (§3). `record_alerts`
  recebe `Sequence[Alert]` (entidade de domínio), não `Flight` — desacopla; a construção do `Alert`
  (com `alerted_at=now`) é do chamador (`orchestration`).
- **`gold.flight_alert` guarda só a projeção do `Alert`** (sem `carrier`/rota): o `flight_id` já
  codifica rota+data+número; `carrier` não é necessário para dedup. Reduz ambiguidade e casa 1:1 com
  o `Alert`. Consulta humana por rota usa o prefixo do `flight_id`.
- **Sem `create_all` em produção** (§4): as tabelas nascem da migration Alembic. `create_all` aparece
  **apenas** na fixture de teste de integração (setup de teste, não é o caminho de produção).
- **`payload` nullable / `success` bool em bronze**: a Validação "execução bem-sucedida = ao menos
  bronze persistido" exige registrar a falha também; `success=False` + `payload=None` +
  `error_message` cobrem a notificação de erro sem inventar tabela de execução separada no MVP.
- **`Decimal` fim-a-fim**: `NUMERIC(12,2)` no banco, `Decimal` nos mappers e no `Mapping` de retorno —
  evita float em dinheiro e casa com a comparação exata da Regra de Deduplicação.
- **Conexão nunca hardcoded**: default host = nome do serviço docker `postgres` (§7); override total
  via `DATABASE_URL` para o futuro secret manager (§5).

## Testes — `test/persistence/`

Config herdada de `pyproject.toml` (`pythonpath=["src"]`, `testpaths=["test"]`). `test/persistence/`
é pacote (`__init__.py`). `conftest.py` reexpõe `make_flight`/`route`/`flight_factory` (espelha o
domínio) e define o **gate de skip** de integração.

### Unitários (sem DB — falham agora por `NotImplementedError`, motivo certo)
- `test_db.py` (7): monta URL a partir dos componentes; default = serviço docker (não localhost);
  nunca localhost/127.0.0.1 por default; `DATABASE_URL` sobrepõe; faltando obrigatória →
  `RuntimeError` nomeando a variável (`pytest.raises(match=...)` — força falhar já, pois
  `NotImplementedError` é subclasse de `RuntimeError` mas sem mensagem).
- `test_mappers.py` (5): `flight_to_silver_row` mapeia todas as colunas / `price` continua `Decimal`
  / `flight_id` == chave de domínio; `alert_to_gold_row` mapeia todas as colunas / `price` `Decimal`.

### Integração (Postgres real — **puláveis automaticamente**, §8 + `.claude/agents/qa.md` §8)
- `test_repositories_integration.py` (11, hoje `skipped`): a fixture `pg_engine`/`pg_connection`
  chama `build_database_url()` + `SELECT 1`; qualquer falha (config não implementada ou DB
  inalcançável) → `pytest.skip`, nunca fail. Com DB disponível cria as tabelas de `tables.metadata`
  (`create_all(checkfirst=True)`) e roda cada teste numa transação com rollback. Cobrem: round-trip
  bronze (sucesso e falha/payload nulo); silver (1 id por voo em ordem; vazio → `[]`); gold
  (`record_alerts` retorna ids; `last_alerted_prices` vazio sem histórico; retorna preço mais recente
  por voo; **pluga direto na dedup do domínio** — voo com mesmo preço é filtrado, alterado é mantido);
  e a existência dos schemas `bronze`/`silver`/`gold`.

Estado atual da suíte (`uv run pytest`): **12 failed, 33 passed, 11 skipped**. As 12 falhas são todas
`NotImplementedError`/mensagem ausente (motivo certo: falta implementação). As 11 puladas são a
integração sem Postgres neste ambiente. As 33 que passam são o domínio já implementado (intocado).
`ruff check` + `ruff format --check` limpos.

## Fora de escopo (não fazer aqui)

- Extração/interceptação do payload da Gol (camada `extraction`) — persistence só recebe o dado.
- Construção do `Alert` (data/hora do alerta) e orquestração da ordem bronze→silver→gold (camada
  `orchestration`/Dagster).
- Compilação/envio da mensagem do Telegram (camada `notification`).
- Rodar a migration contra o Postgres e validar `upgrade head` ponta a ponta — passo de
  `dev-runner`/infra num host com o banco no ar (depende de `build_database_url` implementado).
