# syntax=docker/dockerfile:1
# Imagem base oficial da Microsoft com browsers + libs de SO do Playwright (PRD §6).
# ATENÇÃO: a tag DEVE casar com a versão de 'playwright' no pyproject.toml (ver D3).
FROM mcr.microsoft.com/playwright/python:v1.55.0-noble

# Gerenciador de dependências uv (architecture.md §4)
COPY --from=ghcr.io/astral-sh/uv:0.9.9 /uv /uvx /bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DAGSTER_HOME=/opt/dagster/dagster_home

WORKDIR /app

# Camada de dependências (cache eficiente): copia só os manifestos primeiro.
COPY pyproject.toml ./
# Usa uv.lock se existir (build reprodutível); senão resolve na hora (bootstrap).
COPY uv.loc[k] ./
RUN if [ -f uv.lock ]; then uv sync --frozen --no-install-project; \
    else uv sync --no-install-project; fi

# Código da aplicação
COPY src/ ./src/
COPY workspace.yaml ./

RUN mkdir -p /opt/dagster/dagster_home

EXPOSE 3000
# Sobe daemon + UI do Dagster (logs visíveis na UI, architecture.md §4).
# 'dagster dev' é adequado para o deploy LOCAL do MVP; produção separaria
# webserver/daemon (ver D4).
CMD ["uv", "run", "dagster", "dev", "-w", "workspace.yaml", "-h", "0.0.0.0", "-p", "3000"]
