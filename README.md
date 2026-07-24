# busca-voos

Aplicação assíncrona de monitoramento diário de preços de passagens aéreas (pagantes) e emissões
por milhas, com alertas curados via Telegram. No MVP: monitora a rota Macapá (MCP) → Brasília
(BSB), ida em 01/09/2026, na Gol.

## Status do projeto

O projeto está na fase de **planejamento fechado, sem código de aplicação ainda**. Antes de
qualquer contribuição, leia [`/STATUS.md`](./STATUS.md) — ele descreve o que já foi feito e qual é
a próxima prioridade.

## Documentação

| Arquivo | Conteúdo |
| :--- | :--- |
| [`STATUS.md`](./STATUS.md) | Estado atual do projeto e próxima prioridade — leitura obrigatória antes de qualquer tarefa. |
| [`CLAUDE.md`](./CLAUDE.md) | Fluxo de trabalho e roteamento de contexto para agentes de IA. |
| [`.claude/PRD.md`](./.claude/PRD.md) | O quê e o porquê: escopo do MVP, arquitetura recomendada, critérios de aceite. |
| [`docs/domain/regras_negocio.md`](./docs/domain/regras_negocio.md) | Fonte única da verdade das regras de negócio (elegibilidade, deduplicação, notificação). |
| [`docs/standards/architecture.md`](./docs/standards/architecture.md) | Padrões técnicos: estrutura de `src/`, schemas Postgres, ferramental, testes. |
| [`.claude/agents/`](./.claude/agents/) | Definição do time de subagentes (planejadores e executores, dev e infra, QA). |

## Stack técnica

- **Linguagem:** Python
- **Extração:** Playwright (+ `playwright-stealth`), interceptação de rede (XHR/Fetch)
- **Orquestração:** Dagster (job diário)
- **Banco de dados:** PostgreSQL (schemas `bronze`/`silver`/`gold`, arquitetura Medallion)
- **Mensageria:** API de Bots do Telegram
- **Infraestrutura:** Docker / `docker-compose`

## Ambiente de desenvolvimento

Este projeto usa um devcontainer Debian com Claude Code pré-instalado.

1. Abra a pasta no VS Code.
2. `Ctrl+Shift+P` → **Dev Containers: Reopen in Container**.
3. Faça login no Claude Code (no chat e no terminal).

O `docker-compose.yml` da aplicação (serviços `app` + `postgres`) ainda não existe — é a próxima
prioridade de infraestrutura registrada em `STATUS.md`.

Gerado a partir do template [devc-debian-claude](https://github.com/scarlosfreitas/devc-debian-claude).
