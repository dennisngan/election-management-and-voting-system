#!/bin/sh
# Explicit offline upgrades. A failed step leaves the API stopped/interlocked.
set -eu
umask 077
task_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$task_root"
operation=${1:-status}
if [ "$#" -gt 0 ]; then shift; fi
case "$operation" in
    upgrade)
        if [ "$#" -ne 0 ]; then printf 'upgrade takes no extra arguments\n' >&2; exit 2; fi
        # This lease spans ALL subprocesses, including the final API restart.
        workflow_lock="${ELECTION_DEPLOY_ROOT:-/srv/election-system}/config/upgrade.lock"
        if ! mkdir -m 700 "$workflow_lock" 2>/dev/null; then
            printf 'upgrade_workflow_busy: inspect the deployment profile and existing upgrade lease\n' >&2
            exit 1
        fi
        trap 'rmdir "$workflow_lock" 2>/dev/null || :' 0
        trap 'exit 130' 2
        trap 'exit 143' 15
        docker compose stop api
        previous_image=$(docker compose images --quiet api)
        docker compose run --rm --no-deps -T admin backup --image-id "$previous_image"
        docker compose build api
        docker compose run --rm --no-deps -T admin migrate
        docker compose run --rm --no-deps -T admin finish
        docker compose up --detach --wait --wait-timeout 90 api
        ;;
    status|identity|prepare-test|restore)
        docker compose run --rm --no-deps -T admin "$operation" "$@"
        ;;
    *)
        printf 'Usage: deploy/maintenance.sh {status|identity|upgrade|prepare-test|restore} [arguments]\n' >&2
        exit 2
        ;;
esac
