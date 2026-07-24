# Plano dev — módulo `src/extraction/` (browser, gol, errors)

> Especificação (contrato + testes que falham) para o `dev-runner`. Fonte de verdade das regras:
> `docs/domain/regras_negocio.md`. Padrões técnicos: `docs/standards/architecture.md` §1 (pipeline:
> extraction intercepta payload JSON da Gol → bronze), §2 (estrutura de módulos, desacoplamento),
> §6 (tratamento de erros/timeouts 5+min), §8 (testes). Produto: `PRD.md` §3/§4/§6/§7/§8.
> Escopo: camada de scraping. Extraction NÃO depende de `domain/` nem `persistence/` — produz seus
> próprios value objects que `orchestration` cola nas outras camadas.

## Objetivo

Acessar a busca pública/anônima da Gol via Playwright headless + `playwright-stealth`, interceptar a
**resposta de rede (payload JSON)** — nunca parsear HTML (PRD §8) — e transformar esse payload em
registros tipados de "voo capturado". O `dev-planner` entrega o contrato (assinaturas, dataclasses,
hierarquia de exceções) e a suíte que hoje falha por `NotImplementedError` (unitários puros) ou é
pulada automaticamente (integração de browser/rede). O `dev-runner` implementa os corpos **sem
alterar assinaturas nem testes**.

## Decisão pós-QA (2026-07-24)

O QA apontou que `departureDateTime` sem componente de hora (ex.: `"2026-09-01"`) é aceito
silenciosamente por `datetime.fromisoformat` como meia-noite, em vez de virar
`MalformedPayloadError`. Decisão: **aceitar o comportamento atual** — o payload real da Gol sempre
inclui horário de partida (é campo exibido na UI), então esse formato não é esperado na prática; se
aparecer, meia-noite é um valor "razoavelmente errado" mas não silenciosamente perigoso o bastante
para justificar mais uma exceção especial no parser puro no MVP. Revisitar apenas se uma captura
real da Gol expuser esse formato de fato.

## Estrutura entregue

```
src/extraction/
├── __init__.py   # superfície pública reexportada para orchestration
├── errors.py     # ExtractionError + BlockedError / ExtractionTimeoutError / MalformedPayloadError
├── browser.py    # BrowserConfig/ProxyConfig + from_env (puro) + pick_delay_seconds (puro)
│                 #   + stealth_page_session / human_delay (I/O, integração)
└── gol.py        # CapturedFlight / GolSearchParams / GolCaptureResult
                  #   + parse_gol_response (PURO — coração testável) + capture_gol_search (I/O)
test/extraction/
├── conftest.py                 # loader de fixtures JSON sintéticas
├── fixtures/gol_response_*.json  # sample / empty / malformed / blocked
├── test_parse_gol_response.py  # unit do parser puro (falha por NotImplementedError)
├── test_browser_config.py      # unit de from_env + pick_delay_seconds + constantes
└── test_capture_integration.py # integração de browser/rede — pulável (opt-in)
```

Nota de estrutura: `architecture.md` §2 lista só `browser.py` e `gol.py` para `extraction/`.
Adicionei `errors.py` para manter a hierarquia de exceções num único ponto importável (mesma
justificativa do `persistence/tables.py` no plano da persistência). Documentado aqui para o
`dev-runner`/`qa` não tratarem como divergência.

## Decisão-chave: split puro (parser) × I/O (browser)

Não dá para testar contra o site real da Gol em unit test. Por isso a lógica de **parsing do payload
interceptado** é uma função pura (`parse_gol_response`) testada com fixtures JSON sintéticas; a parte
que **abre o navegador e navega** fica isolada em funções async (`capture_gol_search`,
`stealth_page_session`) cobertas só por teste de integração pulável. É a mesma convenção de skip da
persistência (`test/persistence/conftest.py` para Postgres) aplicada a browser/rede.

## Decisão-chave: desacoplamento (extraction não conhece domain/persistence)

`extraction` emite seu próprio value object `CapturedFlight` (NÃO `domain.models.Flight`) e o payload
cru. Quem cola as camadas é `orchestration` (fora deste escopo):
- `GolCaptureResult.raw_payload` → gravado **verbatim** em `bronze.raw_search_response` (append-only,
  sem transformação — `architecture.md` §3).
- `GolCaptureResult.flights` (`tuple[CapturedFlight, ...]`) → orchestration mapeia para
  `domain.models.Flight` (aplicando `validate_flight`) e persiste em silver/gold.

Consequência importante: a regra "preço deve ser positivo" (`regras_negocio.md` §Validações)
permanece **single-sourced no domínio** — `parse_gol_response` NÃO reimplementa essa validação (ver
boundary abaixo). Extraction não duplica regra de negócio.

## Modelo de dados (schemas já escritos — não reimplementar)

- `errors.ExtractionError` (base) + `BlockedError`, `ExtractionTimeoutError`, `MalformedPayloadError`.
- `browser.ProxyConfig(server, username?, password?)` — proxy residencial opcional (PRD §4/§7).
- `browser.BrowserConfig(headless, user_agent, locale, proxy?, navigation_timeout_ms,
  min_delay_seconds, max_delay_seconds)` — defaults = contrato do MVP (headless, UA orgânica,
  `pt-BR`, sem proxy, timeout 5 min).
- `gol.GolSearchParams(origin, destination, departure_date, adults=1, cabin="economy")` +
  `MVP_SEARCH_PARAMS` (MCP→BSB, 2026-09-01) — fonte única dos parâmetros de busca (`architecture.md`
  §5; `regras_negocio.md` "Parâmetros de busca").
- `gol.CapturedFlight(carrier, flight_number, origin, destination, departure_date, departure_time,
  price: Decimal, currency, cabin)` — fiel ao payload; `carrier`/`flight_number` são as partes cruas
  do designador (ex. `"G3"`/`"1234"`), a chave de dedup do domínio (`G3-1234`) é composta por
  orchestration. `Decimal` fim-a-fim (nunca float em dinheiro).
- `gol.GolCaptureResult(raw_payload, flights)`.

## Contrato a implementar (dev-runner)

### `src/extraction/browser.py` (puro — falha nos testes agora)
1. `BrowserConfig.from_env(env=None) -> BrowserConfig`
   - `env` default `os.environ`.
   - **Proxy opcional**: `PROXY_SERVER` vazio/ausente → `proxy=None` (roda sem proxy, PRD §4/§7);
     setado → `ProxyConfig` com `PROXY_USERNAME`/`PROXY_PASSWORD` opcionais.
   - `EXTRACTION_USER_AGENT` sobrepõe `DEFAULT_USER_AGENT`; `EXTRACTION_NAV_TIMEOUT_MS` sobrepõe o
     timeout (default 5 min — floor do PRD §6); `EXTRACTION_HEADLESS` (`0/false/no`→False) e
     `EXTRACTION_LOCALE` sobrepõem o resto.
2. `pick_delay_seconds(config, rng=None) -> float` — valor no intervalo fechado
   `[min_delay_seconds, max_delay_seconds]`; `rng` injetável para teste determinístico.

### `src/extraction/browser.py` (I/O — integração)
3. `human_delay(config, rng=None)` — `asyncio.sleep(pick_delay_seconds(...))` (PRD §4, delays).
4. `stealth_page_session(config)` — async CM (`@asynccontextmanager`; hoje há `yield` inalcançável
   marcando o gerador) que lança Chromium headless + stealth, aplica UA/locale/proxy/timeout longo e
   garante teardown. Falhas de baixo nível devem virar subclasse de `ExtractionError`, nunca vazar.

### `src/extraction/gol.py` (puro — coração testável)
5. `parse_gol_response(payload) -> tuple[CapturedFlight, ...]`
   - Shape sintético assumido (ver docstring): `{"trips":[{"origin","destination","departureDate",
     "flights":[{"airlineCode","flightNumber","departureDateTime","cabin","fare":{"amount","currency"}}]}]}`.
   - Válido → tupla de `CapturedFlight`, um por voo, na ordem do documento; `price=Decimal(amount)`;
     `departure_date`/`departure_time` de `departureDateTime`.
   - `trips` presente mas sem voos (`flights:[]` / `trips:[]`) → `()` (sem disponibilidade = captura
     bem-sucedida vazia; `regras_negocio.md` Elegibilidade caso de borda).
   - Não é o container esperado (não-`dict` ou sem a chave `trips`) → `BlockedError` (esperávamos a
     API JSON e veio outra coisa: challenge/redirect/WAF — PRD §8).
   - Container correto mas registro inválido (campo obrigatório faltando, `amount` não-numérico,
     `departureDateTime` impossível de tipar) → `MalformedPayloadError`.

### `src/extraction/gol.py` (I/O — integração)
6. `capture_gol_search(params=MVP_SEARCH_PARAMS, *, browser_config=None) -> GolCaptureResult`
   - Abre página via `stealth_page_session` (config default `BrowserConfig.from_env()`), navega a
     busca anônima MCP→BSB 2026-09-01 1 adulto/econômica com delays humanos, registra interceptor da
     resposta de disponibilidade (`GOL_AVAILABILITY_URL_FRAGMENT`) e aguarda dentro do timeout longo.
   - Sucesso → `GolCaptureResult(raw_payload=<json>, flights=parse_gol_response(<json>))`.
   - **Tradução de falha (nunca vazar exceção crua):** timeout de nav/resposta → `ExtractionTimeoutError`;
     CAPTCHA/challenge/resposta-não-API → `BlockedError`; registro inválido → `MalformedPayloadError`
     (propagado do parser). É isso que permite a orchestration capturar e disparar a notificação de
     falha via Telegram (`architecture.md` §6; `regras_negocio.md` Notificação de falha).

## Decisões de design / casos de borda resolvidos

- **Boundary do preço positivo (single-source):** `parse_gol_response` retorna preço 0/negativo
  presente **fielmente** como `Decimal` — NÃO é erro de extração. A regra "preço positivo" é do
  `domain.validate_flight`, aplicada por orchestration ao construir o `Flight`. Teste
  `test_zero_price_is_not_an_extraction_error` fixa isso para o `dev-runner` não duplicar a regra.
- **Block × Malformed (heurística explícita e testável):** ausência do container esperado (`trips`)
  = `BlockedError`; container presente + registro quebrado = `MalformedPayloadError`. Distinção
  fiel a §6 (erro de infra × erro de dado, tags/níveis distintos).
- **Empty ≠ erro:** "sem disponibilidade" é execução bem-sucedida com `flights=()` — não notifica
  (Regra de Notificação), mas persiste bronze (execução "bem-sucedida" = bronze gravado).
- **`raw_payload` + `flights` juntos:** extraction devolve os dois (cru p/ bronze, tipado p/
  orchestration) — resolve a pergunta "bruto e/ou parseado" da tarefa: **ambos**.
- **Proxy opcional de verdade:** sem `PROXY_SERVER` → `proxy=None`, roda sem proxy até haver provedor
  contratado (PRD §4/§7). Nada hardcoded; tudo via env (`architecture.md` §5).
- **Timeout 5+ min como default de contrato:** `DEFAULT_NAVIGATION_TIMEOUT_MS = 300_000`; teste de
  constante garante o floor mesmo antes de `from_env` existir.
- **UA orgânica:** `DEFAULT_USER_AGENT` sem "Headless" (PRD §4); teste de constante trava isso.
- **Sem dependência de pytest-asyncio:** o teste de integração roda a corrotina via `asyncio.run`,
  evitando adicionar dependência de teste e o warning de marker desconhecido.

## Testes — `test/extraction/`

Config herdada de `pyproject.toml` (`pythonpath=["src"]`, `testpaths=["test"]`). `conftest.py`
carrega as fixtures JSON.

### Unitários (sem browser — falham agora por `NotImplementedError`, motivo certo)
- `test_parse_gol_response.py` (12): válido (ordem, campos fiéis/tipados, `Decimal`, `time`);
  empty/sem-trips → `()`; blocked (envelope access-denied, sem `trips`, não-`dict`) → `BlockedError`;
  malformed (campo faltando, preço não-numérico, datetime impossível) → `MalformedPayloadError`;
  boundary de preço zero.
- `test_browser_config.py` (10): 2 de constante (timeout ≥ 5 min; UA sem "Headless") **passam** e
  documentam o contrato; 7 de `from_env` (proxy None sem env / proxy populado / timeout default /
  timeout via env / UA default / UA via env) e 1 de `pick_delay_seconds` (dentro dos limites, `rng`
  seedado) **falham** por `NotImplementedError`.

### Integração (browser/rede real — **pulável automaticamente**, `architecture.md` §8 / `qa.md` §8)
- `test_capture_integration.py` (1): `skipif RUN_GOL_INTEGRATION != "1"` (opt-in — captura real bate
  na Gol pela rede, nunca roda por default); ainda pula se Playwright não importável ou
  `capture_gol_search` não implementado; uma `ExtractionError` tipada numa captura real vira skip
  (contrato é ser tipada, não que a Gol sempre responda).

Estado da suíte (`uv run pytest`): **20 failed, 47 passed, 18 skipped**. As 20 falhas são todas
`NotImplementedError` (motivo certo: falta implementação). Skips = persistência sem Postgres +
integração de extração sem opt-in/browser. `ruff check` + `ruff format --check` limpos.

## Ambiguidades / pendências para o dev-runner (IMPORTANTE)

1. **O shape do payload da Gol é SINTÉTICO.** Nenhuma resposta real foi capturada ainda. As chaves
   (`trips`, `airlineCode`, `flightNumber`, `departureDateTime`, `fare.amount/currency`), o
   `GOL_TRIPS_KEY`, o `GOL_SEARCH_URL` e o `GOL_AVAILABILITY_URL_FRAGMENT` são **placeholders**. O
   `dev-runner` deve capturar um payload real (DevTools/interceptação) e ajustar o mapeamento do
   parser + as fixtures. O **contrato** (assinaturas, tipos de retorno, hierarquia de erro, split
   puro/I-O, semântica block/empty/malformed) é estável independente do shape real.
2. **Endpoint de interceptação a confirmar:** qual request XHR/Fetch carrega a disponibilidade e como
   casar sua URL. Placeholder em `GOL_AVAILABILITY_URL_FRAGMENT`.
3. **Detecção de block em tempo de captura:** além da heurística do parser (payload ≠ container
   esperado), decidir se há sinais de challenge antes da resposta (status HTTP, redirect para página
   de CAPTCHA) — mapear para `BlockedError`.
4. **Fill vs deep-link:** decidir entre preencher o formulário de busca (mais humano, mais frágil) ou
   navegar por deep-link com os parâmetros na URL. Impacta `capture_gol_search`, não o contrato.

## Fora de escopo (não fazer aqui)

- Mapear `CapturedFlight` → `domain.models.Flight` e persistir bronze/silver/gold — camada
  `orchestration`/`persistence`.
- Elegibilidade/deduplicação/notificação (Telegram) — `domain`/`notification`.
- Construir o `Alert` e orquestrar a ordem do pipeline (Dagster) — `orchestration`.
- Rodar a captura real contra a Gol e validar evasão anti-bot ponta a ponta — passo de `dev-runner`
  num host com browser + rede (depende dos placeholders resolvidos).
