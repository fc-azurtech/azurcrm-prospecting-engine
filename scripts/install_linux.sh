#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${PROJECT_DIR}/docker-compose.engine.yml"
ENV_FILE="${PROJECT_DIR}/.env"
ENV_EXAMPLE_FILE="${PROJECT_DIR}/.env.example"
INSTALL_SYSTEMD="false"
SERVICE_NAME="azurcrm-prospecting-engine"

print_help() {
  cat <<'EOF'
Uso:
  ./scripts/install_linux.sh [--with-systemd]

Opciones:
  --with-systemd   Instala y habilita un servicio systemd para autoarranque.
  -h, --help       Muestra esta ayuda.

Que hace:
  1) Crea .env desde .env.example si no existe.
  2) Levanta el engine con Docker Compose (build incluido).
  3) Opcional: instala servicio systemd para iniciar en boot.
EOF
}

for arg in "$@"; do
  case "${arg}" in
    --with-systemd)
      INSTALL_SYSTEMD="true"
      ;;
    -h|--help)
      print_help
      exit 0
      ;;
    *)
      echo "Argumento no soportado: ${arg}" >&2
      print_help
      exit 1
      ;;
  esac
done

if ! command -v docker >/dev/null 2>&1; then
  echo "Error: docker no esta instalado o no esta en PATH." >&2
  exit 1
fi

cd "${PROJECT_DIR}"

if [[ ! -f "${COMPOSE_FILE}" ]]; then
  echo "Error: no se encontro ${COMPOSE_FILE}." >&2
  exit 1
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  if [[ -f "${ENV_EXAMPLE_FILE}" ]]; then
    cp "${ENV_EXAMPLE_FILE}" "${ENV_FILE}"
    echo "Creado .env desde .env.example."
  else
    echo "Aviso: no existe .env ni .env.example; se usaran defaults del compose."
  fi
fi

echo "Levantando servicio con Docker Compose..."
docker compose -f "${COMPOSE_FILE}" up -d --build

echo "Engine instalado y ejecutandose."
echo "URL esperada: http://localhost:8090"

if [[ "${INSTALL_SYSTEMD}" == "true" ]]; then
  if [[ "${EUID}" -ne 0 ]]; then
    echo "Error: --with-systemd requiere ejecutar como root (sudo)." >&2
    exit 1
  fi

  DOCKER_BIN="$(command -v docker)"
  SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

  cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=AzurCRM Prospecting Engine (Docker Compose)
Requires=docker.service
After=docker.service network-online.target

[Service]
Type=oneshot
WorkingDirectory=${PROJECT_DIR}
RemainAfterExit=yes
ExecStart=${DOCKER_BIN} compose -f ${COMPOSE_FILE} up -d --build
ExecStop=${DOCKER_BIN} compose -f ${COMPOSE_FILE} down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable --now "${SERVICE_NAME}.service"
  echo "Servicio systemd habilitado: ${SERVICE_NAME}.service"
fi
