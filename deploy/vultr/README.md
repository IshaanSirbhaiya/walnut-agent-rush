# Deploy Walnut on Vultr

One **Vultr Cloud Compute** VM runs the whole stack with Docker Compose: Caddy (automatic HTTPS), the web
app, the Walnut Internal Brain service and the synthetic mock platforms. **Vultr Serverless Inference** is
an optional model behind Walnut's provider-neutral adapter, configured by environment only.

> **Status (honest):** this kit has **not yet been run on a live Vultr account** (none existed when it was
> written). What has been run: `cloud-init.yaml` with real cloud-init on a clean Ubuntu 24.04 userland (systemd
> in a container, with Docker installed from scratch by `deploy.sh`), ending in a passing smoke test, using
> Caddy's local CA instead of Let's Encrypt; see [docs/VULTR_RUN.md](../../docs/VULTR_RUN.md). Not run: the
> Vultr API calls, the firewall group, a real certificate, and any Serverless Inference call. Their request
> shapes were checked field by field against Vultr's published client and docs.

```
            Vultr firewall group (TCP 22 from your IP; TCP 80, 443 from anywhere)
                                  |
internet --443/80--> [ Vultr Cloud Compute VM, Ubuntu 24.04, Singapore ]
                       caddy (TLS: Let's Encrypt for <ip-with-dashes>.sslip.io)
                         └─> web :3100 (Next.js; same-origin /api/ib/* proxy)
                               └─> ib :8100 (Walnut Internal Brain: gates, grounding wall, ledger)
                                     ├─> mock :8200 (synthetic Slack/Confluence/Jira/Drive; internal network)
                                     └─> https://api.vultrinference.com/v1  (optional; OpenAI-compatible)
```

| Vultr service | What Walnut uses it for | Required? |
|---|---|---|
| **Cloud Compute** (Shared CPU, `vc2-2c-4gb`: 2 vCPU / 4 GB, region `sgp`) | Runs the backend (Brain + mock platforms) and the web app, in Docker | Yes (the track's VM backend and web deployment) |
| **Firewall group** | Only 22 (your IP), 80 and 443 reach the VM; the app's own ports are never published | Yes |
| **Cloud-Init user-data** | First boot installs Docker, clones the repo and runs `deploy/docker/deploy.sh` | Optional (or SSH in and run it) |
| **Serverless Inference** (OpenAI-compatible, `https://api.vultrinference.com/v1`) | Writes the answer from the permitted passages; the grounding wall checks every sentence; the quoted answer is the fallback | Optional |
| **Vultr API v2** | `provision.py` creates the firewall group, SSH key and VM in one command | Optional |

Cost at list price: the 2 vCPU / 4 GB plan is about US$20 a month, billed hourly, so a week of judging is
a few dollars of the hackathon credit. Serverless Inference is billed per token; Walnut's spend caps
(`IB_MODEL_DAILY_CAP_USD` with `IB_MODEL_PRICE_IN_USD` / `IB_MODEL_PRICE_OUT_USD`) bound it.

## 1. Before you start

- A Vultr account with the credit applied (Billing -> Promotions).
- This repository public on GitHub **before the VM boots** (cloud-init clones it once, at first boot). Otherwise
  use `deploy/docker/upload.sh`.
- An SSH key pair: `ssh-keygen -t ed25519 -f ~/.ssh/walnut_vultr -C walnut-vultr`. On Windows, run every command
  here in Git Bash. The key has a non-default name, so **every `ssh` below needs `-i ~/.ssh/walnut_vultr`**.

## 2. Create the VM: console (about 10 minutes)

1. **Account -> SSH Keys -> Add SSH Key**: paste `~/.ssh/walnut_vultr.pub`.
2. **Network -> Firewall -> Add Firewall Group** `walnut-web`, IPv4 rules: TCP 22 from **My IP**; TCP 80
   and TCP 443 from anywhere (Let's Encrypt needs 80). Nothing else.
3. **Deploy + -> Deploy New Server**: Cloud Compute, Shared CPU; **Singapore**; **Ubuntu 24.04 LTS x64**;
   **2 vCPU / 4 GB**; SSH key `walnut`; firewall group `walnut-web`; hostname `walnut-demo`.
   Optional: **Cloud-Init User-Data**: paste [`cloud-init.yaml`](cloud-init.yaml) with `REPO_URL` replaced
   by your repo's URL. Deploy.

**Or by API, in one command** (dry run first; it prints every request and sends nothing). First, Account -> API:
enable the API and add your IP under Access Control, or every call answers 401.

```bash
python deploy/vultr/provision.py --repo-url https://github.com/<you>/<repo>.git --ssh-key ~/.ssh/walnut_vultr.pub
VULTR_API_KEY=<key> python deploy/vultr/provision.py --repo-url ... --ssh-key ~/.ssh/walnut_vultr.pub --apply
```

It stops rather than start a second billed VM if one with the same label exists.

## 3. Deploy the stack

With cloud-init, the VM deploys itself on first boot (14 to 19 minutes on our clean-host test). Watch it:

```bash
ssh -i ~/.ssh/walnut_vultr root@<ip> 'tail -F /var/log/walnut-deploy.log'
```

The log appears about a minute in, once the packages are installed. If `ssh` is refused for the first minute or
so, the VM is still booting. Without cloud-init:

```bash
ssh -i ~/.ssh/walnut_vultr root@<ip>
apt-get update && apt-get install -y git
git clone --depth 1 https://github.com/<you>/<repo>.git /opt/walnut/repo
bash /opt/walnut/repo/deploy/docker/deploy.sh          # Docker, secrets, build, HTTPS, smoke test
```

or from your laptop (sends the committed source, no public repo needed):
`bash deploy/docker/upload.sh root@<ip>`.

It ends with `Smoke: N passed, 0 failed`, then the URL `https://<ip-with-dashes>.sslip.io` and the demo
passcode (generated on the VM; `grep IB_DEMO_PASSCODE /opt/walnut/walnut.env`). `deploy.sh` is safe to run again
at any point.

| If you see | Do |
|---|---|
| `Permission denied (publickey)` | Add `-i ~/.ssh/walnut_vultr`. Still refused: your IP changed, so edit the port 22 rule in the firewall group |
| `Connection timed out` on SSH | Same: the firewall group's port 22 rule must hold your current IP |
| `could not read Username` or `repository not found` in the log | The repo is not public yet. Make it public, then run the two commands in the block above |
| `walnut deploy FAILED` | The lines above it say why. Fix, then `bash /opt/walnut/repo/deploy/docker/deploy.sh` (or re-clone first if `/opt/walnut/repo` is empty) |
| Stuck at `waiting for HTTPS`, or `HTTPS is not up` | The script prints the steps: ports 80/443 in the firewall group, then, on a rate limit, `DOMAIN=<ip-with-dashes>.nip.io` (the same service under its other name; both are in Let's Encrypt's raised limit) |
| `apt-get ... failed (try n of 10)` | Normal on a fresh VM: unattended upgrades hold the lock. It retries |
| Plan unavailable or credit refused | `--plan vc2-2c-2gb` also works (`deploy.sh` adds swap); check Billing |

The stack's TLS account email is `ACME_EMAIL` (default `ishaan@walnut.sg`, in `docker-compose.yml`): Let's Encrypt
expiry notices go there, and setting it is what lets Caddy fall back to ZeroSSL.

> Vultr's Ubuntu images enable `ufw` with only SSH open. `cloud-init.yaml` opens 80/443; if you deploy by
> hand, run `ufw allow 80/tcp && ufw allow 443/tcp` (Docker-published ports usually bypass ufw, but the
> explicit rule keeps the intent clear). Never open 3100, 8100 or 8200.

**Before judges arrive:** `deploy.sh workflow` (section 5) files a real ticket and a sealed audit trail. That is
fine to leave in place; `deploy.sh reset` gives judges a clean ledger if you prefer one.

## 4. Optional: Vultr Serverless Inference

1. Console -> **Serverless -> Inference -> Add**. Copy the API key into your password manager.
2. On the VM:

   ```bash
   sudo bash /opt/walnut/repo/deploy/docker/deploy.sh configure-model vultr
   ```

   It pre-fills `IB_MODEL_URL=https://api.vultrinference.com/v1`, reads the key with hidden input, lists the
   chat models with their prices (Vultr's `/v1/models` also lists music, image and speech models; those are marked
   and left out), asks for a primary model, a fallback and the prices, tests one synthetic grounded prompt per
   model (`check_inference.py`: passes only when the reply keeps the `[C1]` citation format and arrives within the
   answer timeout), then restarts `ib` and runs the smoke test. It sets `IB_MODEL_REASONING_EFFORT=none` and a
   30 s answer timeout: see below.
3. Check any time: `deploy.sh models` (list) and `deploy.sh check-model` (test). The key stays in
   `/opt/walnut/walnut.env` (mode 600, outside the checkout); it is never in the repo, in user-data or on
   a command line.

What the model sees and does is unchanged from the no-model build: only passages that passed both
permission gates are sent; the grounding wall drops any unsupported value or name; on any failure,
timeout or cap, the deterministic quoted answer is served, and every answer says which path wrote it.
**Reasoning.** Vultr's chat models think first by default. The thinking comes back in `message.reasoning`, and
its tokens count against the same limit as the answer, so a thinking model is slower and can run out of budget,
and Walnut would then quietly serve the quoted answer. Answering from given passages needs no thinking, so
`configure-model vultr` turns it off (`reasoning.effort: none`; a few models think regardless, and the check says
so). A flash model is a sensible first try, for example `glm-5.3-flash`, `qwen3.8-flash-next` or `mimo-v2.6-flash`
(all in the public catalogue on 6 Nov 2026; `deploy.sh models` shows today's). No model has been evaluated yet: check
that answers say "AI model" in the UI, and if they say "quoted", run `deploy.sh check-model`.

## 5. Run the real task on the deployment

```bash
sudo bash /opt/walnut/repo/deploy/docker/deploy.sh workflow
# or from anywhere: IB_DEMO_PASSCODE=<passcode> python databridge/scripts/workflow_run.py --base https://<ip-with-dashes>.sslip.io
```

The procurement workflow, end to end through the public edge: ask -> cited, permission-checked answer
-> approval note drafted (never sent) -> ticket proposed -> **human approval** -> ticket created once ->
compliance pulls the audit trail and verifies the hash chain -> a contractor gets the constant refusal.
See [README.md](../../README.md#walnut-on-vultr-the-real-task).

## 6. After judging

Console -> the server -> **Destroy** (or `python deploy/vultr/provision.py --destroy <instance-id> --apply`),
and remove the Serverless Inference subscription; both bill until removed.
