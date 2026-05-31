#!/bin/bash

# ==========================================================
# ProxMenux - Proxmox VE Helper Scripts Browser
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : GPL-3.0
#               https://github.com/MacRimi/ProxMenux/blob/main/LICENSE
# Version     : 1.3
# ==========================================================
# Description:
# Front-end for the community-scripts/ProxmoxVE catalog
# (https://community-scripts.github.io/ProxmoxVE/) —
# the spiritual continuation of tteck's helper scripts.
#
# Loads a curated JSON cache (helpers_cache.json) maintained
# by ProxMenux on GitHub, lists categories + scripts with
# search and type filters, and executes the chosen script
# via "bash <(curl -s <url>)".
#
# Features:
# - Browse scripts by category (Container, OS, Network, …).
# - Free-text search across name and description.
# - Per-script details: description, notes, default credentials,
#   default port, website.
# - Choice of source (GitHub or Mirror) per script.
# - Type labels: LXC / VM / PVE / ADDON / TK / GEN.
#
# Requires: curl, jq, dialog. Internet access mandatory.
# ==========================================================


# Configuration ============================================
LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"
VENV_PATH="/opt/googletrans-env"

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi

load_language
initialize_cache
# ==========================================================

# New unified cache — categories and mirror URLs are embedded,
# metadata.json is no longer needed.
HELPERS_JSON_URL="https://raw.githubusercontent.com/MacRimi/ProxMenux/refs/heads/main/json/helpers_cache.json"

for cmd in curl jq dialog; do
  if ! command -v "$cmd" >/dev/null; then
    echo "Missing required command: $cmd"
    exit 1
  fi
done

# `--connect-timeout` caps DNS+TCP setup; `--max-time` caps total fetch.
# Without these the menu would hang silently for minutes when the network
# is down or the upstream is slow, with no signal to the user. Audit
# Tier 6 — `menu_Helper_Scripts.sh` curl sin --max-time.
CACHE_JSON=$(curl -s --connect-timeout 5 --max-time 15 "$HELPERS_JSON_URL")

# Validate that the JSON loaded correctly
if ! echo "$CACHE_JSON" | jq -e 'if type == "array" and length > 0 then true else false end' >/dev/null 2>&1; then
  dialog --title "Helper Scripts" \
    --msgbox "Error: Could not load helpers cache.\nCheck your internet connection and try again.\n\nURL: $HELPERS_JSON_URL" 10 70
  exec bash "$LOCAL_SCRIPTS/menus/main_menu.sh"
fi

# ---------------------------------------------------------------------------
# Build category map directly from the cache (id → name).
# Uses transpose to pair categories[] and category_names[] arrays — no
# dependency on metadata.json, which no longer exists upstream.
# ---------------------------------------------------------------------------
declare -A CATEGORY_NAMES
while IFS=$'\t' read -r id name; do
  [[ -n "$id" && -n "$name" ]] && CATEGORY_NAMES["$id"]="$name"
done < <(echo "$CACHE_JSON" | jq -r '
  [.[] | [.categories, .category_names] | transpose[] | @tsv]
  | unique[]')

# Count scripts per category (deduplicated by slug)
declare -A CATEGORY_COUNT
while read -r id; do
  ((CATEGORY_COUNT[$id]++))
done < <(echo "$CACHE_JSON" | jq -r '
  group_by(.slug) | map(.[0])[] | .categories[]')

# ---------------------------------------------------------------------------
# Type label — updated to match new type values (lxc instead of ct)
# ---------------------------------------------------------------------------
get_type_label() {
  local type="$1"
  case "$type" in
    lxc)     echo $'\Z1LXC\Zn' ;;
    vm)      echo $'\Z4VM\Zn' ;;
    pve)     echo $'\Z3PVE\Zn' ;;
    addon)   echo $'\Z2ADDON\Zn' ;;
    turnkey) echo $'\Z5TK\Zn' ;;
    *)       echo $'\Z7GEN\Zn' ;;
  esac
}

# ---------------------------------------------------------------------------
# Download and execute a script URL, with optional mirror fallback
# ---------------------------------------------------------------------------
download_script() {
  local url="$1"

  # Same timeouts as the cache fetch above so a stalled mirror can't hang
  # the menu indefinitely. The HEAD probe and the GET both get bounded.
  if curl --silent --connect-timeout 5 --max-time 10 --head --fail "$url" >/dev/null; then
    bash <(curl -s --connect-timeout 5 --max-time 60 "$url")
  else
    dialog --title "Helper Scripts" --msgbox "$(translate "Error: Failed to download the script.")" 8 70
  fi
}

RETURN_TO_MAIN=false

# ---------------------------------------------------------------------------
# Format default credentials for display
# ---------------------------------------------------------------------------
format_credentials() {
  local script_info="$1"
  local credentials_info=""

  local has_credentials
  has_credentials=$(echo "$script_info" | base64 --decode | jq -r 'has("default_credentials")')

  if [[ "$has_credentials" == "true" ]]; then
    local username password
    username=$(echo "$script_info" | base64 --decode | jq -r '.default_credentials.username // empty')
    password=$(echo "$script_info" | base64 --decode | jq -r '.default_credentials.password // empty')

    if [[ -n "$username" && -n "$password" ]]; then
      credentials_info="Username: $username | Password: $password"
    elif [[ -n "$username" ]]; then
      credentials_info="Username: $username"
    elif [[ -n "$password" ]]; then
      credentials_info="Password: $password"
    fi
  fi

  echo "$credentials_info"
}

# ---------------------------------------------------------------------------
# Run a script identified by its slug.
#
# A slug can have multiple entries when a script supports several OS variants
# (e.g. Debian + Alpine). Each entry carries its own script_url / mirror and
# the os field already normalised to lowercase by generate_helpers_cache.py.
# The menu lets the user pick OS variant × source (GitHub / Mirror).
# ---------------------------------------------------------------------------
run_script_by_slug() {
  local slug="$1"
  local -a script_infos
  mapfile -t script_infos < <(echo "$CACHE_JSON" | jq -r --arg slug "$slug" \
    '.[] | select(.slug == $slug) | @base64')

  if [[ ${#script_infos[@]} -eq 0 ]]; then
    dialog --title "Helper Scripts" \
      --msgbox "$(translate "Error: No script data found for slug:") $slug" 8 60
    return
  fi

  decode() { echo "$1" | base64 --decode | jq -r "$2"; }

  local first="${script_infos[0]}"
  local name desc notes warnings port website
  name=$(decode "$first" ".name")
  desc=$(decode "$first" ".desc")
  notes=$(decode "$first" '.notes // [] | join("\n")')
  # Sprint 11.7: PocketBase upstream tags certain notes with type=="warning".
  # The cache generator splits them into a separate `warnings` array so the
  # menu can render them in red with a dedicated WARNINGS header instead of
  # burying them inside the regular notes block.
  warnings=$(decode "$first" '.warnings // [] | join("\n")')
  port=$(decode "$first" ".port // 0")
  website=$(decode "$first" ".website // empty")

  local credentials
  credentials=$(format_credentials "$first")

  # Build info message — warnings first, in red, so the user sees them
  # before deciding to launch the script. Sections are separated by a
  # single \n (one blank line) instead of \n\n; the bullet builders below
  # also strip their trailing \n so we don't double up. Helper Scripts
  # like "PVE LXC Apps Update" carry a lot of text and a fixed-height
  # dialog clips the bottom menu when each section eats two extra rows.
  local msg="\Zb\Z4$(translate "Description"):\Zn\n$desc"
  if [[ -n "$warnings" ]]; then
    local warn_short=""
    local char_count=0
    local max_chars=400
    while IFS= read -r line; do
      [[ -z "$line" ]] && continue
      char_count=$(( char_count + ${#line} ))
      if [[ $char_count -lt $max_chars ]]; then
        warn_short+="• $line\n"
      else
        warn_short+="...\n"
        break
      fi
    done <<< "$warnings"
    warn_short="${warn_short%\\n}"
    msg+="\n\Zb\Z1⚠ $(translate "Warnings"):\Zn\n\Z1${warn_short}\Zn"
  fi
  if [[ -n "$notes" ]]; then
    local notes_short=""
    local char_count=0
    local max_chars=400
    while IFS= read -r line; do
      [[ -z "$line" ]] && continue
      char_count=$(( char_count + ${#line} ))
      if [[ $char_count -lt $max_chars ]]; then
        notes_short+="• $line\n"
      else
        notes_short+="...\n"
        break
      fi
    done <<< "$notes"
    notes_short="${notes_short%\\n}"
    msg+="\n\Zb\Z4$(translate "Notes"):\Zn\n$notes_short"
  fi
  [[ -n "$credentials" ]] && msg+="\n\Zb\Z4$(translate "Default Credentials"):\Zn\n$credentials"
  [[ "$port" -gt 0 ]] && msg+="\n\Zb\Z4$(translate "Default Port"):\Zn $port"
  [[ -n "$website" ]] && msg+="\n\Zb\Z4$(translate "Website"):\Zn $website"

  msg+="\n$(translate "Choose how to run the script:")"

  # Build menu: one or two entries per script_info (GH + optional Mirror)
  declare -a MENU_OPTS=()
  local idx=0
  for s in "${script_infos[@]}"; do
    local os script_url script_url_mirror script_name
    os=$(decode "$s" '.os // empty')
    [[ -z "$os" ]] && os="$(translate "default")"
    script_name=$(decode "$s" ".name")
    script_url=$(decode "$s" ".script_url")
    script_url_mirror=$(decode "$s" ".script_url_mirror // empty")

    MENU_OPTS+=("${idx}_GH" "$os | $script_name | GitHub")

    if [[ -n "$script_url_mirror" ]]; then
      MENU_OPTS+=("${idx}_MR" "$os | $script_name | Mirror")
    fi

    ((idx++))
  done

  local choice
  choice=$(dialog --clear --colors --backtitle "ProxMenux" \
           --title "$name" \
           --menu "$msg" 28 80 6 \
           "${MENU_OPTS[@]}" 3>&1 1>&2 2>&3)

  if [[ $? -ne 0 || -z "$choice" ]]; then
    RETURN_TO_MAIN=false
    return
  fi

  local sel_idx sel_src
  IFS="_" read -r sel_idx sel_src <<< "$choice"

  local selected="${script_infos[$sel_idx]}"
  local gh_url mirror_url
  gh_url=$(decode "$selected" ".script_url")
  mirror_url=$(decode "$selected" ".script_url_mirror // empty")

  if [[ "$sel_src" == "GH" ]]; then
    download_script "$gh_url"
  elif [[ "$sel_src" == "MR" ]]; then
    if [[ -n "$mirror_url" ]]; then
      download_script "$mirror_url"
    else
      dialog --title "Helper Scripts" \
        --msgbox "$(translate "Mirror URL not available for this script.")" 8 60
      RETURN_TO_MAIN=false
      return
    fi
  fi

  echo
  echo

  if [[ -n "$desc" || -n "$notes" || -n "$warnings" || -n "$credentials" ]]; then
    echo -e "$TAB\e[1;36m$(translate "Script Information"):\e[0m"

    if [[ -n "$warnings" ]]; then
      echo -e "$TAB\e[1;31m⚠ $(translate "Warnings"):\e[0m"
      while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        echo -e "$TAB\e[31m• $line\e[0m"
      done <<< "$warnings"
      echo
    fi

    if [[ -n "$notes" ]]; then
      echo -e "$TAB\e[1;33m$(translate "Notes"):\e[0m"
      while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        echo -e "$TAB• $line"
      done <<< "$notes"
      echo
    fi

    if [[ -n "$credentials" ]]; then
      echo -e "$TAB\e[1;32m$(translate "Default Credentials"):\e[0m"
      echo "$TAB$credentials"
      echo
    fi
  fi

  msg_success "$(translate "Press Enter to return to the main menu...")"
  read -r
  RETURN_TO_MAIN=true
}

# ---------------------------------------------------------------------------
# Search / filter scripts by name or description
# ---------------------------------------------------------------------------
search_and_filter_scripts() {
  local search_term=""

  while true; do
    search_term=$(dialog --inputbox \
      "$(translate "Enter search term (leave empty to show all scripts):"):" \
      8 65 "$search_term" 3>&1 1>&2 2>&3)

    [[ $? -ne 0 ]] && return

    local filtered_json
    if [[ -z "$search_term" ]]; then
      filtered_json="$CACHE_JSON"
    else
      local search_lower
      search_lower=$(echo "$search_term" | tr '[:upper:]' '[:lower:]')
      filtered_json=$(echo "$CACHE_JSON" | jq --arg term "$search_lower" '
        [.[] | select(
          (.name | ascii_downcase | contains($term)) or
          (.desc | ascii_downcase | contains($term))
        )]')
    fi

    local count
    count=$(echo "$filtered_json" | jq 'group_by(.slug) | length')

    if [[ "$count" -eq 0 ]]; then
      dialog --msgbox \
        "$(translate "No scripts found for:") '$search_term'\n\n$(translate "Try a different search term.")" \
        8 50
      continue
    fi

    while true; do
      declare -A index_to_slug
      local menu_items=()
      local i=1

      while IFS=$'\t' read -r slug name type; do
        index_to_slug[$i]="$slug"
        local label
        label=$(get_type_label "$type")
        local padded_name
        padded_name=$(printf "%-42s" "$name")
        menu_items+=("$i" "$padded_name $label")
        ((i++))
      done < <(echo "$filtered_json" | jq -r '
        group_by(.slug) | map(.[0]) | sort_by(.name)[]
        | [.slug, .name, .type] | @tsv')

      menu_items+=("" "")
      menu_items+=("new_search" "$(translate "New Search")")
      menu_items+=("show_all"   "$(translate "Show All Scripts")")

      local title
      if [[ -n "$search_term" ]]; then
        title="$(translate "Search Results for:") '$search_term' ($count $(translate "found"))"
      else
        title="$(translate "All Available Scripts") ($count $(translate "total"))"
      fi

      local selected
      selected=$(dialog --colors --backtitle "ProxMenux" \
                 --title "$title" \
                 --menu "$(translate "Select a script or action:"):" \
                 22 75 15 "${menu_items[@]}" 3>&1 1>&2 2>&3)

      [[ $? -ne 0 ]] && return

      case "$selected" in
        "new_search")
          break
          ;;
        "show_all")
          search_term=""
          filtered_json="$CACHE_JSON"
          count=$(echo "$filtered_json" | jq 'group_by(.slug) | length')
          continue
          ;;
        "back"|"")
          return
          ;;
        *)
          if [[ -n "${index_to_slug[$selected]}" ]]; then
            run_script_by_slug "${index_to_slug[$selected]}"
            [[ "$RETURN_TO_MAIN" == true ]] && { RETURN_TO_MAIN=false; return; }
          fi
          ;;
      esac
    done
  done
}

# ---------------------------------------------------------------------------
# Main loop — category list built from embedded category data.
# We map scriptcatXXXXX IDs to short numeric indices so dialog doesn't show
# the long ID string as the visible tag in the menu column.
# ---------------------------------------------------------------------------
while true; do
  MENU_ITEMS=()
  MENU_ITEMS+=("search" "$(translate "Search/Filter Scripts")")
  MENU_ITEMS+=("" "")

  # Map scriptcatXXXXX IDs to short numeric indices (1, 2, 3…) so dialog
  # doesn't render the long ID string as the visible tag column.
  declare -A CAT_IDX_TO_ID
  local_idx=1
  for id in $(printf "%s\n" "${!CATEGORY_COUNT[@]}" | sort); do
    CAT_IDX_TO_ID[$local_idx]="$id"
    name="${CATEGORY_NAMES[$id]:-Category $id}"
    count="${CATEGORY_COUNT[$id]}"
    padded_name=$(printf "%-35s" "$name")
    padded_count=$(printf "(%2d)" "$count")
    MENU_ITEMS+=("$local_idx" "$padded_name $padded_count")
    ((local_idx++))
  done

  SELECTED_IDX=$(dialog --backtitle "ProxMenux" \
    --title "Proxmox VE Helper-Scripts" \
    --menu "$(translate "Select a category or search for scripts:"):" \
    22 75 15 "${MENU_ITEMS[@]}" 3>&1 1>&2 2>&3) || {
      dialog --clear --title "ProxMenux" \
        --msgbox "\n\n$(translate "Visit the website to discover more scripts, stay updated with the latest updates, and support the project:")\n\nhttps://community-scripts.github.io/ProxmoxVE" 15 70
      exec bash "$LOCAL_SCRIPTS/menus/main_menu.sh"
  }

  if [[ "$SELECTED_IDX" == "search" ]]; then
    search_and_filter_scripts
    continue
  fi

  # Resolve numeric index back to the real category ID
  SELECTED="${CAT_IDX_TO_ID[$SELECTED_IDX]}"
  [[ -z "$SELECTED" ]] && continue

  # ---- Scripts within the selected category --------------------------------
  while true; do
    declare -A INDEX_TO_SLUG
    SCRIPTS=()
    i=1

    while IFS=$'\t' read -r slug name type; do
      INDEX_TO_SLUG[$i]="$slug"
      label=$(get_type_label "$type")
      padded_name=$(printf "%-42s" "$name")
      SCRIPTS+=("$i" "$padded_name $label")
      ((i++))
    done < <(echo "$CACHE_JSON" | jq -r --arg id "$SELECTED" '
      [
        .[]
        | select(.categories | index($id))
        | {slug, name, type}
      ]
      | group_by(.slug)
      | map(.[0])
      | sort_by(.name)[]
      | [.slug, .name, .type]
      | @tsv')

    SCRIPT_INDEX=$(dialog --colors --backtitle "ProxMenux" \
      --title "$(translate "Scripts in") ${CATEGORY_NAMES[$SELECTED]}" \
      --menu "$(translate "Choose a script to execute:"):" \
      22 75 15 "${SCRIPTS[@]}" 3>&1 1>&2 2>&3) || break

    SCRIPT_SELECTED="${INDEX_TO_SLUG[$SCRIPT_INDEX]}"
    run_script_by_slug "$SCRIPT_SELECTED"

    [[ "$RETURN_TO_MAIN" == true ]] && { RETURN_TO_MAIN=false; break; }
  done
done
