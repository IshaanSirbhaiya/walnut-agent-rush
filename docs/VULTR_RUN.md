# The Vultr deploy kit, run: evidence

**None of this is a live Vultr deployment.** No Vultr account existed when it was run, and no Vultr credential has
been used. All data is synthetic.

## 1. First boot on a clean Ubuntu 24.04 system (6 Nov 2026)

The closest test possible without an account: the exact user-data `provision.py` sends, through **real cloud-init**,
on a host with nothing installed.

| | |
|---|---|
| Host | `ubuntu:24.04` userland, systemd as PID 1, in a privileged container on Docker Desktop. No git, curl, ufw or Docker |
| Run as | `cloud-init init --local`, `init`, `modules --mode config`, `modules --mode final`, inside a systemd service, so no login environment |
| What it did | apt packages, ufw on (22, 80, 443), `git clone --depth 1`, Docker Engine 29.9.3 and compose v5.7.0 from Docker's apt repo, secrets generated, both images built, four containers healthy |
| Time | 14 minutes 17 s and 18 minutes 41 s on two runs, on a laptop with under 1 GB of RAM free |
| Smoke | 33 of 33 (`deploy.sh` re-run on the same host after the last fix; the first-boot run before it scored 32 of 33 and found that fix) |
| Workflow | `deploy.sh workflow`: 7 of 7, more than once |
| `configure-model vultr`, no key, against the real endpoint | Listed Vultr's real catalogue: 12 chat models of 33, with prices. The test call got Vultr's real `401 No API key provided`, reported as such. `ib` restarted, the smoke test still passed, answers stayed quoted |

**What differs on a real VM, and so is not proven:** `DOMAIN=localhost` with Caddy's local CA instead of Let's Encrypt
(four smoke checks only run on a real host: plain HTTP redirect, ports 8100, 8200, 3100 closed, so expect 37 there); Vultr's
image and cloud-init datasource; the firewall group; the metadata IP lookup; `provision.py --apply`; any Serverless
Inference answer.

The audit's other finding from this rig: the kit's request shapes were compared field by field with Vultr's published
client (`vultr/govultr`) and docs (`api.vultrinference.com/docs`); plan `vc2-2c-4gb` in `sgp` at US$20 a month and
`Ubuntu 24.04 LTS x64` (id 2284) were confirmed on the public API. See `tests/test_vultr_kit.py`.

## 2. The stack on Docker Desktop

The same `deploy/docker/docker-compose.yml`, on host ports 4280/4243 with `IB_PUBLIC_ORIGIN=https://localhost:4243` and
`WALNUT_IMAGE_PREFIX=walnut-vultr`; no model configured (quoted answers). The video's footage comes from this run.

```bash
docker compose -p walnut-vultr --env-file <local env> -f deploy/docker/docker-compose.yml up -d --build
BASE_URL=https://localhost:4243 SMOKE_INSECURE=1 COMPOSE_PROJECT=walnut-vultr ENV_FILE=<local env> bash deploy/docker/smoke.sh
IB_DEMO_PASSCODE=<passcode> python databridge/scripts/workflow_run.py --base https://localhost:4243 --insecure --approve
IB_DEMO_PASSCODE=<passcode> python databridge/scripts/workflow_run.py --base https://localhost:4243 --insecure --scenario support --approve
```

Running the kit for the first time on 5 Nov found three bugs, fixed in `docker-compose.yml`: the Brain's Host allowlist
refused the web proxy (`IB_ALLOWED_HOSTS: ib`), the mock platforms' Host allowlist refused the Brain
(`MOCK_ALLOWED_HOSTS: mock`), and ticket source links pointed at `127.0.0.1:3100` instead of the public origin
(`IB_PUBLIC_ORIGIN` now also reaches `ib`).

### Containers (only Caddy publishes ports)

```
walnut-vultr-caddy-1	Up About a minute	0.0.0.0:4280->80/tcp, [::]:4280->80/tcp, 0.0.0.0:4243->443/tcp, [::]:4243->443/tcp
walnut-vultr-web-1	Up About a minute (healthy)	3100/tcp
walnut-vultr-ib-1	Up 2 minutes (healthy)	8100/tcp, 8200/tcp
walnut-vultr-mock-1	Up 2 minutes (healthy)	8100/tcp, 8200/tcp
```

### Smoke test through the public edge

```
Smoke test against https://localhost:4243
[edge]
  PASS  GET /login is 200 over HTTPS
  PASS  HSTS header present
  PASS  CSP header present
  PASS  no Server header
  PASS  web -> IB health via /api/ib/health
  PASS  Trust centre's evaluation summary is served
[nothing else is public]
  PASS  GET /health is 404 at the edge
  PASS  GET /docs is 404 at the edge
  PASS  GET /openapi.json is 404 at the edge
  PASS  GET /auth/whoami is 404 at the edge
  PASS  GET /ib/sources is 404 at the edge
  PASS  GET /audit/verify is 404 at the edge
  PASS  GET /sim/reset is 404 at the edge
  PASS  GET /admin/webhooks is 404 at the edge
  PASS  GET /slack/api/conversations.list is 404 at the edge
  PASS  GET /confluence/wiki/api/v2/spaces is 404 at the edge
  PASS  GET /jira/rest/api/3/search/jql is 404 at the edge
  PASS  GET /drive/v3/files is 404 at the edge
  PASS  POST /webhooks/slack is 404
  PASS  POST /admin/reset is 404
  PASS  POST /api/ib/webhooks/slack is 404
[sign-in]
  PASS  demo-login without the passcode is refused (401)
  PASS  demo-login with a wrong passcode is refused (401)
  PASS  ask without a session is 401
  PASS  demo-login as jdoe with the passcode
  PASS  session cookie is HttpOnly and Secure
[S1: unified answer with citations, as jdoe]
  PASS  S1 answered with 3 citation(s)
  PASS  S1 is not the refusal
        model: extractive-v1
  PASS  S1 answer omits the private-channel blocker (canary absent)
[S3: contractor gets the constant refusal, as ken.ext]
  PASS  demo-login as ken.ext
  PASS  S3 answer is exactly the constant refusal, no citations
[logout]
  PASS  logout revokes the session (whoami then 401)
[internal ports are closed from outside]
  SKIP  direct port check against localhost (local test; see the docker check below)
  PASS  only caddy publishes host ports (docker)

Smoke: 33 passed, 0 failed
```

### The real task: procurement workflow through the public edge

```
Walnut workflow: Procurement request: 12 laptops, about SGD 18,000
Target: https://localhost:4243   (synthetic data only)

[1] Sign in as the requester (admin.it)
      signed in as Alex Mercer (admin.it), roles employee, admin_it
      -> PASS (216 ms)

[2] Ask: permission-checked, cited answer (Gate 1 + live Gate 2 + grounding wall)
      Q: Who approves spend of SGD 18,000 on 12 laptops, and how many written quotes does the
      purchase take?
      A: Any purchase above SGD 10,000 needs three written quotes and an approved purchase order
      in the procurement tool before the supplier starts work. [C1] Spend up to SGD 500 is
      approved by your line manager, spend above SGD 500 also needs your department head, and
      anything above SGD 5,000 also needs the Head of Finance. [C3]
      [C1] confluence: Procurement: how to buy something (version 4)
      [C3] confluence: Approval limits for company spend (version 3)
      written by: quoted from sources (no model); request 3a3058060d3b430287fdcc6c03cd1c12
      -> PASS (226 ms)

[3] Draft the approval note to the department head from cited sentences only (never sent)
      Draft for your review (approval note to the department head; sent: False):
        | Hi,
        | Here is what our sources say. Any purchase above SGD 10,000 needs three written quotes
        | and an approved purchase order in the procurement tool before the supplier starts
        | work. Spend up to SGD 500 is approved by your line manager, spend above SGD 500 also
        | needs your department head, and anything above SGD 5,000 also needs the Head of
        | Finance.
        | Thanks,
        | Alex Mercer
      built by: deterministic/draft-template-v1; cites C1, C3
      -> PASS (171 ms)

[4] Propose a follow-up ticket (projects checked live; nothing created yet)
      proposed (nothing created yet): Task in ITHELP (IT Helpdesk); allowed projects checked live: ITHELP
        | Follow-up created from an Internal Brain answer.
        | Sources (each link opens only for people allowed to open that source):
        | Source 1: https://localhost:4243/api/ib/ib/open/9f3af9d41bb8705d6f584fef4d8b3556
        | Source 2: https://localhost:4243/api/ib/ib/open/74f5348d5520d0273ec6de9f00a3590e
        | Reference: 3a3058060d3b430287fdcc6c03cd1c12
      source links point at this deployment (https://localhost:4243): yes
      -> PASS (200 ms)

[5] Human approval gate, then execute once
      approved by admin.it -> created: ITHELP-12 "Hardware purchase: three written quotes, purchase order, department head and Head of Finance approval"
      -> PASS (254 ms)

[6] Audit pull as compliance (maya.compliance): journey, gate verdicts, sealed records, verify chain
      as Maya Fernandes (maya.compliance): request by admin.it, status released, policy ib-policy-1
      gate 2  verified / allow  confluence:cf-1228  cited
      gate 2  verified / allow  confluence:cf-1227  cited
      gate 2  verified / allow  jira:ITHELP-11  
      answer path: deterministic/extractive-v1; stage ms {"accept": 17, "compose": 2, "gate1": 25, "gate2": 56, "release": 6, "seal": 16}
      #32    request.accepted     68d4ad86a08016bd...
      #33    retrieval.decided    8d67c171467d4e0a...
      #34    answer.released      6ef021db86819c0b...
      #36    action.proposed      e9782cb8377487ce...
      #38    action.proposed      b11c0f8e757ea655...
      #39    action.confirmed     49ceb51908a21753...
      #40    action.executed      edf7043c59269880...
      verify audit chain: INTACT; 42 records; head cd5ee75ed67aa6fb...; off-host head match: True
      -> PASS (395 ms)

[7] Contrast: ken.ext asks the same question
      Ken Adeyemi (ken.ext, external contractor) asks the same question:
      A: I couldn't find an answer to that in the sources you can access.
      citations: 0 (the constant refusal; no hint the policy exists)
      -> PASS (312 ms)

Workflow PASSED: 7/7 steps
```

### The second scenario: support

```
Walnut workflow: Customer-support call: a restricted business account
Target: https://localhost:4243   (synthetic data only)

[1] Sign in as the requester (amy.am)
      signed in as Amy Lim (amy.am), roles employee
      -> PASS (184 ms)

[2] Ask: permission-checked, cited answer (Gate 1 + live Gate 2 + grounding wall)
      Q: Why has Velquarry Trading's account been restricted, and what should I tell the
      customer?
      A: Account managers should use this script for any customer whose account is restricted or
      under review, whatever the reason. [C1] Tell the customer only that their account is
      undergoing a routine review in line with our regulatory obligations, that we cannot share
      further details, and that we will contact them if we need anything else. [C1] Use the same
      words for every customer. [C1] Log the customer's question with the account review desk
      through the standard form; the desk replies within two business days. [C3]
      [C1] confluence: Customer account review: approved customer script (version 5)
      [C3] confluence: Customer account review: approved customer script (version 5)
      written by: quoted from sources (no model); request 06355d93fd284b03b97baa8287af6e86
      -> PASS (338 ms)

[3] Draft the reply to the customer from cited sentences only (never sent)
      Draft for your review (reply to the customer; sent: False):
        | Hello,
        | Thank you for getting in touch. Your account is undergoing a routine review in line
        | with our regulatory obligations. We cannot share further details. We will contact you
        | if we need anything else.
        | If you have any other questions, please let me know.
        | Kind regards,
        | Amy Lim
      built by: deterministic/approved-script-v1; cites C1
      -> PASS (124 ms)

[4] Propose a follow-up ticket (projects checked live; nothing created yet)
      refused at action time, as expected: A follow-up ticket can't be created from this answer. Nothing was changed.
      -> PASS (114 ms)

[5] Human approval gate, then execute once
      nothing to approve (no proposal)
      -> PASS (0 ms)

[6] Audit pull as compliance (maya.compliance): journey, gate verdicts, sealed records, verify chain
      as Maya Fernandes (maya.compliance): request by amy.am, status released, policy ib-policy-1
      gate 2  verified / allow  confluence:cf-1204  cited
      gate 2  verified / allow  slack:C0PRODUCT:1788424380.000456  
      gate 2  verified / allow  slack:C0PRODUCT:1782279960.001250  
      gate 2  verified / allow  slack:C0PRODUCT:1783211820.003122  
      gate 2  verified / allow  slack:C0PRODUCT:1785468720.000222  
      gate 2  verified / allow  slack:C0PRODUCT:1782542460.000314  
      gate 2  verified / allow  slack:C0PRODUCT:1791798120.002870  
      gate 2  verified / allow  slack:C0PRODUCT:1788052860.002765  
      gate 2  verified / allow  slack:C0PRODUCT:1789348200.001037  
      gate 2  verified / allow  slack:C0PRODUCT:1784534640.000827  
      gate 2  verified / allow  slack:C0PRODUCT:1781678760.000498  
      answer path: deterministic/extractive-v1; stage ms {"accept": 18, "compose": 4, "gate1": 24, "gate2": 170, "release": 5, "seal": 14}
      #49    request.accepted     1e3805970910d033...
      #50    retrieval.decided    a5b2e2c3482b6c77...
      #51    answer.released      23142e5b8339cbe7...
      #53    action.proposed      30b721ad1a4dd93f...
      #55    action.failed        c7a37d4c4dbb84f7...
      verify audit chain: INTACT; 57 records; head 51f2aa91b46f85ba...; off-host head match: True
      -> PASS (376 ms)

[7] Contrast: mlro.tan asks the same question
      Rachel Tan (mlro.tan) asks the same question: 3 citations, different permitted sources
      -> PASS (495 ms)

Workflow PASSED: 7/7 steps
```

## 3. Tests

See `docs/AGENT_RUSH_CHANGES.md`, "Tests", for the commands and the results of 6 Nov 2026, including what was not re-run.
