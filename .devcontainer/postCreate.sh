#!/usr/bin/env bash
set -euo pipefail

# Executado automaticamente pelo Dev Containers logo após a criação do
# container (ver "postCreateCommand" em devcontainer.json). Use este arquivo
# para instalações/configurações que devem acontecer sempre que o container
# for (re)criado.
#
# O bloco entre os marcadores abaixo é preenchido automaticamente pelo
# install.sh/install.ps1 com os plugins que você escolher instalar durante o
# bootstrap do projeto (ver scripts/plugins.sh para o catálogo completo).
# Não remova os marcadores — eles são o ponto de inserção do instalador.

echo "postCreate: iniciando setup do container..."

# >>> devc-debian-claude: plugins selecionados (gerado por install.sh/install.ps1) >>>
# Instalação selecionada durante o bootstrap:
# claude plugin install context7@claude-plugins-official --scope user
# claude plugin marketplace add mksglu/context-mode
# claude plugin install context-mode@context-mode --scope user
# <<< devc-debian-claude: plugins selecionados <<<

# --- Credenciais git via token (regenerado a cada recriação do container) ----
# /workspace (com .env e .git/config) é bind mount do host e sobrevive a
# rebuilds; /home/app é filesystem do container e é descartado a cada rebuild.
# credential.helper=store já está configurado em /workspace/.git/config (persiste),
# mas o arquivo ~/.git-credentials com o token em si precisa ser recriado aqui.
if [ -f /workspace/.env ]; then
    set -a
    # shellcheck disable=SC1091
    source /workspace/.env
    set +a
    if [ -n "${GIT_USERNAME:-}" ] && [ -n "${GIT_TOKKEN:-}" ]; then
        echo "postCreate: configurando credenciais git via token..."
        # url-encode mínimo (usuário costuma ser um e-mail, com '@'/':'/'%')
        enc_user="${GIT_USERNAME//%/%25}"
        enc_user="${enc_user//@/%40}"
        enc_user="${enc_user//:/%3A}"
        enc_token="${GIT_TOKKEN//%/%25}"
        printf 'https://%s:%s@github.com\n' "$enc_user" "$enc_token" > ~/.git-credentials
        chmod 600 ~/.git-credentials
    else
        echo "postCreate: GIT_USERNAME/GIT_TOKKEN não definidos em .env, pulando credenciais git."
    fi
fi

echo "postCreate: concluído."
