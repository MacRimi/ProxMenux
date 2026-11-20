#!/bin/bash
# Shared, content-addressed NVIDIA mount hook installation. No guest lifecycle.
lxc_install_nvidia_hook() {
  local source=$1 expected=$2 directory=${3:-/usr/local/lib/proxmenux/oci}
  local path component current='' stage actual
  local -a components=()
  [[ $expected =~ ^[0-9a-f]{64}$ && -f $source && ! -L $source ]] || return 1
  [[ $(sha256sum "$source" | cut -d ' ' -f1) == "$expected" ]] || return 1
  [[ $directory == /* && $directory != *'..'* ]] || return 1
  IFS=/ read -ra components <<<"$directory"
  for component in "${components[@]}"; do
    [[ -n $component ]] || continue
    current="$current/$component"
    [[ ! -L $current ]] || return 1
    if [[ -e $current ]]; then
      [[ -d $current && $(stat -c '%u' "$current") == 0 ]] || return 1
      actual=$(stat -c '%a' "$current")
      (( (8#$actual & 0022) == 0 )) || return 1
    else
      install -d -m 0755 "$current" || return 1
    fi
  done
  path="$directory/nvidia-mount-$expected.sh"
  if [[ -e $path || -L $path ]]; then
    [[ ! -L $path && -f $path && $(stat -c '%u' "$path") == 0 ]] || return 1
    actual=$(stat -c '%a' "$path")
    (( (8#$actual & 0022) == 0 )) && [[ -x $path ]] || return 1
    [[ $(sha256sum "$path" | cut -d ' ' -f1) == "$expected" ]] || return 1
  else
    stage=$(mktemp "$directory/.nvidia-hook.XXXXXX") || return 1
    if ! install -m 0755 "$source" "$stage"; then rm -f "$stage"; return 1; fi
    # Publish without replacing another process's hook or a symlink.
    if ! ln "$stage" "$path"; then rm -f "$stage"; return 1; fi
    rm -f "$stage"
  fi
  printf '%s\n' "$path"
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
  [[ $# == 3 && $1 == --install-hook ]] || exit 1
  lxc_install_nvidia_hook "$2" "$3"
fi
