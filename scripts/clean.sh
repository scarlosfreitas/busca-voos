#!/usr/bin/env bash
set -euo pipefail

# Remove containers e volumes do devcontainer deste projeto.
#
# O container tem nome fixo (CONTAINER_NAME em .env, usado como container_name
# no docker-compose.yml), então buscamos por esse nome exato. Sem .env (ex.:
# projetos antigos deste template), caímos no padrão "<pasta>_devcontainer..."
# que a extensão Dev Containers do VS Code gerava por conta própria.
#
# Volumes como claude-code-config-<devcontainerId> são criados pela extensão
# Dev Containers via "mounts" do devcontainer.json, fora do compose, e não
# seguem nome previsível — por isso descobrimos os volumes inspecionando os
# mounts reais do(s) container(s) encontrado(s), em vez de tentar casar nomes.
#
# O volume "vscode" (montado em /vscode) é injetado automaticamente pela
# extensão Dev Containers para cachear o VS Code Server, e é compartilhado
# entre TODOS os devcontainers da máquina — nunca deve ser removido aqui.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

CONTAINER_NAME=""
if [[ -f "$SCRIPT_DIR/.env" ]]; then
  CONTAINER_NAME="$(grep -E '^CONTAINER_NAME=' "$SCRIPT_DIR/.env" | tail -1 | cut -d= -f2-)"
fi

FORCE=false
if [[ "${1:-}" == "-y" || "${1:-}" == "--force" ]]; then
  FORCE=true
fi

if [[ -n "$CONTAINER_NAME" ]]; then
  SEARCH_LABEL="$CONTAINER_NAME"
  mapfile -t CONTAINERS < <(docker ps -a --filter "name=^${CONTAINER_NAME}$" --format '{{.Names}}')
else
  SEARCH_LABEL="$(basename "$PROJECT_DIR")_devcontainer"
  mapfile -t CONTAINERS < <(docker ps -a --filter "name=^${SEARCH_LABEL}" --format '{{.Names}}')
fi

VOLUMES=()
for c in "${CONTAINERS[@]:-}"; do
  [[ -z "$c" ]] && continue
  while IFS= read -r v; do
    [[ -n "$v" && "$v" != "vscode" ]] && VOLUMES+=("$v")
  done < <(docker inspect "$c" --format '{{ range .Mounts }}{{ if eq .Type "volume" }}{{ .Name }}{{ "\n" }}{{ end }}{{ end }}')
done
if [[ ${#VOLUMES[@]} -gt 0 ]]; then
  mapfile -t VOLUMES < <(printf '%s\n' "${VOLUMES[@]}" | sort -u)
fi

if [[ ${#CONTAINERS[@]} -eq 0 && ${#VOLUMES[@]} -eq 0 ]]; then
  echo "Nada para remover (busca: ${SEARCH_LABEL})."
  exit 0
fi

echo "Serão removidos:"
for c in "${CONTAINERS[@]:-}"; do [[ -n "$c" ]] && echo "  container: $c"; done
for v in "${VOLUMES[@]:-}"; do [[ -n "$v" ]] && echo "  volume:    $v"; done

if [[ "$FORCE" != true ]]; then
  read -r -p "Confirma a remoção? [y/N] " reply
  [[ "$reply" =~ ^[Yy]$ ]] || { echo "Cancelado."; exit 1; }
fi

for c in "${CONTAINERS[@]:-}"; do
  [[ -n "$c" ]] && docker rm -f "$c"
done
for v in "${VOLUMES[@]:-}"; do
  [[ -n "$v" ]] && docker volume rm "$v"
done

echo "Concluído."
