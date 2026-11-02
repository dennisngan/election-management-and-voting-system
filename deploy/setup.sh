#!/bin/sh
# One-time setup. The only host runtime dependencies are Docker Compose and a shell.
set -eu
umask 077
task_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$task_root"
deployment_host=
deployment_root=${ELECTION_DEPLOY_ROOT:-/srv/election-system}
deployment_bind=${ELECTION_DEPLOY_BIND:-127.0.0.1}
deployment_port=${ELECTION_DEPLOY_PORT:-8443}
deployment_project=${ELECTION_DEPLOY_PROJECT:-election-deployment}
administrator=admin
display_name=Administrator
while [ "$#" -gt 0 ]; do
    case "$1" in
        --host) deployment_host=$2 ;;
        --root) deployment_root=$2 ;;
        --bind) deployment_bind=$2 ;;
        --port) deployment_port=$2 ;;
        --project) deployment_project=$2 ;;
        --username) administrator=$2 ;;
        --display-name) display_name=$2 ;;
        *) printf 'Unknown setup option: %s\n' "$1" >&2; exit 2 ;;
    esac
    shift 2
done
if [ -z "$deployment_host" ]; then
    printf 'Usage: deploy/setup.sh --host <stable hostname or IP> [--root <absolute path>] [--bind <private IP>]\n' >&2
    exit 2
fi
case "$deployment_root" in
    /*) ;;
    *) printf 'The persistent root must be an absolute host path.\n' >&2; exit 2 ;;
esac
export ELECTION_DEPLOY_ROOT="$deployment_root" ELECTION_DEPLOY_BIND="$deployment_bind"
export ELECTION_DEPLOY_PORT="$deployment_port" ELECTION_DEPLOY_PROJECT="$deployment_project"
docker compose build api </dev/null
mkdir -p "$deployment_root"
docker compose run --rm --no-deps -T prepare --root /data --host-root "$deployment_root" \
    --host "$deployment_host" --bind "$deployment_bind" --port "$deployment_port" \
    --project "$deployment_project" </dev/null
docker compose up --detach --wait --wait-timeout 180 db </dev/null
docker compose run --rm --no-deps admin initialize --username "$administrator" \
    --display-name "$display_name"
docker compose up --detach --wait --wait-timeout 90 api </dev/null
printf '\nDeployment ready. Public trust certificate: %s/tls/ca.pem\n' "$deployment_root"
printf 'For later commands, load the NON-SECRET Compose profile: %s/config/compose.env\n' "$deployment_root"
printf 'Use the deployment guide for client setup, explicit upgrades and restore verification.\n'
