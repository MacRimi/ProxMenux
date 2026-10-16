#!/bin/bash
# Install OS packages only after a valid positive check. The shared runner
# verifies that precondition under its CT lock before any lifecycle effect.
export REQUIRE_CHECKED_OS=1 TARGET=os RUN_HELPER=0 UPDATE_COMMAND=""
export ALLOW_HELPER_WITH_CUSTOM=0 DOCKER_STANDALONE_TARGETS="" UPDATE_DOCKER_ENGINE=0
exec /bin/bash "$(dirname -- "$(readlink -f -- "$0")")/apply_updates.sh"
