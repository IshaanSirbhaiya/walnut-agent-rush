# Deploy Internal Brain with Docker

A hardened docker-compose stack for any Linux host with Docker: a VM at any cloud provider, a server
of your own, or Docker Desktop for a local test. The local run in [README.md](../../README.md#1-run-it)
needs none of this.

**Short version:**

1. A Linux host: 2 vCPU and 2 to 4 GB RAM, SSH access, Docker (or Ubuntu/Debian, where `deploy.sh`
   installs Docker).
2. Firewall: TCP 22, 80 and 443 only.
3. Deploy: `bash deploy/docker/upload.sh user@<HOST>` from your laptop (section 2).
4. Smoke test: `deploy.sh smoke` on the host, or `smoke.sh` from your laptop (section 5).

Everything in the stack is synthetic ("Company A"): the Brain talks only to the in-stack mock Slack,
Confluence, Jira and Drive. There is no setting for a real workspace, and none must be added.

```
internet ──TCP 80/443──▶ caddy (TLS, headers, path allowlist)
                           └─▶ web :3100  (Next.js; browser calls same-origin /api/ib/* only)
                                 └─▶ ib :8100  (Internal Brain API, ledger in volume ib-var)
                                       └─▶ mock :8200 (synthetic platforms, signed webhooks back to ib)
```

Only Caddy publishes ports. `ib`, `mock` and `web` have no host ports, and `mock` sits on an
internal-only Docker network with no route to the internet. `web` shares Caddy's network, which has one, but
calls only `ib`. `ib` calls out only to an AI model endpoint, and only when you configure one.

| File | What it is |
|---|---|
| `deploy.sh` | Idempotent installer and operator: `deploy` (default), `reset`, `smoke`, `status`, `logs [svc]`, `down`, `configure-model [vultr]`, `models`, `check-model`, `workflow` |
| `upload.sh` | Run on your laptop: sends the committed source to the host (`git archive`) and runs `deploy.sh` |
| `smoke.sh` | Checks the live URL: edge, sign-in, a cited answer, the constant refusal, closed ports |
| `docker-compose.yml` | The four services, networks and volumes |
| `Caddyfile` | TLS for `$DOMAIN`, security headers, the only public routes |
| `Dockerfile.ib` | python:3.13-slim image for `ib` and `mock` (trimmed deps, import-checked at build) |
| `Dockerfile.web` | Node 20 multi-stage build to a Next.js standalone server |
| `requirements-ib.txt` | The top-level Python packages the two services need; every package is pinned by `databridge/requirements-lock.txt` at install |
| `.env.example` | Every setting, with no real secrets |

`docker-compose.yml` sets `IB_PUBLIC_ORIGIN` to `https://$DOMAIN` for the `web` service, so the proxy
accepts browser requests only from the address you deploy to.

## 1. Prepare the host

1. Any x86_64 or arm64 Linux host. Ubuntu 22.04 / 24.04 or Debian 12 lets `deploy.sh` install Docker
   Engine, compose and buildx from Docker's apt repo. On anything else, install Docker with the compose
   and buildx plugins yourself and pass `SKIP_INSTALL=1`.
2. 2 vCPU / 4 GB is comfortable. 2 vCPU / 2 GB works: `deploy.sh` adds a 2 GB swap file for the web
   build, or you can build the images on your laptop (section 6).
3. Firewall (your provider's security group, or `ufw`): keep only TCP **22** (SSH; your own IP if you
   can), **80** (HTTP: Let's Encrypt validation, then a redirect to HTTPS) and **443** (HTTPS). Never
   open 8100, 8200 or 3100.
4. Check that you can log in: `ssh user@<HOST>`.

## 2. Deploy

**Option A (recommended): upload from your laptop.** It sends exactly the files you have committed, so
the host runs the version you tested. From the repo root, in Git Bash, macOS or Linux:

```bash
bash deploy/docker/upload.sh user@<HOST>
```

That copies the source to `/opt/walnut/repo` and runs `deploy.sh` there. Re-run it after every new commit.

**Option B: let the host clone the repo.** Pipe `deploy.sh` to the host with the repo's URL:

```bash
ssh user@<HOST> 'sudo REPO_URL=<git url> BRANCH=main bash -s' < deploy/docker/deploy.sh
```

For a private repo, use an SSH URL with a read-only deploy key on the host. Update later with
`sudo bash /opt/walnut/repo/deploy/docker/deploy.sh`, which pulls the latest commit.

**What `deploy.sh` does** (safe to re-run): installs Docker if missing (unless `SKIP_INSTALL=1`); adds
swap on small hosts; gets the source; writes `/opt/walnut/walnut.env` (mode 600) **only if it does not
exist**, with fresh keys from `openssl rand -hex 32` and a random demo passcode; runs
`docker compose up -d --build`; waits for health and for HTTPS; runs `smoke.sh`; prints the URL and the
passcode. The first run takes about 10 minutes (image builds, then the Brain indexes the whole world).

**Address.** Without a domain, the URL is `https://<ip-with-dashes>.sslip.io` (sslip.io resolves that
name to your IP, and Caddy gets a Let's Encrypt certificate for it). To use your own domain, create an
A record pointing at the host, then run `deploy.sh` with `DOMAIN`:

```bash
ssh user@<HOST> 'sudo DOMAIN=brain.example.com bash /opt/walnut/repo/deploy/docker/deploy.sh'
```

## 3. Optional: plug in an AI model

Without a model, every answer is the deterministic answer quoted from the permitted sources, and
everything works. To have a model write the answers, use any chat-completions-style JSON endpoint
(hosted, or a model server you run yourself).

**Quickest:** `sudo bash /opt/walnut/repo/deploy/docker/deploy.sh configure-model` asks for the endpoint
URL and the key (hidden input), lists the endpoint's models, tests each chosen model with one synthetic
grounded prompt, and restarts `ib`. `configure-model vultr` pre-fills Vultr Serverless Inference
(`https://api.vultrinference.com/v1`; see [../vultr/README.md](../vultr/README.md)). `models` and
`check-model` repeat the list and the test. By hand:

1. Edit the env file on the host (not a command line, where a key would land in shell history):
   ```bash
   ssh user@<HOST>
   sudo nano /opt/walnut/walnut.env   # IB_MODEL_URL=..., IB_MODEL_NAME=..., IB_MODEL_KEY=... (optional)
   sudo bash /opt/walnut/repo/deploy/docker/deploy.sh
   ```
2. `IB_MODEL_FALLBACKS` (comma-separated model names) are tried in order if the first fails; the quoted
   answer is the last fallback. Optional spend and rate caps: `IB_MODEL_CAP_USD`,
   `IB_MODEL_DAILY_CAP_USD`, `IB_MODEL_RPM`, `IB_MODEL_USER_RPM` (the spend ledger lives in its own
   volume, `ib-guard`, and survives `reset`).
3. The smoke output line `model:` and each answer in the UI show which path answered.

Only passages that passed both permission gates are ever sent. To switch the model off again, set
`IB_FORCE_OFFLINE=1` (or empty `IB_MODEL_URL`) and re-run `deploy.sh`.

## 4. Use it

Open the URL, enter the passcode and pick a persona (all synthetic): `jdoe` engineer, `priya.sre` SRE,
`ken.ext` contractor, `sara.sec` security, `leo.ops` ops, `amy.am` account manager, `mlro.tan` (Rachel)
money-laundering reporting officer, `maya.compliance` compliance officer, `admin.it` (Alex) IT admin, who also
operates the platform simulator. The
walk-through is in [INTERNAL_BRAIN.md](../../INTERNAL_BRAIN.md#walk-through).

> **Signing in on the public URL.** The API requires `IB_DEMO_PASSCODE`. The sign-in page has a
> **Demo passcode** field: enter the passcode `deploy.sh` printed, then pick a person. Compare reuses
> it for its second person, so it is asked for once.

Show the passcode again: `ssh user@<HOST> 'sudo grep IB_DEMO_PASSCODE /opt/walnut/walnut.env'`.
Rotate it: `ssh user@<HOST> 'sudo IB_DEMO_PASSCODE=<new> bash /opt/walnut/repo/deploy/docker/deploy.sh'`.

Public pages: `/`, `/login`, `/history`, `/settings`, `/value`, `/compare`, `/map`, the Developer pages
under `/dev` (except `/dev/brain`, whose engine gateway is not part of this stack, and `/dev/styleguide`; the
image's nav hides both), and the redirects `/audit` and `/sim`. Every number on them still comes from the backend under the signed-in person's
own permissions.

## 5. Reset, update, stop

| Task | Command (on the host, or wrap in `ssh user@<HOST> '...'`) |
|---|---|
| Run the real-task workflow (procurement: ask, cited answer, draft, ticket on approval, audit pull) through the public edge | `sudo bash /opt/walnut/repo/deploy/docker/deploy.sh workflow` |
| Reset (fresh synthetic world, empty ledger, index and answer store; certificates and model spend ledger kept) | `sudo bash /opt/walnut/repo/deploy/docker/deploy.sh reset` |
| Run the smoke test again | `sudo bash /opt/walnut/repo/deploy/docker/deploy.sh smoke` |
| Status / logs | `sudo bash /opt/walnut/repo/deploy/docker/deploy.sh status` / `... logs ib` |
| Deploy new commits | `bash deploy/docker/upload.sh user@<HOST>` from your laptop (or re-run the Option B command) |
| Stop (keeps data) | `sudo bash /opt/walnut/repo/deploy/docker/deploy.sh down` |

The simulator's own "reset" (as `admin.it`) reloads only the mock world; `deploy.sh reset` also clears
the ledger.

Smoke from your laptop (a real outside view, including the closed-port check):

```bash
BASE_URL=https://<ip-with-dashes>.sslip.io IB_DEMO_PASSCODE=<passcode> bash deploy/docker/smoke.sh
```

## 6. Build the images on your laptop instead (small host, or no build on the host)

Match the host's architecture (for an x86_64 host on Apple Silicon, first
`export DOCKER_DEFAULT_PLATFORM=linux/amd64`). From the repo root:

```bash
docker compose -p walnut --env-file deploy/docker/.env.example -f deploy/docker/docker-compose.yml build
docker save walnut-ib:latest walnut-web:latest | gzip | ssh user@<HOST> 'gunzip | sudo docker load'
NO_BUILD=1 bash deploy/docker/upload.sh user@<HOST>
```

(`.env.example` only satisfies the compose file's required variables for the build; no secret goes into
an image. On a brand-new host, install Docker before `docker load`.)

The web app alone, without Docker: `cd databridge/apps/internal_brain_web && npm ci && NEXT_OUTPUT=standalone npm run build`,
then `.next/standalone/server.js` with `.next/static` copied to `.next/standalone/.next/static`
(that is what `Dockerfile.web` does).

## 7. Try the whole stack locally first (optional)

With Docker Desktop, using ports that do not clash with a dev setup:

```bash
cp deploy/docker/.env.example deploy/docker/.env
# edit deploy/docker/.env: DOMAIN=localhost, HTTP_PORT=18080, HTTPS_PORT=18443, and replace every
# replace-with-... value with `openssl rand -hex 32` (passcode: `openssl rand -hex 8`)
docker compose -p walnut-local --env-file deploy/docker/.env -f deploy/docker/docker-compose.yml up -d --build
BASE_URL=https://localhost:18443 SMOKE_INSECURE=1 COMPOSE_PROJECT=walnut-local \
  ENV_FILE=deploy/docker/.env bash deploy/docker/smoke.sh
docker compose -p walnut-local --env-file deploy/docker/.env -f deploy/docker/docker-compose.yml down -v
```

`DOMAIN=localhost` makes Caddy use its own local CA, hence `SMOKE_INSECURE=1`. `deploy/docker/.env`
is git-ignored.

## 8. What the deployment enforces

| Control | Where |
|---|---|
| `IB_DEPLOYED=1` (refuses dev or short keys; `Secure` session cookie) and `IB_DEMO_LOGIN=1` are fixed, not settable from the env file | `docker-compose.yml` (`ib.environment`) |
| The stack refuses to start without `IB_DEMO_PASSCODE` and the keys | `${VAR:?}` in `docker-compose.yml`; checks in `deploy.sh` `ensure_env` |
| Keys generated per host, never in git; env file mode 600 outside the checkout | `deploy.sh` `ensure_env` |
| Synthetic platforms only: `IB_MOCK_BASE=http://mock:8200`, no real platform variables passed | `docker-compose.yml` |
| Only 80/443 published; IB and mock unreachable from outside | `docker-compose.yml` (no `ports:` except caddy); `smoke.sh` checks 8100/8200/3100 and `docker ps` |
| No outbound network for `mock`; `web` has a route (it shares Caddy's network) but calls only `ib`; `ib` calls out only to a configured model endpoint | `docker-compose.yml` networks (`backend` is `internal: true`) |
| Public paths: the app's pages, `/_next/static/*`, `/api/ib/*`; everything else 404 | `Caddyfile`; `smoke.sh` probes IB and mock paths |
| The web proxy's own allowlist (no `/webhooks`) | `databridge/apps/internal_brain_web/app/api/ib/[...path]/route.ts` |
| HSTS, CSP, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, `noindex`; no `Server` header | `Caddyfile` |
| Request body capped at 64 KB; header and body read timeouts | `Caddyfile` |
| Containers: non-root (`ib` uid 10001, `node`), read-only root filesystem, all capabilities dropped, `no-new-privileges` | `Dockerfile.ib`, `Dockerfile.web`, `docker-compose.yml` |
| No model SDK in the image; the optional model is reached over plain HTTPS | `requirements-ib.txt` |

**Rate limiting is not built in at the edge.** Stock Caddy has no rate limiter (it is the third-party
`caddy-ratelimit` plugin, which needs a custom Caddy build). The passcode is the gate on who can ask
questions; model calls are bounded by the `IB_MODEL_*` caps and your provider's own limits. If the URL
is shared widely, rotate the passcode, or `reset`/`down` the stack.

**Ledger anchoring.** The external head defaults to a file in the same volume, which is not off-host.
`IB_ANCHOR_FILE` can point elsewhere inside the container (for example a mounted network share);
making it truly off-host is not set up by this kit.

## 9. Troubleshooting

| Symptom | Check |
|---|---|
| `deploy.sh` stops at "waiting for HTTPS" | Ports 80 and 443 open in the host firewall? `deploy.sh logs caddy` shows the ACME error. With your own domain, the A record must already point at the host. The app is already running; the script prints the next steps. |
| Certificate errors with sslip.io | Let's Encrypt limits certificates per registered domain, and sslip.io is shared. Caddy falls back to ZeroSSL (it needs the account email, `ACME_EMAIL`, set in `docker-compose.yml`). Or use the same service under its other name: `DOMAIN=<ip-with-dashes>.nip.io` and re-run `deploy.sh`. Your own domain avoids it. |
| `ib` unhealthy or slow to start | It crawls and indexes the whole world before it answers `/health` (about a minute, longer on 2 vCPU). `deploy.sh logs ib`. |
| `refusing to start: set strong values for IB_TOKEN_KEY` | The env file has a short or dev key. Generate a new one with `openssl rand -hex 32`. |
| Build killed (out of memory) | 2 GB host: make sure swap is on (`swapon --show`), or build on your laptop (section 6). |
| UI says "temporarily unavailable" at sign-in | Wrong or missing passcode (the API returns 401), or `ib` is down (`deploy.sh status`). |
| `503 {"error":"temporarily unavailable"}` on ask | The Brain failed closed (for example a ledger error). `deploy.sh logs ib`. |
| Answers say "quoted from sources" with a model configured | `IB_MODEL_URL` / `IB_MODEL_NAME` empty, `IB_FORCE_OFFLINE=1`, the endpoint unreachable, or a cap reached. `deploy.sh logs ib`. |
| Audit verify reports problems after you edited the env file | `IB_LEDGER_KEY` changed after the ledger was written. Run `deploy.sh reset`. |
| `git pull failed` | Someone changed files in `/opt/walnut/repo`. Use `upload.sh`, which replaces the directory. |
| Need to look inside | `sudo docker compose -p walnut --env-file /opt/walnut/walnut.env -f /opt/walnut/repo/deploy/docker/docker-compose.yml ps` |
