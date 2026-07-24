# Plano dev — módulo `src/domain/` (models, eligibility, deduplication)

> Especificação (contrato + testes que falham) para o `dev-runner`. Fonte de verdade das regras:
> `docs/domain/regras_negocio.md`. Padrões técnicos: `docs/standards/architecture.md` §2 e §8.
> Escopo: apenas `src/domain/` (puro, sem I/O; não importa de `extraction`/`persistence`/`notification`).

## Objetivo

Traduzir para código as regras de domínio do MVP: Elegibilidade, Deduplicação e as Validações do
voo capturado, mais os modelos de dados (Flight, Route, Alert). O `dev-planner` entrega o contrato
(assinaturas, docstrings, schema) e a suíte de testes que hoje falha por `NotImplementedError`. O
`dev-runner` implementa o corpo das funções sem alterar as assinaturas.

## Modelo de dados (`src/domain/models.py`) — schema já escrito (não implementar)

- `Route(origin: str, destination: str, departure_date: date)` — dataclass frozen. Par O/D + data
  de ida (glossário "Rota monitorada"). MVP fixo: MCP -> BSB, 2026-09-01.
- `Flight(route, carrier, flight_number, departure_time, price: Decimal, currency)` — dataclass
  frozen. Reúne os campos obrigatórios do voo capturado (Validações). Preço em `Decimal`.
- `Alert(flight_id, price: Decimal, currency, alerted_at: datetime)` — dataclass frozen. Registro do
  "Último preço alertado" por voo (base persistida da deduplicação). NÃO é a mensagem do Telegram
  (isso é da camada `notification`).
- `InvalidFlightError(ValueError)` — erro de validação de domínio.

As dataclasses (fields + frozen) já estão escritas por serem schema puro. O que falta implementar:

## Contrato a implementar (dev-runner)

1. `Flight.flight_id -> str` (property, hoje `NotImplementedError`)
   - Identificador do voo = rota + data de ida + número do voo (glossário "Identificador do voo").
   - Formato do contrato: `"{origin}-{destination}-{YYYY-MM-DD}-{flight_number}"`
     (ex.: `"MCP-BSB-2026-09-01-G3-1234"`). Precisa ser estável entre execuções para o mesmo voo.

2. `models.validate_flight(flight: Flight) -> None` (hoje `NotImplementedError`)
   - Enforce da seção "Validações" de `regras_negocio.md`, 1:1:
     - campos obrigatórios não vazios: carrier, flight_number, origin, destination, currency;
     - `price` numérico e estritamente positivo (`> 0`) — nulo/zero/negativo é falha de extração.
   - Levanta `InvalidFlightError` na primeira regra violada; retorna `None` se válido.

3. `eligibility.is_eligible(flight: Flight) -> bool` e
   `eligibility.select_eligible(flights: Sequence[Flight]) -> list[Flight]`
   - Regra de Elegibilidade — MVP é função identidade: todo voo capturado é elegível (sem teto).
   - `select_eligible` retorna todos os voos, preservando a ordem; entrada vazia -> lista vazia.

4. `deduplication.should_notify(flight: Flight, last_alerted_price: Decimal | None) -> bool` e
   `deduplication.select_flights_to_notify(flights: Sequence[Flight], last_alerted_prices: Mapping[str, Decimal]) -> list[Flight]`
   - Regra de Deduplicação:
     - `last_alerted_price is None` -> notifica (primeira ocorrência);
     - preço diferente (qualquer delta, R$ 0,01 conta) -> notifica;
     - preço numericamente igual -> não notifica.
   - `select_flights_to_notify` aplica `should_notify` por voo (usa `flight_id` como chave do
     mapa; ausência no mapa = nunca alertado), preserva ordem; entrada vazia -> lista vazia.

## Decisões de design / casos de borda resolvidos

- **`Decimal` para preço** e comparação numérica: `Decimal("1000") == Decimal("1000.00")` deve ser
  tratado como igual (não notificar) — evita falso alerta por diferença de escala/formatação.
- **Elegibilidade não revalida**: a entrada de `eligibility`/`deduplication` são voos já capturados
  com sucesso. A validação (`validate_flight`) é responsabilidade da camada silver/extração antes de
  chegar ao domínio de decisão — por isso é função separada, não embutida em `is_eligible`.
- **Route contém a data de ida** (glossário), então `flight_id` = route(O/D + data) + flight_number
  cobre integralmente "rota + data + número do voo" sem redundância de campo.
- **Ordem preservada** nas funções de seleção: a camada de notificação compila uma única mensagem;
  ordem estável evita mensagens não determinísticas.

## Testes que falham (TDD) — `test/domain/`

Config: `pyproject.toml` -> `[tool.pytest.ini_options] pythonpath=["src"]`, `testpaths=["test"]`.
`test/` e `test/domain/` são pacotes (`__init__.py`) para o import relativo do `conftest`.
`test/domain/conftest.py` expõe `make_flight(...)` (fábrica de voo válido, override por kwarg) e as
fixtures `route`, `flight`, `flight_factory`.

- `test_models.py`
  - `TestSchema` (4 testes) — schema/imutabilidade; **já passam** (dataclasses são schema puro).
  - `TestFlightId` (4) — composição do id; mesmo voo/execuções diferentes = mesmo id; nº de voo e
    data diferentes = ids diferentes.
  - `TestValidateFlight` (10) — voo válido passa; preço 0/negativo inválido (parametrizado);
    flight_number/carrier/currency/origin/destination vazios inválidos; menor preço positivo
    (`0.01`) válido.
- `test_eligibility.py` (5) — qualquer voo elegível; voo caro ainda elegível (sem teto);
  `select_eligible` retorna todos preservando ordem; captura vazia -> vazio.
- `test_deduplication.py` (10) — sem alerta anterior notifica; preço alterado/queda/1 centavo
  notifica; preço igual e igual com escala diferente não notifica; `select_flights_to_notify`
  seleciona novo+alterado e exclui inalterado preservando ordem; todos iguais -> vazio; entrada
  vazia -> vazio.

Estado atual da suíte: **29 failed, 4 passed** — as 29 falhas são todas `NotImplementedError`
(motivo certo: falta implementação; nenhum erro de sintaxe/import). As 4 que passam confirmam que o
schema está correto.

## Fora de escopo (não fazer aqui)

- Compilação da mensagem do Telegram (camada `notification`).
- Leitura/escrita do "último preço alertado" no Postgres (camada `persistence`/gold); o domínio só
  recebe o valor já resolvido via parâmetro.
- Notificação de erro/execução (regras de Execução e Notificação) — não pertencem a `src/domain/`.
