#!/bin/bash

# ==========================================================
# ProxMenux - A menu-driven script for Proxmox VE management
# ==========================================================
# Author      : MacRimi
# Copyright   : (c) 2024 MacRimi
# License     : (CC BY-NC 4.0) (https://github.com/MacRimi/ProxMenux/blob/main/LICENSE)
# Version     : 1.1
# Last Updated: 04/06/2025
# ==========================================================
# Description:
# This script provides a simple and efficient way to access and execute Proxmox VE scripts
# from the Community Scripts project (https://community-scripts.github.io/ProxmoxVE/).
#
# It serves as a convenient tool to run key automation scripts that simplify system management,
# continuing the great work and legacy of tteck in making Proxmox VE more accessible.
# A streamlined solution for executing must-have tools in Proxmox VE.
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

HELPERS_JSON_URL="https://raw.githubusercontent.com/MacRimi/ProxMenux/refs/heads/main/json/helpers_cache.json"
METADATA_URL="https://raw.githubusercontent.com/community-scripts/ProxmoxVE/main/frontend/public/json/metadata.json"

for cmd in curl jq dialog; do
  if ! command -v "$cmd" >/dev/null; then
    echo "Missing required command: $cmd"
    exit 1
  fi
done

CACHE_JSON=$(curl -s "$HELPERS_JSON_URL")
META_JSON=$(curl -s "$METADATA_URL")

declare -A CATEGORY_NAMES
while read -r id name; do
  CATEGORY_NAMES[$id]="$name"
done < <(echo "$META_JSON" | jq -r '.categories[] | "\(.id)\t\(.name)"')

declare -A CATEGORY_COUNT
for id in $(echo "$CACHE_JSON" | jq -r '.[].categories[]'); do
  ((CATEGORY_COUNT[$id]++))
done

get_type_label() {
  local type="$1"
  case "$type" in
    ct) echo $'\Z1LXC\Zn' ;;
    vm) echo $'\Z4VM\Zn' ;;
    pve) echo $'\Z3PVE\Zn' ;;
    addon) echo $'\Z2ADDON\Zn' ;;
    *) echo $'\Z7GEN\Zn' ;;
  esac
}

download_script() {
  local url="$1"
  local fallback_pve="${url/misc\/tools\/pve}"
  local fallback_addon="${url/misc\/tools\/addon}"
  local fallback_copydata="${url/misc\/tools\/copy-data}"

  if curl --silent --head --fail "$url" >/dev/null; then
      bash <(curl -s "$url")
  elif curl --silent --head --fail "$fallback_pve" >/dev/null; then
      bash <(curl -s "$fallback_pve")
  elif curl --silent --head --fail "$fallback_addon" >/dev/null; then
      bash <(curl -s "$fallback_addon")
  elif curl --silent --head --fail "$fallback_copydata" >/dev/null; then
      bash <(curl -s "$fallback_copydata")
  else
      dialog --title "Helper Scripts" --msgbox "Error: Failed to download the script." 12 70
  fi
}

RETURN_TO_MAIN=false

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


run_script_by_slug() {
  local slug="$1"
  local script_info
  script_info=$(echo "$CACHE_JSON" | jq -r --arg slug "$slug" '.[] | select(.slug == $slug) | @base64')

  decode() {
    echo "$1" | base64 --decode | jq -r "$2"
  }

  local name desc script_url notes
  name=$(decode "$script_info" ".name")
  desc=$(decode "$script_info" ".desc")
  script_url=$(decode "$script_info" ".script_url")
  notes=$(decode "$script_info" ".notes | join(\"\n\")")


  local notes_dialog=""
  if [[ -n "$notes" ]]; then
    while IFS= read -r line; do
      notes_dialog+="• $line\n"
    done <<< "$notes"
    notes_dialog="${notes_dialog%\\n}" 
  fi


  local credentials
  credentials=$(format_credentials "$script_info")


  local msg="\Zb\Z4Descripción:\Zn\n$desc"
  [[ -n "$notes_dialog" ]] && msg+="\n\n\Zb\Z4Notes:\Zn\n$notes_dialog"
  [[ -n "$credentials" ]] && msg+="\n\n\Zb\Z4Default Credentials:\Zn\n$credentials"

  dialog --clear --colors --backtitle "ProxMenux" --title "$name" --yesno "$msg\n\nExecute this script?" 22 85
  if [[ $? -eq 0 ]]; then
    download_script "$script_url"
    echo
    echo

    if [[ -n "$desc" || -n "$notes" || -n "$credentials" ]]; then
      echo -e "$TAB\e[1;36mScript Information:\e[0m"



      if [[ -n "$notes" ]]; then
        echo -e "$TAB\e[1;33mNotes:\e[0m"
        while IFS= read -r line; do
          [[ -z "$line" ]] && continue
          echo -e "$TAB• $line"
        done <<< "$notes"
        echo
      fi

 
      if [[ -n "$credentials" ]]; then
        echo -e "$TAB\e[1;32mDefault Credentials:\e[0m"
        echo "$TAB$credentials"
        echo
      fi
    fi

    msg_success "Press Enter to return to the main menu..."
    read -r
    RETURN_TO_MAIN=true
  fi
}


search_and_filter_scripts() {
  local search_term=""
  
  while true; do
    search_term=$(dialog --inputbox "Enter search term (leave empty to show all scripts):" \
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
    count=$(echo "$filtered_json" | jq length)
    
    if [[ $count -eq 0 ]]; then
      dialog --msgbox "No scripts found for: '$search_term'\n\nTry a different search term." 8 50
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
        local entry="$padded_name $label"
        menu_items+=("$i" "$entry")
        ((i++))
      done < <(echo "$filtered_json" | jq -r '
        sort_by(.name)[] | [.slug, .name, .type] | @tsv')
      
      menu_items+=("" "")
      menu_items+=("new_search" "New Search")
      menu_items+=("show_all" "Show All Scripts")
      
      local title="Search Results"
      if [[ -n "$search_term" ]]; then
        title="Search Results for: '$search_term' ($count found)"
      else
        title="All Available Scripts ($count total)"
      fi
      
      local selected
      selected=$(dialog --colors --backtitle "ProxMenux" \
                 --title "$title" \
                 --menu "Select a script or action:" \
                 22 75 15 "${menu_items[@]}" 3>&1 1>&2 2>&3)
      
      if [[ $? -ne 0 ]]; then
        return
      fi
      
      case "$selected" in
        "new_search")
          break  
          ;;
        "show_all")
          search_term=""
          filtered_json="$CACHE_JSON"
          count=$(echo "$filtered_json" | jq length)
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

while true; do
  MENU_ITEMS=()
  
  MENU_ITEMS+=("search" "Search/Filter Scripts")
  MENU_ITEMS+=("" "")
  
  for id in $(printf "%s\n" "${!CATEGORY_COUNT[@]}" | sort -n); do
    name="${CATEGORY_NAMES[$id]:-Category $id}"
    count="${CATEGORY_COUNT[$id]}"
    padded_name=$(printf "%-35s" "$name")
    padded_count=$(printf "(%2d)" "$count")
    MENU_ITEMS+=("$id" "$padded_name $padded_count")
  done

  SELECTED=$(dialog --backtitle "ProxMenux" --title "Proxmox VE Helper-Scripts" --menu \
    "Select a category or search for scripts:" 20 70 14 \
    "${MENU_ITEMS[@]}" 3>&1 1>&2 2>&3) || {
     dialog --clear --title "Proxmox VE Helper-Scripts" \
         --msgbox "\n\n$(translate "Visit the website to discover more scripts, stay updated with the latest updates, and support the project:")\n\nhttps://community-scripts.github.io/ProxmoxVE" 15 70
      #clear
      exec bash "$LOCAL_SCRIPTS/menus/main_menu.sh"
  }
 
  if [[ "$SELECTED" == "search" ]]; then
    search_and_filter_scripts
    continue
  fi

  while true; do
    declare -A INDEX_TO_SLUG
    SCRIPTS=()
    i=1
    while IFS=$'\t' read -r slug name type; do
      INDEX_TO_SLUG[$i]="$slug"
      label=$(get_type_label "$type")
      padded_name=$(printf "%-42s" "$name")
      entry="$padded_name $label"
      SCRIPTS+=("$i" "$entry") 
      ((i++))
    done < <(echo "$CACHE_JSON" | jq -r --argjson id "$SELECTED" \
      '[.[] | select(.categories | index($id)) | {slug, name, type}] | sort_by(.name)[] | [.slug, .name, .type] | @tsv')

    SCRIPT_INDEX=$(dialog --colors --backtitle "ProxMenux" --title "Scripts in ${CATEGORY_NAMES[$SELECTED]}" --menu \
      "Choose a script to execute:" 20 70 14 \
      "${SCRIPTS[@]}" 3>&1 1>&2 2>&3) || break

    SCRIPT_SELECTED="${INDEX_TO_SLUG[$SCRIPT_INDEX]}"
    run_script_by_slug "$SCRIPT_SELECTED"
    
    [[ "$RETURN_TO_MAIN" == true ]] && { RETURN_TO_MAIN=false; break; }
  done
done
