#!/bin/bash
# ==========================================================
# ProxMenux - Sprint 12B: re-run a single post-install function
# ==========================================================
# Invoked by the Monitor's "Update" buttons (Settings → ProxMenux
# Optimizations) and by the bash menu's update flow. Sources the
# appropriate post_install script and invokes one specific function so
# the user can update a single tool without re-running the whole flow.
#
# Two invocation modes:
#
#   SINGLE — set SOURCE_TYPE + FUNCTION_NAME (+ optionally TOOL_KEY):
#     SOURCE_TYPE=auto FUNCTION_NAME=install_log2ram_auto
#
#   BATCH  — set FUNCTIONS_BATCH to a newline-separated list of
#            "source:function:tool_key" triples (tool_key optional):
#     FUNCTIONS_BATCH="auto:install_log2ram_auto:log2ram
#     custom:install_ceph:ceph"
#
#   In batch mode the wrapper iterates the list, sourcing each flow once
#   and re-using its function definitions. Tools coming from the same
#   flow share a single source step so the terminal output stays clean.
# ==========================================================

set -e

LOCAL_SCRIPTS="/usr/local/share/proxmenux/scripts"
BASE_DIR="/usr/local/share/proxmenux"
UTILS_FILE="$BASE_DIR/utils.sh"

if [[ -f "$UTILS_FILE" ]]; then
    # shellcheck disable=SC1090
    source "$UTILS_FILE"
fi

if command -v load_language >/dev/null 2>&1; then
    load_language
fi
if command -v initialize_cache >/dev/null 2>&1; then
    initialize_cache
fi

if command -v show_proxmenux_logo >/dev/null 2>&1; then
    show_proxmenux_logo
fi

SOURCE_TYPE="${SOURCE_TYPE:-}"
FUNCTION_NAME="${FUNCTION_NAME:-}"
TOOL_KEY="${TOOL_KEY:-${FUNCTION_NAME}}"
FUNCTIONS_BATCH="${FUNCTIONS_BATCH:-}"

# Build the list of (source, function, tool_key) tuples from either the
# single-mode env vars or the batch payload.
declare -a BATCH=()
if [[ -n "$FUNCTIONS_BATCH" ]]; then
    while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        BATCH+=("$line")
    done <<< "$FUNCTIONS_BATCH"
elif [[ -n "$SOURCE_TYPE" && -n "$FUNCTION_NAME" ]]; then
    BATCH+=("${SOURCE_TYPE}:${FUNCTION_NAME}:${TOOL_KEY}")
else
    echo "ERROR: provide either SOURCE_TYPE+FUNCTION_NAME (single mode) or FUNCTIONS_BATCH (batch mode)."
    exit 2
fi

# ----------------------------------------------------------------------
# Source the flow scripts on first use. Both auto and customizable
# guard their entry point with `if [[ "${BASH_SOURCE[0]}" == "${0}" ]]`,
# so sourcing loads function definitions without triggering the
# interactive menu or the extremeshok dialog.
# ----------------------------------------------------------------------
SOURCED_AUTO=0
SOURCED_CUSTOM=0
ensure_flow_loaded() {
    local source_type="$1"
    case "$source_type" in
        auto)
            if [[ $SOURCED_AUTO -eq 0 ]]; then
                # shellcheck disable=SC1091
                source "$LOCAL_SCRIPTS/post_install/auto_post_install.sh"
                SOURCED_AUTO=1
            fi
            ;;
        custom)
            if [[ $SOURCED_CUSTOM -eq 0 ]]; then
                # shellcheck disable=SC1091
                source "$LOCAL_SCRIPTS/post_install/customizable_post_install.sh"
                SOURCED_CUSTOM=1
            fi
            ;;
        *)
            echo "ERROR: invalid source '$source_type' (must be 'auto' or 'custom')"
            return 2
            ;;
    esac
}

# ----------------------------------------------------------------------
# Run each tool. We don't bail on the first failure — the user marked a
# multi-select, they expect every chosen tool to be attempted. RCs are
# collected and the wrapper exits non-zero if any failed.
# ----------------------------------------------------------------------
TOTAL=${#BATCH[@]}
FAILED=0
INDEX=0
for entry in "${BATCH[@]}"; do
    INDEX=$((INDEX + 1))
    IFS=':' read -r src fn tkey <<< "$entry"
    [[ -z "$tkey" ]] && tkey="$fn"

    if command -v msg_info2 >/dev/null 2>&1; then
        msg_info2 "[$INDEX/$TOTAL] Updating ${tkey} (running ${fn} from ${src} flow)..."
    else
        echo "[ProxMenux] [$INDEX/$TOTAL] Updating ${tkey} (running ${fn} from ${src} flow)..."
    fi

    if ! ensure_flow_loaded "$src"; then
        FAILED=$((FAILED + 1))
        continue
    fi

    if ! declare -F "$fn" >/dev/null 2>&1; then
        if command -v msg_error >/dev/null 2>&1; then
            msg_error "Function '$fn' is not defined in the ${src} flow."
        else
            echo "ERROR: function '$fn' is not defined in the ${src} flow."
        fi
        FAILED=$((FAILED + 1))
        continue
    fi

    set +e
    "$fn"
    RC=$?
    set -e

    if [[ $RC -eq 0 ]]; then
        if command -v msg_ok >/dev/null 2>&1; then
            msg_ok "Update for ${tkey} completed."
        else
            echo "[ProxMenux] Update for ${tkey} completed."
        fi
    else
        if command -v msg_error >/dev/null 2>&1; then
            msg_error "Update for ${tkey} exited with status $RC."
        else
            echo "ERROR: update for ${tkey} exited with status $RC."
        fi
        FAILED=$((FAILED + 1))
    fi
done

if [[ $FAILED -eq 0 ]]; then
    if command -v msg_success >/dev/null 2>&1; then
        msg_success "All $TOTAL update(s) completed successfully."
    else
        echo "[ProxMenux] All $TOTAL update(s) completed successfully."
    fi
else
    if command -v msg_warn >/dev/null 2>&1; then
        msg_warn "$FAILED of $TOTAL updates failed — see the messages above."
    else
        echo "WARNING: $FAILED of $TOTAL updates failed."
    fi
fi

if command -v msg_success >/dev/null 2>&1; then
    msg_success "Press Enter to close this terminal..."
else
    echo "Press Enter to close this terminal..."
fi
read -r 2>/dev/null || true

[[ $FAILED -eq 0 ]] && exit 0 || exit 1
