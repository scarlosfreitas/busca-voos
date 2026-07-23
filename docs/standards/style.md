# Padrões de estilo e linting

> **Engenharia e código** (o "como" do estilo). Regras de formatação, nomeação e linting que o
> código gerado deve obedecer.

## Idioma e convenções gerais

- Português é o idioma padrão de documentação e commits (ver `.claude/PRD.md` §8).
- Locale UTF-8 (`LANG`/`LC_ALL=C.UTF-8`) — preserve acentuação (`ç`, `'`).

## Estilo de código

_(Linter/formatter adotado, largura de linha, convenções de nomeação, imports, etc.)_

## Scripts shell

- `set -euo pipefail` e padrão `-y`/`--force` para pular confirmações (ver `scripts/clean.sh`).
