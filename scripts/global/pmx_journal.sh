#!/usr/bin/env bash
# ProxMenux change journal — recording side.
#
# What a sysadmin holds against a tool like this one is not that it
# changes things: it is that afterwards nobody can say what it changed.
# Reading the script does not answer it either — a function of four
# hundred lines may alter two values, and the reader has no way to know
# which two.
#
# So the rule here is that a change is recorded because it could not be
# made any other way. These helpers are the writing path: they capture
# what was there, make the change, and record both. A function that uses
# them is auditable without its author having remembered anything, and a
# function that writes directly is a bug we can find by grepping.
#
# Nothing here needs sqlite, python or network access. Each entry is one
# small JSON file written whole into a spool directory, which the Monitor
# reads and consolidates. One file per entry means no two concurrent
# scripts can interleave a line, and an interrupted write leaves a file
# the reader skips rather than a corrupted log.
#
# Usage:
#     source /usr/local/share/proxmenux/scripts/pmx_journal.sh
#     pmx_journal_context "optimize_logrotate" "1.1"
#     pmx_write_file /etc/logrotate.conf <<EOF
#     ...
#     EOF
#     pmx_enable_service log2ram
#
# Everything degrades quietly: if the journal cannot be written, the
# change still happens. Recording must never be the reason an operation
# fails on somebody's host.

PMX_JOURNAL_ROOT="${PMX_JOURNAL_ROOT:-/usr/local/share/proxmenux/changes}"
PMX_JOURNAL_SPOOL="$PMX_JOURNAL_ROOT/spool"
PMX_JOURNAL_OBJECTS="$PMX_JOURNAL_ROOT/objects"

# Set by pmx_journal_context; every entry carries them.
PMX_JOURNAL_FUNCTION="${PMX_JOURNAL_FUNCTION:-}"
PMX_JOURNAL_VERSION="${PMX_JOURNAL_VERSION:-}"
PMX_JOURNAL_SOURCE="${PMX_JOURNAL_SOURCE:-${SCRIPT_SOURCE:-}}"

# Which function is making the changes that follow. Called once at the
# top of a function, so the entries it produces are attributable to it
# rather than to whichever script happened to source this file.
pmx_journal_context() {
    PMX_JOURNAL_FUNCTION="${1:-unknown}"
    PMX_JOURNAL_VERSION="${2:-}"
    PMX_JOURNAL_SOURCE="${3:-${SCRIPT_SOURCE:-$(basename "${BASH_SOURCE[-1]:-unknown}")}}"
}

_pmx_journal_ready() {
    mkdir -p "$PMX_JOURNAL_SPOOL" "$PMX_JOURNAL_OBJECTS" 2>/dev/null || return 1
    chmod 700 "$PMX_JOURNAL_ROOT" 2>/dev/null || true
    return 0
}

# JSON string escaping in pure bash: no jq dependency on the recording
# side, because the recording side runs before anything is installed.
_pmx_json_escape() {
    local text="$1"
    text="${text//\\/\\\\}"
    text="${text//\"/\\\"}"
    text="${text//$'\n'/\\n}"
    text="${text//$'\r'/\\r}"
    text="${text//$'\t'/\\t}"
    printf '%s' "$text"
}

# The largest file whose contents are worth keeping. Configuration is
# measured in kilobytes; a binary is measured in megabytes and shows no
# useful difference, so past this the journal records that the file was
# there and what it hashed to, and stops short of copying it. A host that
# fills its disk with captured binaries is a worse outcome than a change
# whose contents cannot be shown.
PMX_JOURNAL_MAX_OBJECT="${PMX_JOURNAL_MAX_OBJECT:-1048576}"

# Set by _pmx_store_object. Reported through globals rather than printed
# because a command substitution runs in a subshell: anything the helper
# set there would be lost on the way back, and the caller would record
# every capture as unrecoverable.
PMX_LAST_DIGEST=""
PMX_LAST_OBJECT_STORED=false

# Stores a file's contents and returns its digest, so an entry references
# the bytes rather than embedding them. Content is kept once however many
# times it is captured.
_pmx_store_object() {
    local path="$1"
    PMX_LAST_DIGEST=""
    PMX_LAST_OBJECT_STORED=false
    [ -f "$path" ] || return 1
    local digest
    digest="$(sha256sum "$path" 2>/dev/null | cut -d' ' -f1)" || return 1
    [ -n "$digest" ] || return 1
    PMX_LAST_DIGEST="$digest"

    local size
    size="$(stat -c %s "$path" 2>/dev/null || echo 0)"
    if [ "$size" -gt "$PMX_JOURNAL_MAX_OBJECT" ] 2>/dev/null; then
        # The digest still identifies what was there; the bytes are not
        # kept, and the entry will say the change cannot be undone from
        # the journal alone.
        return 0
    fi

    local target="$PMX_JOURNAL_OBJECTS/${digest:0:2}/$digest"
    if [ ! -f "$target" ]; then
        mkdir -p "$(dirname "$target")" 2>/dev/null || return 1
        cp "$path" "$target.tmp.$$" 2>/dev/null || return 1
        chmod 600 "$target.tmp.$$" 2>/dev/null || true
        mv "$target.tmp.$$" "$target" 2>/dev/null || return 1
    fi
    PMX_LAST_OBJECT_STORED=true
}

# Writes one entry. Callers pass key=value pairs; values are escaped
# here so no caller has to think about JSON.
_pmx_journal_record() {
    _pmx_journal_ready || return 0
    local entry="" key value first=1
    for pair in "$@"; do
        key="${pair%%=*}"
        value="${pair#*=}"
        [ "$first" = 1 ] && first=0 || entry+=","
        # A key ending in _raw carries a number or a literal such as
        # true/false/null and is written unquoted.
        if [ "${key%_raw}" != "$key" ]; then
            entry+="\"${key%_raw}\":${value}"
        else
            entry+="\"$key\":\"$(_pmx_json_escape "$value")\""
        fi
    done
    local file
    file="$PMX_JOURNAL_SPOOL/$(date +%s)-$$-${RANDOM}.json"
    printf '{%s}\n' "$entry" > "$file.tmp" 2>/dev/null || return 0
    chmod 600 "$file.tmp" 2>/dev/null || true
    mv "$file.tmp" "$file" 2>/dev/null || true
    return 0
}

_pmx_journal_common() {
    printf '%s\n' \
        "recorded_at_raw=$(date +%s)" \
        "function=${PMX_JOURNAL_FUNCTION:-unknown}" \
        "function_version=${PMX_JOURNAL_VERSION:-}" \
        "source=${PMX_JOURNAL_SOURCE:-unknown}"
}

# ---------------------------------------------------------------------
# Configuration: files this host had, and what they became
# ---------------------------------------------------------------------

# Replaces a file with what arrives on stdin, capturing what was there.
#
#     pmx_write_file /etc/logrotate.conf <<EOF
#     ...
#     EOF
pmx_write_file() {
    local path="$1"
    local temp before="" after="" existed="false"
    temp="$(mktemp)" || { cat > "$path"; return $?; }
    cat > "$temp"

    local kept="true"
    if [ -f "$path" ]; then
        existed="true"
        _pmx_store_object "$path"
        before="$PMX_LAST_DIGEST"; kept="$PMX_LAST_OBJECT_STORED"
    fi
    # The change itself. Permissions of an existing file are preserved by
    # writing through it rather than replacing the inode.
    if ! cat "$temp" > "$path" 2>/dev/null; then
        rm -f "$temp"
        return 1
    fi
    _pmx_store_object "$path"; after="$PMX_LAST_DIGEST"
    rm -f "$temp"
    # Writing the same bytes back is not a change. Recording it would
    # fill the journal with entries a reader has to open to discover
    # nothing happened — which is exactly what re-running an idempotent
    # post-install does.
    [ "$before" = "$after" ] && return 0

    local -a fields
    mapfile -t fields < <(_pmx_journal_common)
    _pmx_journal_record "${fields[@]}" \
        "class=configuration" "operation=write_file" "target=$path" \
        "before=${before:-}" "after=${after:-}" \
        "existed_raw=$existed" \
        "capture=$([ "$existed" = true ] && echo present || echo created)" \
        "revert=$([ "$existed" = true ] && echo restore || echo remove)" \
        "exactness=$([ "$existed" != true ] || [ "$kept" = true ] && echo exact || echo none)"
}

# Applies a sed expression in place, capturing the file first.
#
#     pmx_edit_file /etc/default/grub 's/^X=.*/X=1/'
pmx_edit_file() {
    local path="$1"; shift
    [ -f "$path" ] || return 1
    local before after kept
    _pmx_store_object "$path"
    before="$PMX_LAST_DIGEST"; kept="$PMX_LAST_OBJECT_STORED"
    sed -i "$@" "$path" || return 1
    _pmx_store_object "$path"; after="$PMX_LAST_DIGEST"
    # An expression that matched nothing is not a change, and recording
    # it would fill the journal with entries a reader has to dismiss.
    [ "$before" = "$after" ] && return 0

    local -a fields
    mapfile -t fields < <(_pmx_journal_common)
    _pmx_journal_record "${fields[@]}" \
        "class=configuration" "operation=edit_file" "target=$path" \
        "before=${before:-}" "after=${after:-}" \
        "expression=$*" "capture=present" "revert=restore" \
        "exactness=$([ "$kept" = true ] && echo exact || echo none)"
}

# Removes a file, keeping its contents so the removal can be undone.
pmx_remove_file() {
    local path="$1"
    [ -e "$path" ] || return 0
    local before kept
    _pmx_store_object "$path"
    before="$PMX_LAST_DIGEST"; kept="$PMX_LAST_OBJECT_STORED"
    rm -f "$path" || return 1

    local -a fields
    mapfile -t fields < <(_pmx_journal_common)
    _pmx_journal_record "${fields[@]}" \
        "class=configuration" "operation=remove_file" "target=$path" \
        "before=${before:-}" "after=" "capture=present" \
        "revert=restore" \
        "exactness=$([ "$kept" = true ] && echo exact || echo none)"
}

# Adds to a file, keeping what was there.
#
# Appending looks like it needs no capture — the previous content is
# still in the file — but the journal shows a change as the difference
# between two states, and a reader asking what a function did to a file
# should not have to reconstruct the first state by subtracting.
#
#     printf 'ulimit -n 1048576\n' | pmx_append_file /root/.profile
pmx_append_file() {
    local path="$1"
    local temp before="" after="" existed="false"
    temp="$(mktemp)" || { cat >> "$path"; return $?; }
    cat > "$temp"

    local kept="true"
    if [ -f "$path" ]; then
        existed="true"
        _pmx_store_object "$path"
        before="$PMX_LAST_DIGEST"; kept="$PMX_LAST_OBJECT_STORED"
    fi
    if ! cat "$temp" >> "$path" 2>/dev/null; then
        rm -f "$temp"
        return 1
    fi
    _pmx_store_object "$path"; after="$PMX_LAST_DIGEST"
    rm -f "$temp"
    [ "$before" = "$after" ] && return 0

    local -a fields
    mapfile -t fields < <(_pmx_journal_common)
    _pmx_journal_record "${fields[@]}" \
        "class=configuration" "operation=append_file" "target=$path" \
        "before=${before:-}" "after=${after:-}" \
        "capture=$([ "$existed" = true ] && echo present || echo created)" \
        "revert=$([ "$existed" = true ] && echo restore || echo remove)" \
        "exactness=$([ "$existed" != true ] || [ "$kept" = true ] && echo exact || echo none)"
}

# Applies a setting through the command that owns it, capturing the
# state that command reports before and after.
#
# Some settings have no file to write: the timezone, whether the clock is
# disciplined, a bootloader entry. The tool that owns them is the only
# thing that can read them back, so it is asked twice — before and after
# — and the journal records the two answers.
#
#     pmx_apply_setting "timezone" "timedatectl show -p Timezone --value" \
#         timedatectl set-timezone "$timezone"
pmx_apply_setting() {
    local name="$1" reader="$2"; shift 2
    local before after
    before="$(eval "$reader" 2>/dev/null | head -c 400)"
    "$@" >/dev/null 2>&1
    local status=$?
    after="$(eval "$reader" 2>/dev/null | head -c 400)"
    # A setting already at the wanted value is not a change.
    [ "$before" = "$after" ] && return $status

    local -a fields
    mapfile -t fields < <(_pmx_journal_common)
    _pmx_journal_record "${fields[@]}" \
        "class=configuration" "operation=apply_setting" "target=$name" \
        "before_state=$before" "after_state=$after" "command=$*" \
        "capture=present" "revert=reapply" \
        "result=$([ $status -eq 0 ] && echo ok || echo failed)" \
        "exactness=exact"
    return $status
}

# ---------------------------------------------------------------------
# Installation: what was not on this host and now is
# ---------------------------------------------------------------------

# Installs packages, recording which ones actually arrived.
#
# What is recorded is the difference the operation made, not what was
# asked for: a package already present is not a change, and the
# dependencies apt pulled in are, even though nobody named them.
pmx_install_pkg() {
    local -a requested=("$@")
    [ ${#requested[@]} -gt 0 ] || return 0

    local before_list after_list added
    before_list="$(dpkg-query -W -f='${binary:Package}\n' 2>/dev/null | sort -u)"
    DEBIAN_FRONTEND=noninteractive apt-get install -y "${requested[@]}" >/dev/null 2>&1
    local status=$?
    after_list="$(dpkg-query -W -f='${binary:Package}\n' 2>/dev/null | sort -u)"
    added="$(comm -13 <(printf '%s\n' "$before_list") <(printf '%s\n' "$after_list") | tr '\n' ' ')"

    local -a fields
    mapfile -t fields < <(_pmx_journal_common)
    _pmx_journal_record "${fields[@]}" \
        "class=installation" "operation=install_package" \
        "target=${requested[*]}" "installed=${added% }" \
        "result=$([ $status -eq 0 ] && echo ok || echo failed)" \
        "capture=present" "revert=purge" \
        "exactness=$([ -n "${added// /}" ] && echo partial || echo none)"
    return $status
}

# ---------------------------------------------------------------------
# Services: what was running, and what runs now
# ---------------------------------------------------------------------

_pmx_service_state() {
    local unit="$1"
    printf '%s/%s' \
        "$(systemctl is-enabled "$unit" 2>/dev/null | head -1 || echo unknown)" \
        "$(systemctl is-active "$unit" 2>/dev/null | head -1 || echo unknown)"
}

pmx_enable_service() {
    local unit="$1"
    local before after
    before="$(_pmx_service_state "$unit")"
    systemctl enable --now "$unit" >/dev/null 2>&1
    local status=$?
    after="$(_pmx_service_state "$unit")"
    [ "$before" = "$after" ] && return $status

    local -a fields
    mapfile -t fields < <(_pmx_journal_common)
    _pmx_journal_record "${fields[@]}" \
        "class=configuration" "operation=enable_service" "target=$unit" \
        "before_state=$before" "after_state=$after" \
        "capture=present" "revert=disable" "exactness=exact"
    return $status
}

pmx_disable_service() {
    local unit="$1"
    local before after
    before="$(_pmx_service_state "$unit")"
    systemctl disable --now "$unit" >/dev/null 2>&1
    local status=$?
    after="$(_pmx_service_state "$unit")"
    [ "$before" = "$after" ] && return $status

    local -a fields
    mapfile -t fields < <(_pmx_journal_common)
    _pmx_journal_record "${fields[@]}" \
        "class=configuration" "operation=disable_service" "target=$unit" \
        "before_state=$before" "after_state=$after" \
        "capture=present" "revert=enable" "exactness=exact"
    return $status
}

# ---------------------------------------------------------------------
# Execution: what ProxMenux ran on the user's behalf
# ---------------------------------------------------------------------

# For work ProxMenux launches but does not decide: a system upgrade, a
# rebuild. Recording it as a change of ours would claim authorship of
# whatever apt decided; recording nothing would leave a host that changed
# under the reader's feet with no trace of why.
pmx_record_execution() {
    local description="$1"; shift
    local command="$*"
    local -a fields
    mapfile -t fields < <(_pmx_journal_common)
    _pmx_journal_record "${fields[@]}" \
        "class=execution" "operation=run_command" \
        "target=$description" "command=$command" \
        "capture=none" "revert=none" "exactness=none"
}

# Records that a function was applied without being able to say what it
# changed — the state before it ran is not knowable. Used by the
# registration path so a host carries an honest account of what was
# applied before the journal existed.
# Records packages the installer put on the host before the journal existed
# (its own dependencies). They are a real host change, so they belong in the
# installation class — there is simply no prior state to diff, because the
# host did not have them.
pmx_record_install() {
    local packages="$1" version="${2:-1.0}"
    local -a fields
    mapfile -t fields < <(_pmx_journal_common)
    _pmx_journal_record "${fields[@]}" \
        "class=installation" "operation=install_package" "target=$packages" \
        "installed=$packages" "function_version=$version" "result=ok" \
        "capture=created" "revert=purge" "exactness=none"
}

# Records that ProxMenux removed a package. On ingest this retires the
# package's installation entry, so a package installed and later removed no
# longer shows as present — the journal reflects the current state.
pmx_record_uninstall() {
    local packages="$1" version="${2:-1.0}"
    local -a fields
    mapfile -t fields < <(_pmx_journal_common)
    _pmx_journal_record "${fields[@]}" \
        "class=installation" "operation=uninstall_package" "target=$packages" \
        "function_version=$version" "capture=none" "revert=none" "exactness=none"
}

pmx_record_applied() {
    local tool="$1" version="$2" state="${3:-applied}"
    local -a fields
    mapfile -t fields < <(_pmx_journal_common)
    _pmx_journal_record "${fields[@]}" \
        "class=registration" "operation=$state" "target=$tool" \
        "function_version=$version" "capture=unknown" \
        "revert=none" "exactness=none"
}
