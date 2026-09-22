#!/usr/bin/env bash
# Helpers shared by the OCI installers: the look of the ProxMenux utils.sh
# messages, the same translation cache and the private log of each run.
# Safe under set -Eeuo pipefail.

PMX_BASE_DIR=${PMX_BASE_DIR:-/usr/local/share/proxmenux}
OCI_LOG_DIR=${OCI_LOG_DIR:-/var/log/proxmenux/oci}
OCI_LOG=${OCI_LOG:-}

_OCI_LANGUAGE=$(jq -r '.language // "en"' "$PMX_BASE_DIR/config.json" 2>/dev/null || true)
[[ -n $_OCI_LANGUAGE && $_OCI_LANGUAGE != null ]] || _OCI_LANGUAGE=en
_OCI_LANG_FILE="$PMX_BASE_DIR/lang/${_OCI_LANGUAGE}.json"

_OCI_MG=$'\033[1;35m'
_OCI_GN=$'\033[1;92m'
_OCI_RD=$'\033[01;31m'
_OCI_YW=$'\033[33m'
_OCI_YWB=$'\033[1;33m'
_OCI_BOLD=$'\033[1m'
_OCI_CL=$'\033[m'
_OCI_TAB="    "
_OCI_SPINNER_PID=""

translate() {
  if [[ $_OCI_LANGUAGE == en || ! -s $_OCI_LANG_FILE ]]; then
    printf '%s' "$1"
    return 0
  fi
  local value
  value=$(jq -r --arg text "$1" '.[$text] // empty' "$_OCI_LANG_FILE" 2>/dev/null || true)
  printf '%s' "${value:-$1}"
}

_oci_spinner() {
  local frames=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏') i=0
  printf '\033[?25l'
  while :; do
    printf '\r %s%s%s' "$_OCI_MG" "${frames[i]}" "$_OCI_CL"
    i=$(( (i + 1) % ${#frames[@]} ))
    sleep 0.1
  done
}

stop_spinner() {
  if [[ -n $_OCI_SPINNER_PID ]]; then
    kill "$_OCI_SPINNER_PID" 2>/dev/null || true
    wait "$_OCI_SPINNER_PID" 2>/dev/null || true
    _OCI_SPINNER_PID=""
  fi
  printf '\033[?25h'
}

# The spinner is shown when the caller's terminal is interactive; OCI_SPINNER=1
# is set by the Python front end, which relays this output to a terminal.
msg_info() {
  stop_spinner
  printf '\r\033[K%s%s-%s%s' "$_OCI_TAB" "$_OCI_MG" "$1" "$_OCI_CL"
  if [[ -t 1 || ${OCI_SPINNER:-0} == 1 ]]; then
    _oci_spinner &
    _OCI_SPINNER_PID=$!
  else
    printf '\n'
  fi
}

# One line rewritten in place, for progress counters (no spinner).
msg_progress() {
  stop_spinner
  printf '\r\033[K%s%s-%s%s' "$_OCI_TAB" "$_OCI_MG" "$1" "$_OCI_CL"
}

msg_ok() {
  stop_spinner
  printf '\r\033[K%s%s✓ %s%s%s%s\n' "$_OCI_TAB" "$_OCI_GN" "$_OCI_CL" "$_OCI_GN" "$1" "$_OCI_CL"
}

msg_warn() {
  stop_spinner
  printf '\r\033[K%s%s %s%s%s\n' "$_OCI_TAB" "$_OCI_CL" "$_OCI_YWB" "$1" "$_OCI_CL"
}

msg_error() {
  stop_spinner
  printf '\r\033[K%s%s[ERROR] %s%s\n' "$_OCI_TAB" "$_OCI_RD" "$1" "$_OCI_CL"
}

msg_info2() {
  stop_spinner
  printf '\r\033[K%s%s%s- %s%s\n' "$_OCI_TAB" "$_OCI_BOLD" "$_OCI_YW" "$1" "$_OCI_CL"
}

# Starts the private log of one run; every quiet command writes into it.
oci_log_init() {
  local name=${1:-oci}
  [[ -n $OCI_LOG ]] && return 0
  mkdir -p "$OCI_LOG_DIR"
  chmod 0700 "$OCI_LOG_DIR" 2>/dev/null || true
  OCI_LOG="$OCI_LOG_DIR/${name//[^A-Za-z0-9._-]/_}-$(date +%Y%m%d-%H%M%S).log"
  : >"$OCI_LOG"
  chmod 0600 "$OCI_LOG"
  export OCI_LOG
}

oci_log() {
  [[ -n $OCI_LOG ]] && printf '%s\n' "$*" >>"$OCI_LOG"
  return 0
}

# Runs a command with its output in the log instead of the terminal.
oci_quiet() {
  if [[ -n $OCI_LOG ]]; then
    "$@" >>"$OCI_LOG" 2>&1
  else
    "$@" >/dev/null 2>&1
  fi
}

# Last lines of the log, for the error report.
oci_log_tail() {
  [[ -n $OCI_LOG && -s $OCI_LOG ]] || return 0
  tail -n "${1:-15}" "$OCI_LOG" | sed "s/^/${_OCI_TAB}  /"
}

# ip= and gw= options of an access interface, DHCP or a static IPv4 with an
# optional gateway, in OCI_ACCESS_NET. Returns 1 when a value is not valid.
oci_access_net() {
  local octet='(25[0-5]|2[0-4][0-9]|1?[0-9]?[0-9])'
  OCI_ACCESS_NET=""
  if [[ $1 == dhcp ]]; then
    OCI_ACCESS_NET="ip=dhcp"
    return 0
  fi
  [[ $1 =~ ^($octet\.){3}$octet/([89]|[12][0-9]|3[0-2])$ ]] || return 1
  [[ -z ${2:-} || $2 =~ ^($octet\.){3}$octet$ ]] || return 1
  OCI_ACCESS_NET="ip=$1${2:+,gw=$2}"
}
