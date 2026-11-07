# CHANGES: what this entry changed versus `Competitions/_base`

This is also the **pre-existing-work disclosure**. `_base` is Walnut DataBridge, neutral edition, built by the
Walnut team from August 2026, before Vultr Agent Rush (3 to 8 Nov 2026). It was imported unchanged as the first
commit of `repo/` (`c995d3e`, "Import Walnut DataBridge neutral base (pre-existing work, unchanged)"). Everything
after that commit is new work for this hackathon.

**Size of the change:** 28 files, about 2,550 lines added and 44 removed (`git diff --stat c995d3e HEAD`). Most of it is the deploy kit, the workflow runner,
tests and docs. In the code `_base` shipped, the changes are the ones listed under "Changed files" and "Fixes after the
audit": one setting in `databridge_ib/llm.py`, and small fixes in the web app. `databridge/packages/**` is byte-identical to `_base`. The Brain's gates, grounding,
ledger, connectors, mock platforms and synthetic world are **unchanged**.

## New files

| File | What it is |
|---|---|
| `deploy/vultr/README.md` | The Vultr deployment guide: Vultr services used, console steps (SSH key, firewall group, Cloud Compute VM in Singapore), cloud-init or by-hand deploy, Serverless Inference setup, running the real task, tear-down. States plainly that it has not yet run on a live Vultr account |
| `deploy/vultr/cloud-init.yaml` | Vultr Cloud-Init user-data: packages, ufw 22/80/443 (Vultr Ubuntu images ship with ufw on and only SSH open), clone, `deploy.sh deploy`. No secret in it, on purpose |
| `deploy/vultr/provision.py` | Vultr API v2 provisioning (standard library): firewall group with SSH from the operator's IP only, SSH key, Ubuntu 24.04 VM `vc2-2c-4gb` in `sgp` with the cloud-init as user-data, wait for the IP, print the sslip.io URL; `--destroy`. **Dry run by default**; `--apply` needs `VULTR_API_KEY` |
| `deploy/vultr/check_inference.py` | Checks an OpenAI-compatible endpoint (Vultr Serverless Inference preset with `--vultr`): `/models` list (flags non-chat models), one synthetic grounded prompt per configured model, flags `<think>` output or a dropped `[C1]` tag. Reads the key from the env or the env file; never prints it |
| `databridge/scripts/workflow_run.py` | The real-task runner (standard library): procurement workflow (ask, cited answer, approval-note draft, ticket proposal, human approval gate, single execution, compliance audit pull and chain verify, contractor contrast) and a support workflow (`--scenario support`). Works through a deployment's public edge (`--base`) or directly against a Brain (`--ib`); `--approve`/`--reject`/prompt; `--json` report; exit 0 only when every check passes. Through an edge it also checks the ticket's source links point back at that edge |
| `databridge/apps/internal_brain/tests/test_workflow_run.py` | 7 tests: the runner against the app `bootstrap.build_app` builds, over the real in-process mock platforms and connectors (approve, decline, no-terminal means not approved, support refusal with no FinCrime leak, report shape, CLI guards) |
| `databridge/apps/internal_brain/tests/test_vultr_kit.py` | 12 tests: the provider-neutral adapter, configured by env only, answering through a real local HTTP server in the OpenAI-compatible shape (bearer key, `/v1/chat/completions`, no restricted canary sent); a citation-breaking model falls back to the quoted answer; `check_inference.py` (pass, `<think>` flagged, wrong key, env file, preset only when asked); `provision.py` dry-run plan (order, firewall rules, SSH /32, user-data filled); static checks (cloud-init YAML, only Caddy publishes ports, model env reaches `ib`, Host allowlists, no key in the kit) |
| `docs/VULTR_RUN.md` | Evidence of the local Docker run: containers, smoke test 32/32 through Caddy, both workflows through the edge, the backend test-suite result |
| `docs/AGENT_RUSH_CHANGES.md` | A copy of this file inside the repository, for judges |
| `LICENSE.MIT.proposed` | A proposed MIT licence, marked NOT IN EFFECT; needs Ishaan's and Dev's sign-off before it replaces `LICENSE` (Apache-2.0, unchanged) |
| `.gitattributes` | LF line endings for shell scripts, compose/YAML, the Caddyfile and Dockerfiles (they run on Linux) |

## Changed files

| File | Change |
|---|---|
| `README.md` | New top section for judges: the problem, **the real task** (8-step table and commands), **Vultr services used**, **architecture on one Vultr VM** (mermaid), proof table, **prior work disclosed**, licence note. The previous intro moved under "About Walnut DataBridge"; the rest of the README is unchanged apart from one sentence in §7 Deploy pointing at `deploy/vultr/` |
| `STATUS.md` | Docker deployment "Written" -> "Built and run locally"; two new rows (Vultr deploy kit; workflow runner) |
| `deploy/docker/docker-compose.yml` | **Bug fixes found by running the kit for the first time:** `MOCK_ALLOWED_HOSTS: mock` and `IB_ALLOWED_HOSTS: ib` (the Host allowlists refused in-stack traffic, so the Brain indexed nothing and every API call was a 400), and `IB_PUBLIC_ORIGIN` now also reaches `ib` (ticket source links pointed at `127.0.0.1:3100`). New: `IB_MODEL_PRICE_IN_USD`, `IB_MODEL_PRICE_OUT_USD`, `IB_MODEL_ANSWER_TIMEOUT_S` pass through; `WALNUT_IMAGE_PREFIX` (default `walnut`) and an `IB_PUBLIC_ORIGIN` override for local tests on non-standard ports; comments name Vultr Serverless Inference as one option |
| `deploy/docker/deploy.sh` | New operations: `configure-model [vultr]` (endpoint, hidden key input, model list, grounded test, restart `ib`, smoke), `models`, `check-model`, `workflow` (runs `workflow_run.py` through the public edge). Public IP from the Vultr metadata service first, then the echo services. The generated env file gains `IB_MODEL_DAILY_CAP_USD` and the two price keys |
| `deploy/docker/.env.example` | A commented Vultr Serverless Inference example (`IB_MODEL_URL=https://api.vultrinference.com/v1`), price and timeout keys, local-test keys |
| `deploy/docker/README.md` | The `configure-model` quick path in §3, the new operations in the file table, a "run the real-task workflow" row |
| `databridge/apps/internal_brain_web/lib/personas.ts` | One extra starter question for the IT admin persona: the procurement question (the existing first starter is kept, so the persona tests still hold). Header label: see below |

## Fixes after the audit of 6 Nov 2026

| File | Change and why |
|---|---|
| `databridge/apps/internal_brain_web/components/user/answerText.ts` | **Bug:** on quoted answers (`S. [C1]`) every citation chip attached to the next sentence. Tags now move before the full stop first |
| `databridge/apps/internal_brain_web/lib/personas.ts`, `lib/i18n/user.ts` | Alex's header read "IT admin — Platform simulator" under "Good morning, Alex". Now "Alex — IT admin". The simulator stays labelled: the sign-in note, the Simulator nav item and page |
| `databridge/apps/internal_brain_web/app/login/page.tsx` | Alex landed on the simulator, with no question box, so the demo path did not work as written. Everyone lands on Ask |
| `databridge/apps/internal_brain_web/components/shell/nav.ts`, `deploy/docker/Dockerfile.web` | The deployed image hides nav links to the two pages the edge does not serve |
| `databridge/scripts/workflow_run.py`, `personas.ts` | New demo question: the old one pulled in card-limit and course sentences. New ticket summary: the old one repeated the question, so after two runs the answer cited only the last ticket and no policy |
| `databridge/apps/internal_brain/databridge_ib/llm.py` | `IB_MODEL_REASONING_EFFORT`: when set, sent as `reasoning.effort` (Vultr's chat models think by default, which costs budget and time). Off by default, provider-neutral. `databridge/packages/**` stays unmodified, per AGENTS.md |
| `deploy/vultr/check_inference.py` | Checked against Vultr's docs: chat models filtered by `output_modalities` (the catalogue holds music, image and speech models), prices listed, reasoning sent and reported, a 1,000-token budget since thinking counts against it, too-slow models fail, the endpoint's error message shown |
| `deploy/docker/deploy.sh` | apt retry (fresh-VM lock), swap on a 4 GB VM, URL and passcode printed even if the smoke test fails, HTTPS next steps, compose failure shows logs; `configure-model` asks for prices and sets reasoning off and a 30 s timeout for Vultr, and no longer restarts the mock |
| `deploy/docker/Caddyfile`, `docker-compose.yml`, `.env.example`, `smoke.sh` | `/eval_summary.json` served (Trust centre read a 404); `ACME_EMAIL` (Caddy 2.8 needs it for its ZeroSSL fallback); the reasoning setting passes through; a smoke check for the summary |
| `deploy/vultr/cloud-init.yaml` | One log for every step, so a clone failure is visible; `HOME` set; no UDP 443 |
| `deploy/vultr/provision.py` | No UDP 443 rule (Caddy serves h1/h2 only); refuses a second VM with the same label; User-Agent; `ssh -i` in its next steps |
| `deploy/vultr/README.md`, `deploy/docker/README.md`, `README.md`, `STATUS.md`, `docs/VULTR_RUN.md` | SSH commands with `-i`, a failure table, API key access control, corrected claims (`web` does have a route out; Caddy's fallback needs an email; there are no "instruct" models), the clean-host evidence |
| `databridge/apps/internal_brain_web/tests/e2e/answer-text.spec.ts`, `pure.config.ts` | New: 9 tests, no browser or server |
| `tests/test_vultr_kit.py`, `tests/test_workflow_run.py` | New tests, including a local server answering in the shapes Vultr documents, field names checked against Vultr's published client, and repeat workflow runs |

## What was not changed

- The Brain's gates, grounding wall, ledger, connectors and policy code. The Vultr integration is configuration
  (`IB_MODEL_URL`/`IB_MODEL_NAME`/`IB_MODEL_KEY`/`IB_MODEL_FALLBACKS`/`IB_MODEL_REASONING_EFFORT`), deploy tooling and
  documentation, as the repo's own rule 9 (no vendor lock-in, no vendor SDK or default) requires. The Vultr URL appears
  only in the deploy kit and docs as a documented preset, never as a default in product code.
- No key, token, passcode or `.env` file is in the repository. Local test env files lived outside the repo. `ACME_EMAIL`
  defaults to the public contact address.
- The eval numbers quoted (0 leaks in 7,374, and so on) are the pre-existing 30 Oct 2026 synthetic evaluation
  with a capturing test model; no Vultr model has been evaluated.

## Tests

Commands: `PY -m pytest <file> -q` from `databridge/` with the README's `PYTHONPATH`; on Windows the shared venv.

| What | Result (6 Nov 2026) |
|---|---|
| `tests/test_vultr_kit.py` (new) | 24 passed |
| `tests/test_workflow_run.py` (new) | 9 passed |
| `tests/e2e/answer-text.spec.ts` (new; `npx playwright test -c tests/e2e/pure.config.ts`) | 9 passed |
| `packages/harness/tests` (unchanged package) | 44 passed |
| `test_llm_chain`, `test_model_config`, `test_model_guard`, `test_model_labels`, `test_model_live` (the code beside the one-line change in `llm.py`) | 55 passed, 8 failed. The 8 are `test_demo_up_refuses_...`, which shell out through Git Bash: the same failures recorded on 5 Nov as identical on unchanged `_base` |
| `npx tsc --noEmit` in the web app | clean |
| Smoke through the Docker stack's TLS edge | 33 of 33, on the clean-Ubuntu host and on Docker Desktop |
| Workflows through the edge | procurement 7 of 7, support 7 of 7 |

Not re-run after these fixes: the whole backend suite (memory on this machine; last full run, 5 Nov: 1,474 passed, 10 failed,
2 skipped, the 8 above plus 2 timing-sensitive that pass alone) and the browser e2e suite against the app. Browser e2e
specs that mention Alex's old label or landing page were checked by reading them: `sim.spec.ts` navigates to `/sim` itself.
