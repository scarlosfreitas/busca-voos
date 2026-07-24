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
