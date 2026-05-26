#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${PROJECT_DIR}/docker-compose.engine.yml"
ENV_FILE="${PROJECT_DIR}/.env"
ENV_EXAMPLE_FILE="${PROJECT_DIR}/.env.example"
INSTALL_SYSTEMD="false"
MODE="auto"
SERVICE_NAME="azurcrm-prospecting-engine"
PID_FILE="${PROJECT_DIR}/.engine.pid"

print_help() {
  cat <<'EOF'
Uso:
  ./scripts/install_linux.sh [--mode auto|docker|native] [--with-systemd]

Opciones:
  --mode <modo>    auto (default), docker, native.
  --with-systemd   Instala y habilita un servicio systemd para autoarranque.
  -h, --help       Muestra esta ayuda.

Que hace:
  1) Crea .env desde .env.example si no existe.
  2) Modo docker: levanta engine con Docker Compose.
  3) Modo native: instala venv + dependencias y ejecuta uvicorn.
  4) Opcional: instala servicio systemd para iniciar en boot.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      if [[ $# -lt 2 ]]; then
        echo "Error: --mode requiere un valor." >&2
        exit 1
      fi
      MODE="$2"
      shift 2
      ;;
    --with-systemd)
      INSTALL_SYSTEMD="true"
      shift
      ;;
    -h|--help)
      print_help
      exit 0
      ;;
    *)
      echo "Argumento no soportado: $1" >&2
      print_help
      exit 1
      ;;
  esac
done

if [[ "${MODE}" != "auto" && "${MODE}" != "docker" && "${MODE}" != "native" ]]; then
  echo "Error: modo invalido '${MODE}'. Usa auto, docker o native." >&2
  exit 1
fi

detect_mode() {
  if [[ "${MODE}" != "auto" ]]; then
    printf '%s\n' "${MODE}"
    return
  fi

  if command -v docker >/dev/null 2>&1; then
    printf '%s\n' "docker"
  else
    printf '%s\n' "native"
  fi
}

prepare_env_file() {
  if [[ ! -f "${ENV_FILE}" ]]; then
    if [[ -f "${ENV_EXAMPLE_FILE}" ]]; then
      cp "${ENV_EXAMPLE_FILE}" "${ENV_FILE}"
      echo "Creado .env desde .env.example."
    else
      echo "Aviso: no existe .env ni .env.example; continuando sin EnvironmentFile."
    fi
  fi
}

start_native_service() {
  if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 no esta instalado." >&2
    exit 1
  fi

  # Debian/Ubuntu often ship python3 without venv/ensurepip by default.
  if ! python3 -c "import ensurepip" >/dev/null 2>&1; then
    if command -v apt-get >/dev/null 2>&1; then
      if [[ "${EUID}" -eq 0 ]]; then
        echo "Instalando dependencias Python (python3-venv, python3-pip)..."
        apt-get update
        apt-get install -y python3-venv python3-pip
      else
        echo "Error: falta soporte venv en python3. Ejecuta como root o instala: apt-get install python3-venv python3-pip" >&2
        exit 1
      fi
    else
      echo "Error: python3 no tiene soporte venv (ensurepip). Instala python3-venv y python3-pip con el gestor de paquetes del sistema." >&2
      exit 1
    fi
  fi

  cd "${PROJECT_DIR}"
  python3 -m venv .venv
  "${PROJECT_DIR}/.venv/bin/pip" install --upgrade pip
  "${PROJECT_DIR}/.venv/bin/pip" install -r requirements.txt

  if [[ -f "${PID_FILE}" ]] && kill -0 "$(cat "${PID_FILE}")" >/dev/null 2>&1; then
    echo "Deteniendo proceso previo del engine (PID $(cat "${PID_FILE}"))."
    kill "$(cat "${PID_FILE}")" || true
  fi

  set -a
  [[ -f "${ENV_FILE}" ]] && . "${ENV_FILE}"
  set +a

  nohup "${PROJECT_DIR}/.venv/bin/uvicorn" app.main:app --host 0.0.0.0 --port 8090 > "${PROJECT_DIR}/engine.log" 2>&1 &
  echo "$!" > "${PID_FILE}"
  echo "Engine iniciado en modo native (PID $!)."
}

install_systemd_native() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "Error: --with-systemd requiere ejecutar como root (sudo)." >&2
    exit 1
  fi

  local service_file="/etc/systemd/system/${SERVICE_NAME}.service"

  cat > "${service_file}" <<EOF
[Unit]
Description=AzurCRM Prospecting Engine (Native Python)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${PROJECT_DIR}
EnvironmentFile=-${ENV_FILE}
ExecStart=${PROJECT_DIR}/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8090
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable --now "${SERVICE_NAME}.service"
  echo "Servicio systemd habilitado: ${SERVICE_NAME}.service"
}

install_systemd_docker() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "Error: --with-systemd requiere ejecutar como root (sudo)." >&2
    exit 1
  fi

  local docker_bin
  docker_bin="$(command -v docker)"
  local service_file="/etc/systemd/system/${SERVICE_NAME}.service"

  cat > "${service_file}" <<EOF
[Unit]
Description=AzurCRM Prospecting Engine (Docker Compose)
Requires=docker.service
After=docker.service network-online.target

[Service]
Type=oneshot
WorkingDirectory=${PROJECT_DIR}
RemainAfterExit=yes
ExecStart=${docker_bin} compose -f ${COMPOSE_FILE} up -d --build
ExecStop=${docker_bin} compose -f ${COMPOSE_FILE} down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable --now "${SERVICE_NAME}.service"
  echo "Servicio systemd habilitado: ${SERVICE_NAME}.service"
}

SELECTED_MODE="$(detect_mode)"
echo "Modo seleccionado: ${SELECTED_MODE}"

cd "${PROJECT_DIR}"
prepare_env_file

if [[ "${SELECTED_MODE}" == "docker" ]]; then
  if ! command -v docker >/dev/null 2>&1; then
    echo "Error: docker no esta instalado o no esta en PATH." >&2
    exit 1
  fi
  if [[ ! -f "${COMPOSE_FILE}" ]]; then
    echo "Error: no se encontro ${COMPOSE_FILE}." >&2
    exit 1
  fi

  echo "Levantando servicio con Docker Compose..."
  docker compose -f "${COMPOSE_FILE}" up -d --build

  if [[ "${INSTALL_SYSTEMD}" == "true" ]]; then
    install_systemd_docker
  fi
else
  echo "Instalando y levantando servicio en modo native (sin Docker)..."
  start_native_service

  if [[ "${INSTALL_SYSTEMD}" == "true" ]]; then
    install_systemd_native
  fi
fi

echo "Engine instalado y ejecutandose."
echo "URL esperada: http://localhost:8090"
