# Padrões de Arquitetura de Software e Dados

> Referência de **como construir**. O `.claude/PRD.md` define o quê e o porquê; o
> `docs/domain/regras_negocio.md` define as regras de negócio; este arquivo define os padrões
> técnicos que o código deve seguir para que diferentes agentes/sessões produzam um sistema
> coerente.

## 1. Visão Geral da Arquitetura

Pipeline batch diário, sem servidor web, orquestrado pelo Dagster:

```
Dagster (schedule diário)
   └─▶ Job de extração
         ├─▶ Playwright (+ stealth) acessa o site da Gol e intercepta a resposta de rede
         ├─▶ Persiste raw no PostgreSQL (schema bronze)
         ├─▶ Transforma e normaliza (schema silver)
         ├─▶ Avalia elegibilidade + deduplicação (schema gold)
         └─▶ Se houver voo elegível novo/alterado → Telegram
             Se a execução falhar → Telegram (notificação de erro)
```

Não há API HTTP nem frontend no MVP. Toda a superfície de execução é o job agendado.

## 2. Estrutura de Módulos (`src/`)

Segue a separação definida em `.claude/PRD.md` (seção 9): `domain/` para regras de negócio,
`utils/` para infraestrutura técnica. Módulos concretos propostos:

```
src/
├── domain/            # Entidades e regras (o que está em docs/domain/regras_negocio.md, em código)
│   ├── models.py       # Flight, Route, Alert — dataclasses/pydantic models
│   ├── eligibility.py   # Regra de Elegibilidade
│   └── deduplication.py # Regra de Deduplicação
├── extraction/         # Camada de scraping
│   ├── browser.py       # Setup do Playwright + stealth
│   └── gol.py            # Navegação e interceptação específicas da Gol
├── persistence/        # Acesso a dados (bronze/silver/gold no Postgres)
│   ├── db.py             # Conexão/engine
│   └── repositories.py   # Leitura/escrita por camada
├── notification/       # Integração Telegram
│   └── telegram.py
├── orchestration/      # Assets e jobs do Dagster
│   └── assets.py
└── utils/              # Helpers técnicos sem regra de negócio (retry, logging, config)
```

- **`domain/` não importa de `extraction/`, `persistence/` ou `notification/`** — regra de negócio
  não conhece detalhe de infraestrutura. A dependência é sempre de fora para dentro.
- Toda regra descrita em `docs/domain/regras_negocio.md` deve ter um módulo/função correspondente
  em `src/domain/`, rastreável 1:1.

## 3. Padrão de Dados — Arquitetura Medallion no PostgreSQL

Como definido no PRD, não há DuckDB/Iceberg: as camadas Bronze/Silver/Gold são **schemas do
Postgres**, não arquivos.

| Schema | Conteúdo | Mutabilidade |
| :--- | :--- | :--- |
| `bronze` | Payload JSON bruto interceptado, como veio da Gol, + metadados de execução (timestamp, rota, sucesso/falha). | Append-only, nunca editado. |
| `silver` | Voos normalizados: tipos corretos, preço em decimal, datas/horas tipadas. | Derivado do bronze; pode ser reprocessado. |
| `gold` | Resultado da avaliação de negócio: elegibilidade + deduplicação + histórico de "último preço alertado". | Derivado do silver; base para notificação. |

Convenções:
- Nomes de tabela em `snake_case`, no singular por entidade (ex: `bronze.raw_search_response`,
  `silver.flight`, `gold.flight_alert`).
- Toda tabela de bronze/silver carrega `execution_id` (FK lógica para a execução do job) e
  `captured_at` (timestamp UTC).
- Nenhum dado é deletado (retenção indefinida, conforme PRD) — não há jobs de purge.

## 4. Ferramental Python

- **Gerenciador de dependências/ambiente:** `uv`. Todo o projeto usa `pyproject.toml` +
  lockfile (`uv.lock`); não misturar com `pip install` manual ou `requirements.txt` solto.
- **Lint e formatação:** `ruff` (lint + format), substituindo a necessidade de black/flake8/isort
  separados. Deve rodar em `scripts/test.sh` ou equivalente antes dos testes.
- **Migrations de banco:** `alembic`, versionando incrementalmente as tabelas de todos os schemas
  (bronze/silver/gold). Nenhuma tabela é criada via `create_all` automático em produção — toda
  mudança de schema passa por uma migration versionada.
- **Logging:** usar o sistema de logging/eventos nativo do Dagster (`context.log` dentro de
  ops/assets), sem biblioteca de logging adicional. Isso mantém os logs de execução visíveis
  diretamente na UI do Dagster, que já é a ferramenta de acompanhamento do pipeline.

## 5. Configuração e Segredos

- Nenhuma credencial, token ou string de conexão em código-fonte.
- Todas as variáveis sensíveis (token do bot Telegram, chat_id, string de conexão Postgres, dados
  de proxy) vêm de variáveis de ambiente carregadas via `.env` (não commitado) em desenvolvimento,
  e devem migrar para um secret manager ao ir para produção em nuvem.
- Parâmetros de negócio versionáveis (rota monitorada, data de ida) ficam em configuração
  explícita no código/config file — não são segredo, mas também não devem ser *hardcoded* em
  múltiplos lugares (uma única fonte de verdade de configuração).

## 6. Tratamento de Erros e Resiliência

- Toda falha de extração (bloqueio, CAPTCHA, timeout, exceção) deve ser capturada no nível do
  job/asset do Dagster, registrada em log estruturado e propagada para a notificação de erro via
  Telegram — nunca deve derrubar o processo silenciosamente.
- Timeouts de rede/página seguem o PRD (5+ minutos) para tolerar lentidão sem falso-positivo de
  falha.
- Erros de negócio (ex: payload sem campo obrigatório) são diferentes de erros de infraestrutura
  (ex: timeout de rede) e devem ser logados com níveis/tags distintos para facilitar diagnóstico.

## 7. Containerização

- Um único `docker-compose.yml` (em `.devcontainer/` ou raiz, conforme convenção do projeto) sobe
  no mínimo dois serviços: a aplicação (imagem baseada em
  `mcr.microsoft.com/playwright/python`) e o PostgreSQL.
- A aplicação nunca acessa Postgres fora do container/rede definida no compose — sem
  `localhost` hardcoded, sempre via variável de ambiente com o nome do serviço.

## 8. Testes

- Testes vivem em `test/`, espelhando a estrutura de `src/` (ex: `test/domain/test_eligibility.py`
  para `src/domain/eligibility.py`).
- Regras de negócio (`src/domain/`) devem ter cobertura de teste unitário para cada caso descrito
  em `docs/domain/regras_negocio.md`, incluindo os casos de borda.
- Integração com Playwright/Telegram/Postgres é testada separadamente (testes de integração), não
  misturada com testes unitários de regra de negócio.
