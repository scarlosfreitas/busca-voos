# Plano dev — módulo `src/notification/` (composição + envio Telegram)

> Especificação (contrato + testes que falham) para o `dev-runner`. Fonte de verdade das regras:
> `docs/domain/regras_negocio.md` — Regra de Notificação (Telegram). Produto: `PRD.md` §8
> (mensagem clara com horários/valores/data da pesquisa + notificação de falha). Padrões técnicos:
> `docs/standards/architecture.md` §5 (segredos via env), §6 (toda falha propaga p/ notificação de
> erro), §8 (testes). Escopo: camada de integração com o Telegram. `notification` NÃO decide
> elegibilidade/dedup (`domain/`) e NÃO persiste (`persistence/`) — recebe voos já filtrados.

## Objetivo

Transformar a lista de voos que passaram na deduplicação em **uma** mensagem legível em
português (Cia, Data, Trecho, horário(s), preço(s), data da pesquisa) e enviá-la ao Telegram; e,
independentemente, transformar uma falha de extração numa **notificação de erro separada**. O
`dev-planner` entrega o contrato (assinaturas, dataclass de config, exceção tipada) e a suíte que
hoje falha por `NotImplementedError` (unitários puros de composição) ou é pulada automaticamente
(integração de envio real sem credenciais). O `dev-runner` implementa os corpos **sem alterar
assinaturas nem testes**.

## Estrutura entregue

```
src/notification/
├── __init__.py    # superfície pública reexportada para orchestration
└── telegram.py    # constantes + NotificationError + TelegramConfig
                   #   + format_price / format_flight_alert_message / format_failure_message (PUROS)
                   #   + send_telegram_message (I/O)
test/notification/
├── __init__.py
├── conftest.py                 # make_flight / route / flight_factory (espelha persistence)
├── test_format_messages.py     # unit puro da composição (falha por NotImplementedError)
└── test_send_integration.py    # envio real — pulável (opt-in RUN_TELEGRAM_INTEGRATION=1)
```

Estrutura fiel a `architecture.md` §2 (o módulo lista exatamente `telegram.py`). Nenhum arquivo extra
inventado além do `__init__.py` de reexport (mesmo padrão de `extraction/__init__.py`).

## Decisão-chave: composição pura × envio I/O

A regra de negócio testável é **como a mensagem é montada** (conteúdo, ordem, formatação PT-BR de
preço/data/hora). Isso é isolado em funções puras (`format_*`) testadas sem rede nem credenciais. A
parte que fala HTTP com a API do Telegram fica em `send_telegram_message`, coberta só por teste de
integração pulável — mesma convenção de skip de `test/persistence` (Postgres) e `test/extraction`
(browser). Assim a composição é 100% unit-testável e o envio real é mockável/pulável.

## Decisão-chave: biblioteca de envio = `httpx` síncrono (não `python-telegram-bot`)

`python-telegram-bot` é uma dependência declarada, mas é um framework **async-first** desenhado para
construir bots (polling, handlers, `Application`/updater). Para um job batch diário que dispara
**um** `sendMessage` fire-and-forget no fim da execução, um `POST` síncrono a
`https://api.telegram.org/bot{token}/sendMessage` via `httpx` é mais simples, síncrono (casa com o
fluxo do pipeline) e trivial de mockar/pular em teste. `httpx` já vem transitivamente com o
`python-telegram-bot`; foi **promovido a dependência explícita** em `pyproject.toml` (não se deve
depender de dep transitiva). Ver "Pendências" para o destino do `python-telegram-bot`.

## Contrato a implementar (dev-runner)

### Constantes (`telegram.py`)
- `TELEGRAM_API_BASE = "https://api.telegram.org"` — endpoint por bot é
  `{TELEGRAM_API_BASE}/bot{token}/sendMessage`. Nunca host hardcoded fora daqui.
- `DEFAULT_TIMEOUT_SECONDS = 15.0` — timeout de um `sendMessage` (o Telegram é rápido; **não** usa o
  orçamento de 5 min da extração).
- `FAILURE_LABEL_FALLBACK = "Falha inesperada"` — rótulo default para exceção sem tipo conhecido.

### Exceção
- `NotificationError(Exception)` — falha de entrega (erro de transporte: conexão/timeout; ou
  resposta não-2xx / envelope `{"ok": false}`). Contrato: **nunca engolir** falha de envio; sempre
  visível para `orchestration` capturar/logar (`architecture.md` §6).

### Config (segredos via env, `architecture.md` §5)
- `TelegramConfig(bot_token: str, chat_id: str)` — frozen dataclass.
- `TelegramConfig.from_env(env=None) -> TelegramConfig` (hoje `NotImplementedError`) — lê
  `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` de `env` (default `os.environ`); ausente/vazio →
  `RuntimeError` **nomeando a variável** (fail-fast; evita "não notificar em silêncio"). Placeholders
  já existem em `.env.example` (raiz); a criação real do bot/token é passo manual do operador via
  @BotFather (fora de escopo).

### Composição pura (network-free, unit-testada) — hoje `NotImplementedError`
1. `format_price(price: Decimal, currency: str) -> str`
   - `BRL` → formato brasileiro `R$ 1.234,56` (ponto milhar, vírgula decimal, sempre 2 casas);
     `Decimal("890.00")` → `R$ 890,00`.
   - outra moeda → genérico `"{currency} {amount}"` com 2 casas (MVP só captura BRL).
   - `Decimal` in / `str` out — nunca passa por `float` (precisão monetária).
2. `format_flight_alert_message(flights: Sequence[Flight], search_date: date) -> str`
   - **Uma** string cobrindo **todos** os voos, **na ordem de entrada** (não reordena/filtra — só
     renderiza; a ordem/filtro é do chamador).
   - Cada voo rende ao menos: Cia (`carrier`), Trecho (`origin → destination`), Data do voo
     (`route.departure_date`, `dd/mm/aaaa`), horário (`HH:MM`) e preço (via `format_price`).
   - Declara a **data da pesquisa** (`search_date`) **uma vez**, em `dd/mm/aaaa`.
   - **Lista vazia → `ValueError`.** Decidir *não* notificar em lista vazia é da `orchestration`
     (ela simplesmente não chama esta função); montar um "alerta vazio" é erro de programação e deve
     estourar alto. Isto fixa no código **quem decide o quê**.
3. `format_failure_message(error, *, search_date, route=None) -> str`
   - Mensagem PT-BR sinalizando falha da execução — **separada e independente** do alerta de voos
     (`regras_negocio.md` Notificação de falha; `architecture.md` §6).
   - Rótulo humano derivado do **tipo** da exceção (subclasses de `ExtractionError` — block/timeout/
     malformed — cada uma com rótulo distinto; qualquer outra → `FAILURE_LABEL_FALLBACK`) **mais** o
     texto do erro (`str(error)`) para diagnóstico.
   - Declara `search_date` (`dd/mm/aaaa`) e, se `route` dado, o trecho + data do voo.
   - **NÃO importa `extraction`** (direção de dependência): keia pelo **nome/tipo** da exceção
     (`type(error).__name__` ou mapeamento por nome de classe), degradando graciosamente para
     qualquer `Exception`.

### Envio I/O (integração pulável) — hoje `NotImplementedError`
4. `send_telegram_message(text, config, *, timeout_seconds=DEFAULT_TIMEOUT_SECONDS, parse_mode=None) -> None`
   - `POST` único a `{TELEGRAM_API_BASE}/bot{config.bot_token}/sendMessage` com `chat_id`/`text`
     (e `parse_mode` quando dado) via `httpx` síncrono.
   - Recebe o `text` **já composto** (das `format_*`) — separação que mantém composição testável sem
     rede e envio mockável.
   - Erro de transporte (conexão/timeout) → `NotificationError` embrulhando a causa; resposta não-2xx
     ou `{"ok": false}` → `NotificationError` com status/descrição. Sucesso → `None`. Nunca engole.

## Decisões de design / casos de borda resolvidos

- **Quem decide não notificar em lista vazia = orchestration.** Contrato deixa isso explícito: a
  função de composição do alerta **recusa** lista vazia (`ValueError`); a `orchestration` é que checa
  "lista vazia → não chama `send`". Fiel à Regra de Notificação (lista vazia → nenhuma mensagem).
- **Alerta × falha são mutuamente independentes.** Duas funções de composição distintas; uma
  execução com falha não chega a produzir voos elegíveis (Regra de Notificação — 0/1 alerta + 0/1
  erro por execução). `orchestration` orquestra qual disparar.
- **`Decimal` fim-a-fim.** `format_price` recebe `Decimal` e formata sem `float` — casa com a
  comparação exata da dedup e com `NUMERIC(12,2)` da persistência.
- **Falha de envio nunca silenciosa.** `NotificationError` tipada envolve transporte e API
  (`architecture.md` §6). `orchestration` decide o que fazer, mas o erro sempre aparece.
- **Segredos só via env** (`architecture.md` §5): `from_env` fail-fast nomeando a variável ausente;
  nada hardcoded. `TELEGRAM_API_BASE` é a única constante de host (não é segredo).
- **Desacoplamento de `extraction`:** `format_failure_message` não importa `extraction.errors`; keia
  pelo nome do tipo. O teste importa as classes reais (teste pode; o módulo não) para provar a
  distinção de rótulo.

## Testes — `test/notification/`

Config herdada de `pyproject.toml` (`pythonpath=["src"]`, `testpaths=["test"]`). `conftest.py`
reexpõe `make_flight`/`route`/`flight_factory` (espelha `test/persistence/conftest.py`).

### Unitários (sem rede — falham agora por `NotImplementedError`, motivo certo) — `test_format_messages.py` (11)
- `format_price`: BRL com milhar (`R$ 1.234,56`); BRL 2 casas (`R$ 890,00`); não-BRL genérico
  (contém `USD`, não contém `R$`).
- alerta 1 voo: mensagem contém Cia/Trecho (MCP,BSB)/Data do voo (`01/09/2026`)/horário (`08:30`)/
  preço (`R$ 1.234,56`)/data da pesquisa (`24/07/2026`); data da pesquisa aparece **uma vez**.
- alerta N voos: todos renderizados; **ordem preservada** (`index(06:00) < index(09:15) < index(20:45)`);
  é **uma** mensagem (data da pesquisa uma vez).
- alerta lista vazia → `ValueError` (hoje falha por `NotImplementedError`, que o dev-runner troca por
  `ValueError`).
- falha: contém `str(error)` + data da pesquisa + trecho quando `route` dado; funciona sem `route`;
  tipos de erro distintos (mesmo texto de erro) geram mensagens **diferentes** (rótulo por tipo).

### Integração (envio real — **pulável automaticamente**, `architecture.md` §8 / `qa.md` §8) — `test_send_integration.py` (1)
- `skipif RUN_TELEGRAM_INTEGRATION != "1"` (opt-in — envio real bate no Telegram pela rede). Ainda
  pula se `from_env` não implementado / sem credenciais, e se `send`/`format` não implementados.
  `NotificationError` numa entrega real vira **skip** (condição de rede transitória) — contrato é ser
  tipada, não que o Telegram esteja sempre acessível. Mesma filosofia do skip de extração.

Estado da suíte (`uv run pytest`): **11 failed, 71 passed, 19 skipped**. As 11 falhas são todas
`NotImplementedError` (motivo certo: falta implementação). Skips = persistência sem Postgres +
extração sem opt-in/browser + Telegram sem opt-in/credenciais. `ruff check`/`format` limpos nos
arquivos de `notification` (as 5 lint + 2 format pendentes são pré-existentes em `test/domain/`,
fora deste escopo).

## Ambiguidades / pendências para o dev-runner (IMPORTANTE)

1. **Layout exato da mensagem é livre.** Os testes fixam **conteúdo** (substrings: Cia, trecho,
   datas `dd/mm/aaaa`, hora `HH:MM`, preço `R$ x.xxx,xx`, data da pesquisa uma vez) e **ordem**, não
   a diagramação linha-a-linha. O `dev-runner` decide emojis/quebras/ordem dos campos — desde que os
   substrings existam. Se optar por `parse_mode="HTML"`, precisa escapar `< > &` no texto dinâmico.
2. **`parse_mode` opcional.** Deixei `parse_mode=None` no contrato; decidir se envia como texto puro
   ou HTML/MarkdownV2 é do `dev-runner` (afeta escaping, não a assinatura).
3. **Destino do `python-telegram-bot`.** O contrato usa `httpx`. Se ninguém mais usar
   `python-telegram-bot`, ele vira dependência morta — o `dev-runner`/humano pode removê-lo do
   `pyproject.toml` numa limpeza. Não removi aqui para não tomar decisão de dependência maior fora do
   escopo do módulo.
4. **Rótulos PT-BR das falhas.** A tabela tipo-de-exceção → rótulo (block/timeout/malformed) é do
   `dev-runner`; o teste só exige que tipos distintos gerem rótulos distintos e que
   desconhecido caia no `FAILURE_LABEL_FALLBACK`. Ver `regras_negocio.md` (Notificação de falha) para
   a semântica de cada tipo.

## Fora de escopo (não fazer aqui)

- Decidir **quando** disparar alerta vs. erro e checar lista vazia — camada `orchestration`/Dagster.
- Construir a lista de voos deduplicada (`domain/`) e o `Alert`/persistência (`domain`/`persistence`).
- Interceptar/traduzir a falha de extração em `ExtractionError` — camada `extraction` (já entregue);
  `notification` só a renderiza.
- Criar o bot/token no @BotFather e rodar o envio real ponta a ponta — passo manual do operador com
  credenciais (`RUN_TELEGRAM_INTEGRATION=1`).
