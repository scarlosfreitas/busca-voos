# Infra de DESENVOLVIMENTO (o Dockerfile/compose de produção virão na raiz).
# Imagem base derivada de Debian, enxuta e estável.
FROM debian:bookworm-slim

# --- Pacotes do sistema -------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        git \
        gnupg \
        sudo \
        zip \
        unzip \
        xz-utils \
    && rm -rf /var/lib/apt/lists/*

# --- Node.js (LTS) + npm -------------------------------------------------------
RUN curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# --- Google Chrome (automação de navegador, ex.: agent-browser) ---------------
RUN curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
        | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
        > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# --- uv (gerenciador de dependências/ambiente Python do projeto) --------------
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# --- Usuário não-root (UID/GID 1000, casa com o fallback do docker-compose) ---
RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash app \
    && echo "app ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/app \
    && chmod 0440 /etc/sudoers.d/app

# Pré-cria o diretório de config do Claude Code com dono correto: quando o
# devcontainer monta um volume nomeado vazio em /home/app/.claude pela
# primeira vez, o Docker copia o conteúdo/dono deste diretório da imagem
# para o volume. Sem isso, o ponto de montagem é criado como root e o
# usuário app fica sem permissão de escrita.
RUN mkdir -p /home/app/.claude && chown -R app:app /home/app/.claude

# Volta para o usuário padrão não-root do container por segurança
USER app

WORKDIR /workspace

