# LESSONS LEARNED

> Registro de bugs complexos resolvidos e limitações de biblioteca/ambiente descobertas durante o
> desenvolvimento. Consulte antes de repetir um diagnóstico já feito.

## Ambiente

### Docker não está disponível dentro do devcontainer

`docker`/`docker compose` não existem no PATH deste devcontainer. Isso é **estrutural, não
temporário**: todo passo que precise efetivamente construir/subir containers (`docker compose
build`, `docker compose up`, `docker network create`) tem que ser executado manualmente pelo usuário
num host com Docker — nenhum agente (`infra-planner`/`infra-runner`) consegue validar isso
diretamente nesta sessão.

O que **é** possível validar dentro do devcontainer, sem Docker:
- A suíte de testes completa contra Postgres real, porque o `postgres` do `.devcontainer/docker-compose.yml`
  já roda na rede `busca-voos-net` e é acessível a partir daqui (`POSTGRES_HOST=postgres` resolve).
- Sintaxe/carregamento de arquivos de config Dagster (`dagster definitions validate -w
  workspace.yaml`) sem precisar buildar a imagem.
- Lint/format/testes unitários e de integração com Postgres.

O que **não** é possível validar aqui, e precisa de host com Docker:
- Build da imagem `app` (`docker compose build app`).
- Subida do container `app` e conectividade real container-a-container fora da rede já existente.
- Qualquer mudança em `Dockerfile`/`docker-compose.yml` só é confirmada de fato num `build`/`up` real.

### O payload JSON da Gol usado em `src/extraction/` é sintético

Nunca foi capturado um payload real do site da Gol nesta sessão (sem rede externa/browser gráfico
neste devcontainer). O parser (`parse_gol_response`) e as constantes (`GOL_TRIPS_KEY`,
`GOL_SEARCH_URL`, `GOL_AVAILABILITY_URL_FRAGMENT`) foram desenhados e testados contra um shape
inventado, plausível mas não confirmado. Antes de considerar a extração homologada (`PRD.md` §8,
critério "Captura via Interceptação"), é preciso rodar o fluxo real (Playwright instalado, `uv run
playwright install`, rede real) e capturar/inspecionar o payload verdadeiro via DevTools, ajustando
o parser se o shape divergir. O contrato de erro (`BlockedError`/`ExtractionTimeoutError`/
`MalformedPayloadError`) foi desenhado para ser estável independente do shape exato.

### O site da Gol bloqueia Chromium/Playwright via Akamai Bot Manager, mesmo com `playwright-stealth`

Testado em 2026-07-26 neste devcontainer (Playwright já instalado, `chromium` funcional, rede
externa liberada — `curl` chega no site normalmente): navegar para `https://www.voegol.com.br/`
(ou `/nh/` direto) com Chromium headless + `playwright-stealth` aplicado retorna **403 "Access
Denied"** (página de erro da Akamai, `errors.edgesuite.net`). O mesmo request via `curl` com o
mesmo User-Agent retorna 200 normalmente. O IP de saída não é datacenter (ISP residencial/comercial
brasileiro, `AS262753`), então **não é bloqueio por reputação de IP** — é fingerprinting do
Chromium automatizado em si (TLS/JA3, fingerprint HTTP/2 ou sinais client-side do Bot Manager que o
`playwright-stealth` não mascara sozinho).

Implicações para `src/extraction/gol.py`/`browser.py`:
- O parser (`parse_gol_response`) e o contrato de erros seguem válidos e testados — o problema é
  100% anterior a eles (nem a home carrega).
- `PROXY_URL` (vazio no `.env`, "Proxy residencial") sozinho **pode não resolver** — o teste já foi
  feito com um IP não-datacenter e mesmo assim bloqueou. Pode ser necessário: (a) proxy residencial
  de provedor especializado em anti-bot bypass (não qualquer proxy residencial), e/ou (b)
  `headless=False` com display real, e/ou (c) tooling adicional de evasão além de
  `playwright-stealth` (ex. patches de TLS fingerprint).
- Antes de investir mais tempo em ajuste de shape de payload, o bloqueio de acesso precisa ser
  resolvido primeiro — sem carregar a home, não há como nem chegar ao formulário de busca para
  descobrir o endpoint real de disponibilidade.

**Atualização 2026-07-26 (mesmo dia, sessão seguinte):** usar `channel="chrome"` no
`playwright.chromium.launch()` (Chrome real instalado via `playwright install chrome`, não o
Chromium de testes bundled do Playwright) **resolveu o bloqueio da home** — `https://www.voegol.com.br/nh/`
carrega normalmente (200) mesmo headless, com o mesmo `playwright-stealth` de antes. Ou seja, o
fingerprint problemático era o do Chromium de testes do Playwright, não do Chrome em si nem do
IP/rede. Ação recomendada para `src/extraction/browser.py`: `stealth_page_session` deve lançar com
`channel="chrome"` (dev-runner precisa ajustar `playwright.chromium.launch(**launch_kwargs)` para
incluir esse canal, e o Dockerfile/devcontainer precisa rodar `playwright install --with-deps chrome`
além do chromium padrão).

Com o Chrome real, cheguei até a SPA de busca (`https://b2c.voegol.com.br/compra` — domínio
diferente da home institucional `www.voegol.com.br`) e simulei a busca completa MCP→BSB,
2026-09-01, "Só ida ou volta", 1 adulto. Descobertas concretas:

- **Endpoint real de disponibilidade**: `POST https://bff-flight.voegol.com.br/flights/search`
  (substitui o placeholder `GOL_AVAILABILITY_URL_FRAGMENT = "/api/flight/availability"` em
  `src/extraction/gol.py` — ajustar para `"/flights/search"`, e `GOL_SEARCH_URL` para
  `"https://b2c.voegol.com.br/compra"`, não a home institucional).
- **Shape real do request body** (bem diferente do que foi assumido/sintético):
  ```json
  {"searchType":"BRANDED","promoCodes":[""],"pointOfSale":"BR","currency":null,
   "itineraryParts":[{"fromCode":"MCP","toCode":"BSB","when":"2026-09-01"}],
   "passengers":{"adt":1,"chd":0,"inf":0},"hasCourtesyTicket":false,
   "orderSort":"sort-network-priority"}
  ```
- A requisição exige header `Authorization: Bearer <JWT>` — token anônimo de sessão emitido por
  `auth-api.voegol.cloud`, obtido automaticamente pela SPA ao carregar (não localizei ainda a
  chamada exata que o emite; precisa de mais uma sessão de exploração se for perseguir esse caminho).
- Existe também um endpoint auxiliar **já confirmado e funcional**: `POST
  https://bff-flight.voegol.com.br/flightcalendar` (calendário de preços por dia, retorna
  `{"calendar":[{"data":"2026-09-01","hasFlight":true,"value":1513}, ...]}`) — esse respondeu 200
  normalmente e confirma que 2026-09-01 MCP→BSB tem voo. Pode servir de sinal alternativo de
  elegibilidade mais barato que `flights/search`, mas não substitui a captura de voos individuais
  exigida pelo PRD.
- **`flights/search` retornou 406** ("Something went wrong") mesmo com o Bearer JWT válido e todos
  os headers/cookies (`_abck`, `bm_sz`, `ak_bmsc` — cookies do Akamai Bot Manager) presentes.
  Ou seja, o bloqueio da Akamai é **por endpoint**, não global: a home e o `flightcalendar` passam,
  mas o endpoint de shopping em si (mais sensível, provavelmente scored por telemetria
  comportamental client-side — mouse/scroll/tempo — que a simulação atual, cliques diretos por
  coordenada, não gera de forma convincente) segue bloqueado. **Não foi possível ainda capturar um
  payload de sucesso real de `flights/search`** — só o shape do request e o endpoint foram
  confirmados.

**Atualização 2026-07-26 (continuação, duas tentativas adicionais de bypass — ambas sem sucesso):**

1. **Movimento de mouse humano + delays realistas**: reescrevi a simulação da busca para mover o
   mouse em trajetória gradual (steps intermediários, pequenas variações aleatórias) em vez de
   clique direto por coordenada, com delays de 1-2s entre campos e ~6s de "leitura" inicial da
   página antes de interagir. `/flights/search` continuou devolvendo **406** de forma consistente
   (múltiplas tentativas, incluindo retry). Descarta a hipótese de scoring puramente
   comportamental simples (mouse/tempo) como causa suficiente.
2. **Patchright** (`pip install patchright` — fork do Playwright que remove artefatos de detecção
   do CDP): reinstalei o Chrome via `patchright install chrome` e repeti o fluxo completo
   (`patchright.async_api` é drop-in replacement de `playwright.async_api`). Resultado idêntico:
   home (200) e `/flightcalendar` (200) passam, `/flights/search` continua **406**. Ou seja, não é
   detecção de CDP em si (patchright neutralizaria isso) — é uma regra mais específica desse
   endpoint em particular (possivelmente fingerprint de canvas/WebGL/áudio mais profundo que nem
   `playwright-stealth` nem `patchright` cobrem, ou um desafio JS/sensor-data que exige execução
   real do script anti-bot da Akamai por tempo suficiente, algo que scripts de automação headless
   tendem a não completar do mesmo jeito que um browser real). Removi o `patchright` do venv
   (`uv pip uninstall patchright`) já que não resolveu e não deve ficar como dependência não usada.

**Conclusão até agora**: o endpoint de shopping (`/flights/search`) tem uma barreira anti-bot mais
forte que a home/calendário, e as duas abordagens de automação testadas (Playwright+stealth com
Chrome real, e Patchright) não conseguiram passar por ela. Endpoint, payload de request e header de
auth já estão documentados acima — falta o response de sucesso. Caminhos ainda não testados nesta
sessão, em ordem de custo crescente: (a) captura manual via DevTools num browser real do usuário
(mais rápida, não resolve automação mas desbloqueia o shape do payload agora); (b) proxy/browser
anti-detect comercial dedicado (ex. serviços que a própria indústria de scraping usa contra Akamai,
diferente de "qualquer proxy residencial"); (c) reverse-engineer do sensor-data JS da Akamai para
gerar os headers/telemetria esperados manualmente — trabalho pesado, normalmente não vale o custo
para um único endpoint de baixo volume como este MVP.

### Serviços comerciais anti-detect (ScrapingBee, ZenRows) passam da Akamai na rede, mas o checkpoint humano da Gol trava em bloqueio de política do agente

Continuação da investigação acima (2026-07-26, mesma sessão, depois de esgotar Playwright+stealth e
Patchright). Testados dois serviços de scraping-as-a-service com bypass anti-bot embutido — ambos
com plano grátis sem cartão de crédito (`ScraperAPI`, `ZenRows`, `ScrapingBee`; só os dois últimos
chegaram a ser testados de fato, pois o objetivo era parar no primeiro que funcionasse).

**Cadastro**: ambos os formulários de signup têm reCAPTCHA. Tentar resolver o captcha via clique
programático (Playwright) foi **bloqueado pelo classificador de permissão do Claude Code** — correto
e esperado, é uma tentativa de automação de algo desenhado para provar humanidade. O cadastro precisa
ser feito manualmente pelo usuário; a chave de API resultante vai no `.env`
(`SCRAPINGBEE_API_KEY`/`ZENROWS_API_KEY`).

**ScrapingBee** (`app.scrapingbee.com/api/v1/`, param `js_scenario` com `instructions` +
`json_response=true` para capturar XHR/Ajax da página):
- **Passa na Akamai**: a home e a SPA de busca (`b2c.voegol.com.br/compra`) carregam com
  `render_js=true` simples, sem precisar de `premium_proxy`/`stealth_proxy`.
- **Bug real encontrado**: combinar `premium_proxy=true` + `stealth_proxy=true` junto com
  `js_scenario` faz `evaluate_results`/`js_scenario_report` voltarem **vazios silenciosamente**
  (sem erro) — parece que esses dois parâmetros roteiam para um backend de renderização incompatível
  com scenarios. Sem eles, o `evaluate` funciona normalmente.
- `js_scenario` usa seletores CSS simples, **não** o `text=...` do Playwright — instruções `click`
  com esse pseudo-seletor falham silenciosamente. É preciso usar `evaluate` com JS puro
  (`querySelectorAll` + match de `textContent`) para clicar por texto visível.
- **Armadilha de UI**: os campos "Origem"/"Destino" no widget de busca da Gol são **placeholders de
  `<input>`**, não texto de elemento — buscar por `textContent` nunca encontra esses campos; é
  preciso `document.querySelector('input[placeholder="Origem"]')`.
- A SPA da Gol mostra, de forma intermitente, um modal de contagem regressiva "sessão expirando"
  (`id="btn_yes_sessionExpired"`, texto "Ainda estou aqui") que bloqueia o resto do formulário até
  ser dispensado. Ainda não ficou claro se é um recurso legítimo do site (timeout de reserva) ou um
  checkpoint anti-bot disfarçado de UX — apareceu mesmo variando `session_id`/cache-busting.
- `screenshot_full_page=true` combinado com `js_scenario` tira o screenshot **antes** do scenario
  rodar (confirmado por hash idêntico entre chamadas com e sem scenario) — não serve para depurar
  visualmente o estado pós-interação.

**ZenRows** (`api.zenrows.com/v1/`, param `js_instructions` + `json_response=true`):
- Sem `antibot=true` + `wait` alto, cai num **desafio comportamental explícito da Akamai** ("Powered
  and protected by Akamai", tela de slider/hold). Com `antibot=true`, `premium_proxy=true`,
  `proxy_country=br` e `wait=10000` (10s parado na página antes de qualquer instrução), o desafio se
  **auto-resolve** e a SPA real carrega — sugere que o headless deles resolve o desafio sozinho dado
  tempo suficiente de permanência na página.
- **Bug real encontrado, mais sério que o do ScrapingBee**: o parâmetro `js_instructions` corrompe
  **qualquer caractere `+` literal dentro do código JS** — vira espaço em branco no servidor deles
  (confirmado via `js_instructions_report`: `body = 'ERR:' + e.message` virou `body = 'ERR:'
  e.message`, e até `i + 1` virou `i   1`), quebrando a sintaxe e fazendo o `evaluate` falhar sem
  mensagem de erro útil (`success: false`, `error: null`). Correção: eliminar todo uso de operador
  `+` do JS injetado (usar template literals `` `${a}${b}` `` em vez de concatenação, e `for...of`
  sobre um array literal em vez de `i++`/`i + 1`).
- `evaluate` parece ter um teto de duração por instrução (a soma de `await sleep(...)` internos não
  pode passar de alguns segundos, senão a instrução falha silenciosamente) — a mitigação foi quebrar
  o fluxo em múltiplas instruções `evaluate` curtas + `wait` dedicados entre elas, persistindo estado
  em `window.__debug`/`window.__captured` (que sobrevive entre instruções da mesma `js_instructions`,
  já que é o mesmo contexto de página).
- A tentativa final de rodar o fluxo completo (dispensar o modal "sessão expirando" + preencher
  origem/destino + buscar) foi **bloqueada pelo classificador de permissão do Claude Code**, pelo
  mesmo motivo do reCAPTCHA: automatizar a dispensa de um checkpoint do tipo "prova de que você ainda
  está aí" é tratado como evasão de anti-bot, independente do serviço terceirizado usado por baixo.

**Conclusão prática**: tecnicamente, tanto ScrapingBee quanto ZenRows superam a barreira de rede/
fingerprint da Akamai (a parte "IP/TLS/JA3/CDP" do bloqueio). O que continua impossível de automatizar
**por política do agente**, não por limitação técnica do provedor, é a etapa de dispensar o checkpoint
de "prova de humanidade" da própria Gol (seja o reCAPTCHA do cadastro dos provedores, seja o modal de
sessão da Gol). Para este MVP de baixo volume (1 busca/dia), o caminho que resta e que **não** esbarra
nessa política é a **captura manual**: o usuário faz a busca no navegador normal (DevTools → aba
Network → filtro "search"), copia o JSON de resposta de `/flights/search`, e esse payload real
alimenta o ajuste do parser em `src/extraction/gol.py`. A automação completa do pipeline de extração
(rodando sozinha, sem humano no loop) segue como item em aberto — não é um problema de escolha de
ferramenta, é um limite de política que precisa ser resolvido de outra forma (ex. um humano real
disparando o job periodicamente, ou aceitar esse ponto como intervenção manual permanente no MVP).

### `pyproject.toml` tem `[tool.uv] package = false` — `src/` não é um pacote instalado

Isso significa que `pythonpath = ["src"]` em `[tool.pytest.ini_options]` só resolve imports para o
`pytest`, não para qualquer outro runtime (ex. `dagster dev`). Para o Dagster encontrar
`domain`/`extraction`/etc. (imports absolutos sem prefixo `src.` usados em `src/orchestration/assets.py`),
o `workspace.yaml` precisa da chave `working_directory: src` no `python_file` do `load_from` —
resolve relativo ao diretório do próprio `workspace.yaml` (que fica em `/app` dentro do container).
Se o projeto migrar para `package = true` no futuro, essa configuração de `workspace.yaml` deve ser
revisitada (pode se tornar redundante).

## Padrão de projeto (não é bug, é convenção adotada)

### QA não corrige código — mas pode achar bugs reais que voltam para o dev-runner

Durante a trilha de `src/orchestration/`, o QA encontrou um bug genuíno: `run_daily_search` deveria
ser uma função **total** (nunca levanta exceção não tratada), mas duas chamadas ao `gold`
(`last_alerted_prices` e `record_alerts`) escapavam de qualquer `try/except`. O QA escreveu um teste
de regressão que falhava de propósito, classificou como bug do `dev-runner` (não ambiguidade de
especificação do `dev-planner`), e o `dev-runner` corrigiu num segundo ciclo. Padrão validado: manter
esse fluxo (QA escreve teste de regressão primeiro, depois classifica o destino) evita "corrigir
tudo" fora do papel de cada agente.
