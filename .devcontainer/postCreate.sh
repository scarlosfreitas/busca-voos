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

echo "postCreate: concluído."
