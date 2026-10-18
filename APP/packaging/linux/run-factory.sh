#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
APP_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd -P)"
REPO_ROOT="$(cd -- "${APP_ROOT}/.." && pwd -P)"
VENV_DIR="${TIANXIA_VENV_DIR:-${REPO_ROOT}/.venv}"
PYTHON="${VENV_DIR}/bin/python"
STATE_HOME="${XDG_STATE_HOME:-${HOME}/.local/state}"
DATA_ROOT="${TIANXIA_FOUNDRY_DATA:-${STATE_HOME}/cultivation-factory}"
SECURITY_ROOT="${TIANXIA_FOUNDRY_SECURITY_DIR:-${DATA_ROOT}/security}"
PORT="${TIANXIA_FACTORY_PORT:-8765}"

if [[ ! -x "${PYTHON}" ]]; then
  printf 'CultivationFactory virtual environment is missing: %s\n' "${PYTHON}" >&2
  printf 'Run %s/install-omarchy.sh first.\n' "${SCRIPT_DIR}" >&2
  exit 2
fi

mkdir -p -- "${DATA_ROOT}" "${SECURITY_ROOT}"
chmod 700 -- "${DATA_ROOT}" "${SECURITY_ROOT}"

export TIANXIA_FOUNDRY_DATA="${DATA_ROOT}"
export TIANXIA_FOUNDRY_SECURITY_DIR="${SECURITY_ROOT}"

# Scratch compiles and the clean-import proof stage a copy of the data root
# under TMPDIR.  The default /tmp is a RAM-backed tmpfs whose pages are
# charged to this service's memory cgroup, so keep scratch on disk.  The path
# must stay short: the GM Screen consumer's Chromium creates a Unix socket
# under TMPDIR and Linux limits socket paths to 107 bytes.
SCRATCH_ROOT="${TIANXIA_SCRATCH_TMPDIR:-/var/tmp/cf}"
mkdir -p -- "${SCRATCH_ROOT}"
chmod 700 -- "${SCRATCH_ROOT}"
export TMPDIR="${SCRATCH_ROOT}"

# Fill the Character Sheets / character library list caches in the background at
# startup (APP/app/api.py), so the first visit after a restart is not a long wait.
export TIANXIA_WARM_LIST_CACHES="${TIANXIA_WARM_LIST_CACHES:-1}"

if [[ -z "${TIANXIA_BROWSER_EXECUTABLE:-}" ]]; then
  for browser in chromium google-chrome-stable google-chrome chrome; do
    if command -v "${browser}" >/dev/null 2>&1; then
      export TIANXIA_BROWSER_EXECUTABLE="$(command -v "${browser}")"
      break
    fi
  done
fi

has_port=false
has_data_root=false
for argument in "$@"; do
  [[ "${argument}" == "--port" || "${argument}" == --port=* ]] && has_port=true
  [[ "${argument}" == "--data-dir" || "${argument}" == "--data-root" || "${argument}" == --data-dir=* || "${argument}" == --data-root=* ]] && has_data_root=true
done

arguments=(--host 127.0.0.1)
${has_port} || arguments+=(--port "${PORT}")
${has_data_root} || arguments+=(--data-dir "${DATA_ROOT}")
arguments+=("$@")

cd -- "${APP_ROOT}"
exec "${PYTHON}" -m app.main "${arguments[@]}"
