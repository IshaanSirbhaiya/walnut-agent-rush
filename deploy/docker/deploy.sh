#!/usr/bin/env bash
# Deploy (or update) the Walnut Internal Brain stack on one Linux host with Docker (any provider, or
# your own machine; the installer step supports Ubuntu/Debian). Idempotent: safe to run again at any time.
#
#   bash deploy/docker/upload.sh user@HOST                                      # from your laptop (recommended)
#   ssh user@HOST 'sudo REPO_URL=<git url> bash -s' < deploy/docker/deploy.sh   # or let the host clone
#   sudo bash /opt/walnut/repo/deploy/docker/deploy.sh [deploy|reset|smoke|status|logs [svc]|down]
#   sudo bash /opt/walnut/repo/deploy/docker/deploy.sh configure-model [vultr]   # set the optional model, restart ib
#   sudo bash /opt/walnut/repo/deploy/docker/deploy.sh models | check-model       # list / test the model endpoint
#   sudo bash /opt/walnut/repo/deploy/docker/deploy.sh workflow                   # run the real-task workflow end to end
#
# What `deploy` does:
#   1. installs git/curl/openssl and Docker Engine + compose + buildx (official Docker apt repo) if missing
#      (skip with SKIP_INSTALL=1 when Docker is already set up, e.g. on a non-Debian host)
#   2. adds a 2 GB swap file on small hosts (the Next.js build needs it on 2 GB RAM)
#   3. gets the source into /opt/walnut/repo: git pull if it is a clone; uses it as-is if it was
#      uploaded (upload.sh); otherwise clones REPO_URL
#   4. writes /opt/walnut/walnut.env (mode 600) if missing, with freshly generated keys and passcode
#   5. docker compose up -d --build, waits for health and HTTPS, then runs smoke.sh
#
# Optional env (pass through sudo, e.g. ssh user@HOST 'sudo DOMAIN=brain.example.com bash -s' < deploy.sh):
#   DOMAIN            public hostname (default: <public-ip-with-dashes>.sslip.io)
#   IB_DEMO_PASSCODE  set/rotate the demo passcode
#   REPO_URL BRANCH   source to clone when /opt/walnut/repo is empty (no default URL; BRANCH default main)
#   SKIP_INSTALL=1    do not install packages or Docker (use what the host has)
# The optional AI model (IB_MODEL_URL, IB_MODEL_NAME, IB_MODEL_KEY, IB_MODEL_FALLBACKS) is set by
# `configure-model` (the key is read with hidden input) or by editing the env file, never on a command
# line where it would land in shell history. `configure-model vultr` pre-fills the Vultr Serverless
# Inference URL (OpenAI-compatible); any other chat-completions-style endpoint works the same way.
#   NO_BUILD=1        do not build; use images already loaded with `docker load` (see README)
#   SKIP_SMOKE=1      do not run smoke.sh at the end
set -euo pipefail

ACTION="${1:-deploy}"; shift || true
WALNUT_HOME="${WALNUT_HOME:-/opt/walnut}"
SRC="${SRC:-$WALNUT_HOME/repo}"
ENV_FILE="${ENV_FILE:-$WALNUT_HOME/walnut.env}"
REPO_URL="${REPO_URL:-}"
BRANCH="${BRANCH:-main}"
PROJECT="${COMPOSE_PROJECT:-walnut}"
COMPOSE_FILE="$SRC/deploy/docker/docker-compose.yml"

log()  { printf '\n==> %s\n' "$*"; }
warn() { printf 'WARN: %s\n' "$*" >&2; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run as root: ssh user@HOST 'sudo bash -s' < deploy.sh"
export DEBIAN_FRONTEND=noninteractive

dc() { docker compose -p "$PROJECT" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"; }

env_get() { sed -n "s/^$1=//p" "$ENV_FILE" 2>/dev/null | tail -n1; }
env_set() {  # upsert KEY=VALUE in the env file
  local k="$1" v="$2" tmp
  tmp="$(mktemp "$WALNUT_HOME/.env.XXXXXX")"
  { grep -v "^$k=" "$ENV_FILE" 2>/dev/null || true; printf '%s=%s\n' "$k" "$v"; } > "$tmp"
  chmod 600 "$tmp"; mv "$tmp" "$ENV_FILE"
}

# --- 1. packages and Docker ----------------------------------------------------------------------
apt_retry() {  # a fresh VM's unattended-upgrades can hold the apt locks for minutes after first boot
  local i
  for i in 1 2 3 4 5 6 7 8 9 10; do
    apt-get -o DPkg::Lock::Timeout=120 "$@" && return 0
    warn "apt-get $1 failed (try $i of 10); trying again in 20 s"; sleep 20
  done
  die "apt-get $* kept failing: check the VM's network, then run this script again"
}

install_prereqs() {
  local need=()
  for c in git curl openssl; do command -v "$c" >/dev/null 2>&1 || need+=("$c"); done
  command -v gpg >/dev/null 2>&1 || need+=(gnupg)
  if [ "${#need[@]}" -gt 0 ]; then
    log "installing ${need[*]}"
    apt_retry update -y -q && apt_retry install -y -q ca-certificates "${need[@]}"
  fi
}

docker_repo() {
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  # shellcheck disable=SC1091
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt_retry update -y -q
}

install_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    log "installing Docker Engine (official apt repo)"
    docker_repo
    apt_retry install -y -q docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  fi
  if ! docker compose version >/dev/null 2>&1 || ! docker buildx version >/dev/null 2>&1; then
    log "installing the docker compose and buildx plugins"
    apt-get install -y -q docker-compose-v2 docker-buildx >/dev/null 2>&1 \
      || { docker_repo && apt_retry install -y -q docker-buildx-plugin docker-compose-plugin; }
  fi
  systemctl enable --now docker >/dev/null 2>&1 || true
  docker compose version >/dev/null 2>&1 || die "docker compose v2 is not available"
  docker buildx version >/dev/null 2>&1 || die "docker buildx (BuildKit) is not available"
}

ensure_swap() {
  local mem_mb; mem_mb="$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)"
  # 6 GB: the first build happens once, under time pressure; a 4 GB VM should not risk an OOM kill
  if [ "$mem_mb" -lt 6000 ] && [ -z "$(swapon --show --noheadings 2>/dev/null)" ]; then
    log "adding a 2 GB swap file (RAM ${mem_mb} MB)"
    fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048
    chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
    grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  fi
}

# --- 2. source ------------------------------------------------------------------------------------
get_source() {
  mkdir -p "$WALNUT_HOME"
  if [ -d "$SRC/.git" ]; then
    log "updating $SRC ($BRANCH)"
    git -C "$SRC" pull --ff-only origin "$BRANCH" || die "git pull failed (local changes on the host?)"
  elif [ -f "$COMPOSE_FILE" ]; then
    log "using the uploaded source in $SRC (no .git: upload.sh)"
  else
    [ -n "$REPO_URL" ] || die "no source in $SRC: run deploy/docker/upload.sh from your laptop, or set REPO_URL=<git url>"
    log "cloning $REPO_URL ($BRANCH) into $SRC"
    git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$SRC" \
      || die "clone failed. For a private repo, run deploy/docker/upload.sh from your laptop instead, or set REPO_URL to an ssh URL with a read-only deploy key (README)."
  fi
  [ -f "$COMPOSE_FILE" ] || die "$COMPOSE_FILE not found: is deploy/docker committed on $BRANCH?"
}

# --- 3. env file ----------------------------------------------------------------------------------
public_ip() {
  # the cloud's metadata service first (Vultr: 169.254.169.254/v1), then a public echo service
  local m; m="$(curl -fsS --max-time 3 http://169.254.169.254/v1/interfaces/0/ipv4/address 2>/dev/null || true)"
  if [[ "$m" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then echo "$m"; return 0; fi
  curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null \
    || curl -fsS --max-time 5 https://ifconfig.me 2>/dev/null || true
}

ensure_env() {
  mkdir -p "$WALNUT_HOME"; chmod 700 "$WALNUT_HOME"
  if [ ! -f "$ENV_FILE" ]; then
    log "writing $ENV_FILE with fresh keys"
    local domain="${DOMAIN:-}" ip
    if [ -z "$domain" ]; then
      ip="$(public_ip)"
      [[ "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "could not detect the public IP; rerun with DOMAIN=<host>"
      domain="${ip//./-}.sslip.io"
    fi
    umask 077
    cat > "$ENV_FILE" <<EOF
# Walnut Internal Brain env (generated $(date -u +%FT%TZ) by deploy.sh). Keep secret. Mode 600.
# Template with explanations: deploy/docker/.env.example. Synthetic data only: never add real
# Slack/Atlassian/Google credentials here.
DOMAIN=$domain
HTTP_PORT=80
HTTPS_PORT=443
IB_DEMO_PASSCODE=${IB_DEMO_PASSCODE:-$(openssl rand -hex 8)}
IB_TOKEN_KEY=$(openssl rand -hex 32)
IB_LEDGER_KEY=$(openssl rand -hex 32)
MOCK_SVC_TOKEN=$(openssl rand -hex 32)
MOCK_ADMIN_TOKEN=$(openssl rand -hex 32)
MOCK_WEBHOOK_SECRET=$(openssl rand -hex 32)
# Optional AI model: empty = deterministic quoted answers only. See .env.example.
IB_MODEL_URL=
IB_MODEL_NAME=
IB_MODEL_KEY=
IB_MODEL_FALLBACKS=
IB_MODEL_DAILY_CAP_USD=
IB_MODEL_PRICE_IN_USD=
IB_MODEL_PRICE_OUT_USD=
IB_MODEL_ANSWER_TIMEOUT_S=
IB_MODEL_REASONING_EFFORT=
IB_FORCE_OFFLINE=0
IB_POLL_S=120
IB_ANCHOR_INTERVAL_S=900
IB_ANCHOR_FILE=
EOF
  else
    # explicit overrides passed on this run win; generated secrets are never regenerated
    [ -n "${DOMAIN:-}" ] && env_set DOMAIN "$DOMAIN"
    [ -n "${IB_DEMO_PASSCODE:-}" ] && env_set IB_DEMO_PASSCODE "$IB_DEMO_PASSCODE"
  fi
  chown root:root "$ENV_FILE"; chmod 600 "$ENV_FILE"
  local k v
  for k in DOMAIN IB_DEMO_PASSCODE IB_TOKEN_KEY IB_LEDGER_KEY MOCK_SVC_TOKEN MOCK_ADMIN_TOKEN MOCK_WEBHOOK_SECRET; do
    v="$(env_get "$k")"
    [ -n "$v" ] || die "$k is empty in $ENV_FILE"
    case "$v" in replace-with*) die "$k in $ENV_FILE is still a placeholder";; esac
  done
  for k in IB_TOKEN_KEY IB_LEDGER_KEY; do
    v="$(env_get "$k")"
    [ "${#v}" -ge 32 ] || die "$k must be at least 32 characters"
  done
  [ "$(env_get MOCK_SVC_TOKEN)" != "$(env_get MOCK_ADMIN_TOKEN)" ] || die "MOCK_SVC_TOKEN and MOCK_ADMIN_TOKEN must differ"
}

# --- 4. run ---------------------------------------------------------------------------------------
health_of() { docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$(dc ps -q "$1" 2>/dev/null)" 2>/dev/null || echo missing; }

wait_healthy() {
  local svc deadline=$(( $(date +%s) + ${WAIT_S:-900} )) st
  for svc in mock ib web; do
    printf 'waiting for %s ' "$svc"
    while :; do
      st="$(health_of "$svc")"
      [ "$st" = healthy ] && { echo "healthy"; break; }
      [ "$st" = unhealthy ] && { echo; dc logs --tail 80 "$svc"; die "$svc is unhealthy"; }
      [ "$(date +%s)" -lt "$deadline" ] || { echo; dc logs --tail 80 "$svc"; die "timed out waiting for $svc"; }
      printf '.'; sleep 5
    done
  done
  local domain url; domain="$(env_get DOMAIN)"; url="https://$domain/login"
  printf 'waiting for HTTPS on %s ' "$url"
  local k=(); [ "$domain" = localhost ] && k=(-k)
  while ! curl -fsS "${k[@]}" --max-time 10 -o /dev/null "$url" 2>/dev/null; do
    [ "$(date +%s)" -lt "$deadline" ] || { echo; dc logs --tail 80 caddy; https_help; die "HTTPS is not up on $domain (the app itself is running)"; }
    printf '.'; sleep 5
  done
  echo "up"
}

https_help() {
  local d; d="$(env_get DOMAIN)"
  cat >&2 <<EOF

HTTPS did not come up. In order:
 1. Vultr firewall group and ufw must allow TCP 80 and 443 from anywhere (Let's Encrypt connects to port 80).
 2. "rate limit" / "too many certificates" in the log above: use the same service under its other name:
      sudo DOMAIN=${d%.sslip.io}.nip.io bash $SRC/deploy/docker/deploy.sh
 3. Otherwise wait a few minutes and run this script again. Nothing is lost: it is safe to re-run.
EOF
}

run_smoke() {
  [ "${SKIP_SMOKE:-0}" = 1 ] && return 0
  log "smoke test"
  local domain ip; domain="$(env_get DOMAIN)"; ip="$(public_ip)"
  ENV_FILE="$ENV_FILE" PORT_CHECK_HOST="${PORT_CHECK_HOST:-${ip:-$domain}}" COMPOSE_PROJECT="$PROJECT" \
    SMOKE_INSECURE="$([ "$domain" = localhost ] && echo 1 || echo 0)" \
    bash "$SRC/deploy/docker/smoke.sh"
}

summary() {
  cat <<EOF

------------------------------------------------------------------------------
 Walnut Internal Brain is up:       https://$(env_get DOMAIN)
 Demo passcode:                     $(env_get IB_DEMO_PASSCODE)
 Model:                             $([ -n "$(env_get IB_MODEL_URL)" ] && [ -n "$(env_get IB_MODEL_NAME)" ] && echo "AI model $(env_get IB_MODEL_NAME), then the quoted answer" || echo "quoted answers only (no IB_MODEL_URL / IB_MODEL_NAME)")
 Env file (secrets, mode 600):      $ENV_FILE
 Status / logs:                     sudo bash $SRC/deploy/docker/deploy.sh status | logs ib
 Reset the demo:                    sudo bash $SRC/deploy/docker/deploy.sh reset
------------------------------------------------------------------------------
EOF
}

finish() {  # the URL and passcode are printed even when a check fails, so the failure can be looked at
  wait_healthy
  if ! run_smoke; then
    summary
    die "the stack is running but the smoke test failed: see the FAIL lines above (deploy.sh smoke repeats it)"
  fi
  summary
}

# --- 5. the optional model (any chat-completions-style endpoint; Vultr Serverless Inference preset) --
VULTR_INFERENCE_URL="https://api.vultrinference.com/v1"
host_python() { command -v python3 || command -v python || die "python3 is required for this step"; }

check_model() {  # check_inference.py reads the env file itself: the key never reaches argv or the log
  "$(host_python)" "$SRC/deploy/vultr/check_inference.py" --env-file "$ENV_FILE" "$@"
}

configure_model() {
  [ -f "$ENV_FILE" ] || die "run deploy first ($ENV_FILE is missing)"
  [ -t 0 ] || die "configure-model is interactive; run it in an SSH session"
  local preset="${1:-}" url key name fb cap effort timeout pin pout ans
  url="$(env_get IB_MODEL_URL)"
  effort="$(env_get IB_MODEL_REASONING_EFFORT)"; timeout="$(env_get IB_MODEL_ANSWER_TIMEOUT_S)"
  if [ "$preset" = vultr ]; then
    # Vultr's chat models all think first by default, which costs tokens and time: answers quote passages
    url="$VULTR_INFERENCE_URL"; effort="${effort:-none}"; timeout="${timeout:-30}"
  fi
  read -r -p "Model endpoint base URL [${url:-none}]: " ans; url="${ans:-$url}"
  [ -n "$url" ] || die "no endpoint given; nothing changed"
  read -r -s -p "API key (hidden; Enter keeps the current one): " key; echo
  [ -n "$key" ] || key="$(env_get IB_MODEL_KEY)"
  env_set IB_MODEL_URL "$url"; env_set IB_MODEL_KEY "$key"
  log "models this key may use"
  check_model --list || warn "could not list models (wrong key, or the endpoint has no /models)"
  name="$(env_get IB_MODEL_NAME)"; fb="$(env_get IB_MODEL_FALLBACKS)"; cap="$(env_get IB_MODEL_DAILY_CAP_USD)"
  read -r -p "Primary chat model id [${name:-none}]: " ans; name="${ans:-$name}"
  read -r -p "Fallback model ids, comma-separated [${fb:-none}]: " ans; fb="${ans:-$fb}"
  pin="$(env_get IB_MODEL_PRICE_IN_USD)"; pout="$(env_get IB_MODEL_PRICE_OUT_USD)"
  read -r -p "Input price, US\$ per million tokens, as listed above (makes the spend caps count) [${pin:-}]: " ans; pin="${ans:-$pin}"
  read -r -p "Output price, US\$ per million tokens [${pout:-}]: " ans; pout="${ans:-$pout}"
  read -r -p "Daily spend cap in USD (empty = built-in US\$5) [${cap:-}]: " ans; cap="${ans:-$cap}"
  env_set IB_MODEL_NAME "$name"; env_set IB_MODEL_FALLBACKS "$fb"; env_set IB_MODEL_DAILY_CAP_USD "$cap"
  env_set IB_MODEL_PRICE_IN_USD "$pin"; env_set IB_MODEL_PRICE_OUT_USD "$pout"
  env_set IB_MODEL_REASONING_EFFORT "$effort"; env_set IB_MODEL_ANSWER_TIMEOUT_S "$timeout"
  env_set IB_FORCE_OFFLINE 0
  log "testing the model with one synthetic, grounded prompt"
  check_model || warn "no configured model passed; the Brain will serve quoted answers until one does"
  log "restarting ib with the new model settings"
  dc up -d --no-build --force-recreate --no-deps ib   # not the mock: its world (and any tickets) stays
  finish
}

run_workflow() {  # the real-task workflow through the public edge (creates one ticket on the mock Jira)
  local domain; domain="$(env_get DOMAIN)"
  IB_DEMO_PASSCODE="$(env_get IB_DEMO_PASSCODE)" "$(host_python)" "$SRC/databridge/scripts/workflow_run.py"     --base "https://$domain" $([ "$domain" = localhost ] && echo --insecure) --approve "$@"
}

start_failed() {  # compose stops at the first unhealthy container without saying why
  dc ps || true
  dc logs --tail 60 || true
  die "docker compose up failed: see the build output or the service logs above. Safe to run this script again."
}

case "$ACTION" in
  deploy)
    if [ "${SKIP_INSTALL:-0}" != 1 ]; then install_prereqs; install_docker; ensure_swap; fi
    command -v docker >/dev/null 2>&1 || die "docker is not installed (unset SKIP_INSTALL, or install Docker first)"
    get_source; ensure_env
    log "starting the stack (first build takes several minutes)"
    if [ "${NO_BUILD:-0}" = 1 ]; then dc up -d --no-build --pull never --remove-orphans || start_failed
    else dc up -d --build --remove-orphans || start_failed; fi
    finish ;;
  reset)
    # Fresh synthetic world and an empty ledger/index. TLS certificates (caddy-data) are kept.
    log "resetting demo state (ledger, index, answer store, mock world)"
    dc stop web ib mock || true
    dc rm -f web ib mock || true
    docker volume rm "${PROJECT}_ib-var" 2>/dev/null || true
    dc up -d --no-build || start_failed
    finish ;;
  smoke)  run_smoke ;;
  status) dc ps ;;
  logs)   dc logs --tail "${TAIL:-200}" "$@" ;;
  down)   dc down ;;
  configure-model) configure_model "$@" ;;
  models)      check_model --list ;;
  check-model) check_model ;;
  workflow)    run_workflow "$@" ;;
  *) die "unknown action '$ACTION' (deploy | reset | smoke | status | logs [service] | down | configure-model [vultr] | models | check-model | workflow)" ;;
esac
