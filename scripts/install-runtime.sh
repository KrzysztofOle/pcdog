#!/usr/bin/env bash
# Install and reconcile the minimal systemd-managed PcDog runtime.

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
project_dir="$(cd -- "$script_dir/.." && pwd -P)"
# shellcheck source=common.sh
source "$script_dir/common.sh"

readonly RUNTIME_USER='pcdog'
readonly RUNTIME_GROUP='pcdog'
readonly RUNTIME_DIRECTORY='/opt/pcdog'
readonly RUNTIME_BINARY="$RUNTIME_DIRECTORY/bin/pcdog-runtime"
readonly HEALTH_CHECK_BINARY="$RUNTIME_DIRECTORY/bin/pcdog-healthcheck"
readonly RUNTIME_LIBRARY_DIRECTORY="$RUNTIME_DIRECTORY/lib"
readonly RUNTIME_PACKAGE_DIRECTORY="$RUNTIME_LIBRARY_DIRECTORY/pcdog_runtime"
readonly RUNTIME_WEB_PANEL_DIRECTORY="$RUNTIME_PACKAGE_DIRECTORY/web_panel"
readonly RUNTIME_DATA_DIRECTORY='/var/lib/pcdog-runtime'
readonly SERVICE_NAME='pcdog.service'
readonly SERVICE_PATH="/etc/systemd/system/$SERVICE_NAME"
readonly RUNTIME_SOURCE="$project_dir/runtime/pcdog-runtime.sh"
readonly HEALTH_CHECK_SOURCE="$project_dir/runtime/pcdog-healthcheck.sh"
readonly SERVICE_SOURCE="$project_dir/systemd/$SERVICE_NAME"
readonly PYTHON_PACKAGE_SOURCE="$project_dir/pcdog_runtime"
readonly -a PYTHON_PACKAGE_FILES=(
  '__init__.py'
  'event_store.py'
  'input_monitor.py'
  'inputs.py'
  'models.py'
  'read_only_runtime.py'
  'state_engine.py'
  'web_api.py'
  'web_panel/index.html'
  'web_panel/pcdog-panel.css'
  'web_panel/pcdog-panel.js'
)

usage() {
  cat <<'EOF'
Użycie: ./scripts/install-runtime.sh [--check]

Instaluje minimalny runtime PcDog i usługę systemd.
--check wyłącznie sprawdza instalację oraz health check.
EOF
}

check_only=false
if [[ $# -gt 1 ]]; then
  usage >&2
  exit 2
elif [[ $# -eq 1 ]]; then
  [[ "$1" = '--check' ]] || { usage >&2; exit 2; }
  check_only=true
fi

runtime_user_is_safe() {
  local passwd_entry user_name user_id group_id home_directory login_shell

  passwd_entry="$(getent passwd "$RUNTIME_USER")" || return 1
  IFS=: read -r user_name _ user_id group_id _ home_directory login_shell <<<"$passwd_entry"

  [[ "$user_name" = "$RUNTIME_USER" ]] || return 1
  [[ "$user_id" =~ ^[0-9]+$ && "$user_id" -lt 1000 ]] || return 1
  [[ "$group_id" =~ ^[0-9]+$ ]] || return 1
  [[ "$home_directory" = '/nonexistent' ]] || return 1
  [[ "$login_shell" = '/usr/sbin/nologin' ]] || return 1
  getent group "$RUNTIME_GROUP" >/dev/null
}

runtime_user_has_no_gpio_access() {
  ! id --groups --name "$RUNTIME_USER" | tr ' ' '\n' | grep --fixed-strings --quiet 'gpio'
}

file_matches() {
  local source_path="$1"
  local target_path="$2"
  local expected_mode="$3"
  local actual_metadata

  [[ -f "$target_path" ]] || return 1
  cmp --silent "$source_path" "$target_path" || return 1
  actual_metadata="$(stat --format='%u:%g:%a' "$target_path")"
  [[ "$actual_metadata" = "0:0:${expected_mode}" ]]
}

runtime_layout_is_correct() {
  local directory_metadata
  local relative_path

  [[ -d "$RUNTIME_DIRECTORY" && -d "$RUNTIME_DIRECTORY/bin" && -d "$RUNTIME_LIBRARY_DIRECTORY" && -d "$RUNTIME_PACKAGE_DIRECTORY" && -d "$RUNTIME_WEB_PANEL_DIRECTORY" ]] || return 1
  directory_metadata="$(stat --format='%u:%g:%a' "$RUNTIME_DIRECTORY" "$RUNTIME_DIRECTORY/bin" "$RUNTIME_LIBRARY_DIRECTORY" "$RUNTIME_PACKAGE_DIRECTORY" "$RUNTIME_WEB_PANEL_DIRECTORY")"
  [[ "$directory_metadata" = $'0:0:755\n0:0:755\n0:0:755\n0:0:755\n0:0:755' ]] || return 1
  file_matches "$RUNTIME_SOURCE" "$RUNTIME_BINARY" 755 || return 1
  file_matches "$HEALTH_CHECK_SOURCE" "$HEALTH_CHECK_BINARY" 755 || return 1
  file_matches "$SERVICE_SOURCE" "$SERVICE_PATH" 644 || return 1
  for relative_path in "${PYTHON_PACKAGE_FILES[@]}"; do
    file_matches "$PYTHON_PACKAGE_SOURCE/$relative_path" "$RUNTIME_PACKAGE_DIRECTORY/$relative_path" 644 || return 1
  done
  [[ "$(stat --format='%U:%G:%a' "$RUNTIME_DATA_DIRECTORY")" = 'pcdog:pcdog:750' ]]
}

if "$check_only"; then
  require_command systemctl
  require_command getent

  runtime_user_is_safe || die "Użytkownik ${RUNTIME_USER} nie spełnia wymagań runtime."
  runtime_user_has_no_gpio_access || die "Użytkownik ${RUNTIME_USER} nie może należeć do grupy gpio."
  runtime_layout_is_correct || die 'Pliki runtime lub jednostka systemd nie odpowiadają wersji repozytorium.'
  systemctl is-enabled --quiet "$SERVICE_NAME" || die "Usługa ${SERVICE_NAME} nie jest włączona."
  systemctl is-active --quiet "$SERVICE_NAME" || die "Usługa ${SERVICE_NAME} nie jest aktywna."
  "$script_dir/health-check.sh"
  log_success 'Runtime PcDog i usługa systemd są poprawnie zainstalowane.'
  exit 0
fi

require_root
require_command cmp
require_command getent
require_command install
require_command systemctl
require_command useradd

if getent passwd "$RUNTIME_USER" >/dev/null; then
  runtime_user_is_safe || die "Istniejący użytkownik ${RUNTIME_USER} nie jest bezpiecznym użytkownikiem systemowym PcDog."
  runtime_user_has_no_gpio_access || die "Istniejący użytkownik ${RUNTIME_USER} należy do niedozwolonej grupy gpio."
else
  log_info "Tworzenie użytkownika systemowego ${RUNTIME_USER} bez dostępu do GPIO."
  if getent group "$RUNTIME_GROUP" >/dev/null; then
    useradd --system --gid "$RUNTIME_GROUP" --home-dir /nonexistent --shell /usr/sbin/nologin "$RUNTIME_USER"
  else
    useradd --system --user-group --home-dir /nonexistent --shell /usr/sbin/nologin "$RUNTIME_USER"
  fi
fi

log_info "Przygotowanie katalogu runtime ${RUNTIME_DIRECTORY}."
install --directory --owner=root --group=root --mode=755 \
  "$RUNTIME_DIRECTORY" \
  "$RUNTIME_DIRECTORY/bin" \
  "$RUNTIME_LIBRARY_DIRECTORY" \
  "$RUNTIME_PACKAGE_DIRECTORY" \
  "$RUNTIME_WEB_PANEL_DIRECTORY"

install_if_changed() {
  local source_path="$1"
  local target_path="$2"
  local file_mode="$3"

  if file_matches "$source_path" "$target_path" "$file_mode"; then
    return 1
  fi

  install --owner=root --group=root --mode="$file_mode" "$source_path" "$target_path"
  return 0
}

wait_for_healthy_runtime() {
  local attempt

  for attempt in {1..10}; do
    if "$script_dir/health-check.sh" >/dev/null 2>&1; then
      "$script_dir/health-check.sh"
      return 0
    fi
    sleep 1
  done

  "$script_dir/health-check.sh"
}

runtime_changed=false
unit_changed=false

if install_if_changed "$RUNTIME_SOURCE" "$RUNTIME_BINARY" 755; then
  runtime_changed=true
fi
if install_if_changed "$HEALTH_CHECK_SOURCE" "$HEALTH_CHECK_BINARY" 755; then
  runtime_changed=true
fi
for relative_path in "${PYTHON_PACKAGE_FILES[@]}"; do
  if install_if_changed "$PYTHON_PACKAGE_SOURCE/$relative_path" "$RUNTIME_PACKAGE_DIRECTORY/$relative_path" 644; then
    runtime_changed=true
  fi
done
if install_if_changed "$SERVICE_SOURCE" "$SERVICE_PATH" 644; then
  unit_changed=true
fi

if "$unit_changed"; then
  log_info "Przeładowanie konfiguracji systemd po zmianie ${SERVICE_NAME}."
  systemctl daemon-reload
fi

if ! systemctl is-enabled --quiet "$SERVICE_NAME"; then
  log_info "Włączanie ${SERVICE_NAME} do autostartu."
  systemctl enable "$SERVICE_NAME"
fi

if ! systemctl is-active --quiet "$SERVICE_NAME"; then
  log_info "Uruchamianie ${SERVICE_NAME}."
  systemctl start "$SERVICE_NAME"
elif "$runtime_changed" || "$unit_changed"; then
  log_info "Restart ${SERVICE_NAME} po zmianie plików runtime."
  systemctl restart "$SERVICE_NAME"
else
  log_info "${SERVICE_NAME} jest już aktywna; restart nie jest potrzebny."
fi

wait_for_healthy_runtime
runtime_data_layout_is_correct() {
  [[ -d "$RUNTIME_DATA_DIRECTORY" ]] || return 1
  [[ "$(stat --format='%U:%G:%a' "$RUNTIME_DATA_DIRECTORY")" = 'pcdog:pcdog:750' ]]
}

runtime_data_layout_is_correct || die "Katalog danych ${RUNTIME_DATA_DIRECTORY} nie ma oczekiwanych uprawnień."
log_success 'Runtime PcDog i usługa systemd są gotowe.'
