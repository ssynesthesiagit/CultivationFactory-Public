#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
APP_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd -P)"
REPO_ROOT="$(cd -- "${APP_ROOT}/.." && pwd -P)"
VENV_DIR="${TIANXIA_VENV_DIR:-${REPO_ROOT}/.venv}"
PYTHON_VERSION="${TIANXIA_PYTHON_VERSION:-3.12}"
STATE_HOME="${XDG_STATE_HOME:-${HOME}/.local/state}"
CONFIG_HOME="${XDG_CONFIG_HOME:-${HOME}/.config}"
DATA_ROOT="${TIANXIA_FOUNDRY_DATA:-${STATE_HOME}/cultivation-factory}"
SECURITY_ROOT="${TIANXIA_FOUNDRY_SECURITY_DIR:-${DATA_ROOT}/security}"
INSTALL_SERVICE=false
CHECK_ONLY=false
SKIP_BOOTSTRAP=false

usage() {
  cat <<'EOF'
Usage: install-omarchy.sh [--check] [--systemd-user] [--skip-bootstrap]

  --check           Verify host tools and repository artifacts without writing.
  --systemd-user    Install (but do not start) a systemd user service.
  --skip-bootstrap  Install dependencies without initializing persistent Factory data.
EOF
}

while (($#)); do
  case "$1" in
    --check) CHECK_ONLY=true ;;
    --systemd-user) INSTALL_SERVICE=true ;;
    --skip-bootstrap) SKIP_BOOTSTRAP=true ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

if ((EUID == 0)); then
  printf 'Run this installer as the owner user, not root.\n' >&2
  exit 2
fi

required_files=(
  "${APP_ROOT}/requirements/requirements.txt"
  "${APP_ROOT}/BundledContent/Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip"
  "${APP_ROOT}/BundledContent/Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip.sha256"
  "${APP_ROOT}/gm_screen/HF05ZUI_R2K3_HF3_W1_CoreStats_GMScreen.zip"
  "${APP_ROOT}/gm_screen/HF05ZUI_R2K3_HF3_W1_CoreStats_GMScreen.zip.sha256"
  "${SCRIPT_DIR}/run-factory.sh"
  "${SCRIPT_DIR}/cultivation-factory.service.in"
)
for path in "${required_files[@]}"; do
  [[ -f "${path}" ]] || { printf 'Required installation artifact is missing: %s\n' "${path}" >&2; exit 3; }
done

for command_name in git sha256sum; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    printf 'Missing required host command: %s\n' "${command_name}" >&2
    printf 'On Omarchy, install packages with the Omarchy package menu or omarchy pkg add.\n' >&2
    exit 3
  }
done

(cd -- "${APP_ROOT}/BundledContent" && sha256sum --check --status Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip.sha256)
(cd -- "${APP_ROOT}/gm_screen" && sha256sum --check --status HF05ZUI_R2K3_HF3_W1_CoreStats_GMScreen.zip.sha256)

browser=""
for candidate in chromium google-chrome-stable google-chrome chrome; do
  if command -v "${candidate}" >/dev/null 2>&1; then
    browser="$(command -v "${candidate}")"
    break
  fi
done
if [[ -z "${browser}" ]]; then
  printf 'Chromium/Chrome is required for exact Character Sheet consumer verification.\n' >&2
  printf 'Omarchy normally includes Chromium; otherwise run: omarchy pkg add chromium\n' >&2
  exit 3
fi

if ! command -v uv >/dev/null 2>&1; then
  printf 'uv is required to install the pinned private Python environment.\n' >&2
  printf 'Install it from the Omarchy package menu or run: omarchy pkg add uv\n' >&2
  exit 3
fi

if ${CHECK_ONLY}; then
  printf 'Omarchy prerequisites: PASS\n'
  printf 'Repository artifacts: PASS\n'
  printf 'Browser: %s\n' "${browser}"
  printf 'Persistent data root: %s\n' "${DATA_ROOT}"
  exit 0
fi

uv python install "${PYTHON_VERSION}"
uv venv --python "${PYTHON_VERSION}" "${VENV_DIR}"
uv pip install --python "${VENV_DIR}/bin/python" -r "${APP_ROOT}/requirements/requirements.txt"

mkdir -p -- "${DATA_ROOT}" "${SECURITY_ROOT}" "${DATA_ROOT}/logs"
chmod 700 -- "${DATA_ROOT}" "${SECURITY_ROOT}"

if ! ${SKIP_BOOTSTRAP}; then
  report="${DATA_ROOT}/logs/omarchy-install-bootstrap.json"
  (
    cd -- "${APP_ROOT}"
    TIANXIA_FOUNDRY_DATA="${DATA_ROOT}" \
    TIANXIA_FOUNDRY_SECURITY_DIR="${SECURITY_ROOT}" \
    TIANXIA_BROWSER_EXECUTABLE="${browser}" \
    "${VENV_DIR}/bin/python" -c \
      'import json; from pathlib import Path; from app.core import Settings; from product_bootstrap import ProductBootstrapService; result=ProductBootstrapService(Settings.from_env()).run(); Path("'"${report}"'").write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8"); print(result["status"])'
  )
fi

if ${INSTALL_SERVICE}; then
  service_dir="${CONFIG_HOME}/systemd/user"
  service_path="${service_dir}/cultivation-factory.service"
  mkdir -p -- "${service_dir}"
  escaped_repo=${REPO_ROOT//&/\\&}
  sed "s&@REPO_ROOT@&${escaped_repo}&g" "${SCRIPT_DIR}/cultivation-factory.service.in" > "${service_path}"
  systemctl --user daemon-reload
  printf 'Installed user service: %s\n' "${service_path}"
  printf 'Start it with: systemctl --user start cultivation-factory\n'
fi

printf 'CultivationFactory Omarchy installation: PASS\n'
printf 'Launch: %s --open-browser\n' "${SCRIPT_DIR}/run-factory.sh"
printf 'Persistent data root: %s\n' "${DATA_ROOT}"
