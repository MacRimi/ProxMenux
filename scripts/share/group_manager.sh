#!/usr/bin/env bash
# ==========================================================
# ProxMenux - Shared Groups Manager
# ==========================================================
# Author      : MacRimi
# Description : Manage host groups for shared directories
# ==========================================================

# Configuration
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"

if [[ -f "$UTILS_FILE" ]]; then
    source "$UTILS_FILE"
fi

load_language
initialize_cache


pmx_list_groups() {
    local groups
    groups=$(getent group | awk -F: '$3 >= 1000 && $1 != "nogroup" && $1 !~ /^pve/ {print $1 ":" $3}')
    if [[ -z "$groups" ]]; then
        whiptail --title "$(translate "Groups")" --msgbox "$(translate "No user groups found.")" 8 60
        return
    fi

    show_proxmenux_logo
    msg_title "$(translate "Existing Groups")"
    echo "$groups" | column -t -s: | while read -r name gid; do
        members=$(getent group "$name" | awk -F: '{print $4}')
        echo -e "  • ${BL}$name${CL} (GID: $gid)  ->  ${YW}${members:-no members}${CL}"
    done
    echo ""
    msg_success "$(translate "Press Enter to continue...")"
    read -r
}



pmx_create_group() {
    group_name=$(dialog --inputbox "$(translate "Enter new group name:")" 10 60 "sharedfiles-new" \
        --title "$(translate "New Group")" 3>&1 1>&2 2>&3) || return
    [[ -z "$group_name" ]] && return

    if getent group "$group_name" >/dev/null; then
        dialog --title "$(translate "Error")" --msgbox "$(translate "Group already exists.")" 8 50
        return
    fi

    if groupadd "$group_name"; then
        show_proxmenux_logo
        msg_title "$(translate "Create Group")"
        msg_ok "$(translate "Group created successfully:") $group_name"
    else
        show_proxmenux_logo
        msg_title "$(translate "Create Group")"
        msg_error "$(translate "Failed to create group.")"
    fi
    
    echo -e
    msg_success "$(translate "Press Enter to continue...")"
    read -r
}



pmx_edit_group() {
    local groups group_name action
    

    groups=$(getent group | awk -F: '$3 >= 1000 && $1 != "nogroup" && $1 !~ /^pve/ {print $1}')
    
    if [[ -z "$groups" ]]; then
        dialog --title "$(translate "Error")" --msgbox "$(translate "No groups available to edit.")" 8 50
        return
    fi


    local menu_options=""
    while read -r group; do
        if [[ -n "$group" ]]; then
            local gid=$(getent group "$group" | cut -d: -f3)
            menu_options="$menu_options $group \"GID:$gid\""
        fi
    done <<< "$groups"


    group_name=$(eval "dialog --title \"$(translate "Edit Group")\" --menu \
        \"$(translate "Select a group:")\" 20 60 10 \
        $menu_options 3>&1 1>&2 2>&3")
    
    if [[ -z "$group_name" ]]; then
        return
    fi


    action=$(dialog --title "$(translate "Edit Group")" --menu \
        "$(translate "What do you want to edit in group:") $group_name" 15 60 3 \
        "rename" "$(translate "Rename group")" \
        "gid"    "$(translate "Change GID")" \
        "users"  "$(translate "Add/Remove users")" 3>&1 1>&2 2>&3)
    
    if [[ -z "$action" ]]; then
        return
    fi

    case "$action" in
        rename)
            new_name=$(dialog --inputbox "$(translate "Enter new group name:")" 10 60 \
                "$group_name" --title "$(translate "Rename Group")" 3>&1 1>&2 2>&3)
            if [[ -n "$new_name" && "$new_name" != "$group_name" ]]; then
                if groupmod -n "$new_name" "$group_name" 2>/dev/null; then
                    show_proxmenux_logo
                    msg_title "$(translate "Rename Group")"
                    msg_ok "$(translate "Group renamed to:") $new_name"
                else
                    show_proxmenux_logo
                    msg_title "$(translate "Rename Group")"
                    msg_error "$(translate "Failed to rename group")"
                fi
            fi
            ;;
        gid)
            current_gid=$(getent group "$group_name" | cut -d: -f3)
            new_gid=$(dialog --inputbox "$(translate "Enter new GID:")" 10 60 \
                "$current_gid" --title "$(translate "Change GID")" 3>&1 1>&2 2>&3)
            if [[ -n "$new_gid" && "$new_gid" != "$current_gid" ]]; then
                if groupmod -g "$new_gid" "$group_name" 2>/dev/null; then
                    show_proxmenux_logo
                    msg_title "$(translate "Change GID")"
                    msg_ok "$(translate "GID changed to:") $new_gid"
                else
                    show_proxmenux_logo
                    msg_title "$(translate "Change GID")"
                    msg_error "$(translate "Failed to change GID")"
                fi
            fi
            ;;
        users)
            user_action=$(dialog --title "$(translate "User Management")" --menu \
                "$(translate "Choose an action for group:") $group_name" 15 60 2 \
                "add" "$(translate "Add user to group")" \
                "remove" "$(translate "Remove user from group")" 3>&1 1>&2 2>&3)

            case "$user_action" in
                add)
                    username=$(dialog --inputbox "$(translate "Enter username to add:")" 10 60 \
                        --title "$(translate "Add User")" 3>&1 1>&2 2>&3)
                    if [[ -n "$username" ]]; then
                        if id "$username" >/dev/null 2>&1; then
                            if usermod -aG "$group_name" "$username" 2>/dev/null; then
                                show_proxmenux_logo
                                msg_title "$(translate "Add User")"
                                msg_ok "$(translate "User added:") $username"
                            else
                                show_proxmenux_logo
                                msg_title "$(translate "Add User")"
                                msg_error "$(translate "Failed to add user")"
                            fi
                        else
                            show_proxmenux_logo
                            msg_title "$(translate "Add User")"
                            msg_error "$(translate "User does not exist:") $username"
                        fi
                    fi
                    ;;
                remove)
                    members=$(getent group "$group_name" | awk -F: '{print $4}' | tr ',' ' ')
                    if [[ -z "$members" ]]; then
                        dialog --title "$(translate "Info")" --msgbox "$(translate "No users in this group.")" 8 50
                        return
                    fi
                    

                    local user_options=""
                    for user in $members; do
                        user_options="$user_options $user \"\""
                    done
                    
                    username=$(eval "dialog --title \"$(translate "Remove User")\" --menu \
                        \"$(translate "Select user to remove:")\" 15 60 5 \
                        $user_options 3>&1 1>&2 2>&3")
                    
                    if [[ -n "$username" ]]; then
                        if gpasswd -d "$username" "$group_name" 2>/dev/null; then
                            show_proxmenux_logo
                            msg_title "$(translate "Remove User")"
                            msg_ok "$(translate "User removed:") $username"
                        else
                            show_proxmenux_logo
                            msg_title "$(translate "Remove User")"
                            msg_error "$(translate "Failed to remove user")"
                        fi
                    fi
                    ;;
            esac
            ;;
    esac
    

    echo -e
    msg_success "$(translate "Press Enter to continue...")"
    read -r
}



pmx_delete_group() {
    local groups group_name menu_options
    groups=$(getent group | awk -F: '$3 >= 1000 && $1 != "nogroup" && $1 !~ /^pve/ {print $1}')
    
    if [[ -z "$groups" ]]; then
        dialog --title "$(translate "Error")" --msgbox "$(translate "No groups available to delete.")" 8 50
        return
    fi


    menu_options=""
    while read -r group; do
        if [[ -n "$group" ]]; then
            menu_options="$menu_options $group \"\""
        fi
    done <<< "$groups"

    group_name=$(eval "dialog --title \"$(translate "Delete Group")\" --menu \
        \"$(translate "Select a group to delete:")\" 20 60 10 \
        $menu_options 3>&1 1>&2 2>&3") || return

    if dialog --yesno "$(translate "Are you sure you want to delete group:") $group_name ?" 10 60; then
        if groupdel "$group_name" 2>/dev/null; then
            show_proxmenux_logo
            msg_title "$(translate "Deleting Groups")"
            msg_ok "$(translate "Group deleted:") $group_name"
        else
                        show_proxmenux_logo
            msg_title "$(translate "Deleting Groups")"
            msg_ok "$(translate "Group deleted:") $group_name"
            msg_error "$(translate "Failed to delete group")"
        fi
    fi
    echo -e
    msg_success "$(translate "Press Enter to continue...")"
    read -r
}


pmx_manage_groups() {
    while true; do
        CHOICE=$(dialog --title "$(translate "Shared Groups Manager")" \
            --menu "$(translate "Select an option:")" 20 70 10 \
            "list"   "$(translate "View existing groups")" \
            "create" "$(translate "Create new group")" \
            "edit"   "$(translate "Edit existing group")" \
            "delete" "$(translate "Delete a group")" \
            "exit"   "$(translate "Exit")" \
            3>&1 1>&2 2>&3) || return 0

        case "$CHOICE" in
            list) pmx_list_groups ;;
            create) pmx_create_group ;;
            edit) pmx_edit_group ;;
            delete) pmx_delete_group ;;
            exit) return 0 ;;
        esac
    done
}


pmx_manage_groups
