# Status

Product: **Walnut DataBridge**, with **Internal Brain** as the ask product inside it.
Start at [README.md](README.md) and [INTERNAL_BRAIN.md](INTERNAL_BRAIN.md). Every feature and its test:
[docs/FEATURE_CATALOGUE.md](docs/FEATURE_CATALOGUE.md). Changes by area:
[docs/CHANGELOG.md](docs/CHANGELOG.md).

This is the **neutral build**: no dependency on any AI vendor, model or hosting platform. It runs with no
model by default (the deterministic, quoted-evidence answer); an optional AI model plugs in through one
provider-neutral adapter (`IB_MODEL_URL`, `IB_MODEL_NAME`, `IB_MODEL_KEY`, optional
`IB_MODEL_FALLBACKS`).

## 1. Built

| Area | State | Where |
|---|---|---|
| Internal Brain service: two permission gates, grounding wall, write-ahead sealed log, one response shape | Built | `databridge/apps/internal_brain/` |
| Developer endpoints: `/ib/graph`, `/ib/graph/openable`, `/ib/doc/{id}`, `/ib/trace/{req}`, `/ib/status`, `/ib/ask/stream` (SSE stages), `/audit/stats`, `/audit/journey/{req}`, `/audit/tamper-demo` | Built | `databridge_ib/app.py`, `databridge_ib/audit/routes.py`; contract [backend_v1.md](docs/contracts/backend_v1.md) |
| Provider-neutral model adapter (chat-completions-style JSON over HTTPS; env only; no vendor SDK or default) | Built; off unless configured | `databridge_ib/llm.py`, `packages/harness` |
| Seeded demo history: about 300 replay-labelled questions through the real pipeline, with 2 real Gate-2 denials | Built | `databridge/scripts/seed_demo_activity.py` |
| Web app, User mode: sign-in, Ask with live stage events, sources sheet, History, Settings (English / 简体中文, accessibility), Compare, Value, voice dictation | Built | `databridge/apps/internal_brain_web/` |
| Web app, Developer mode: Mission control, Journey, Knowledge graph, Walnut engine, Analytics, Audit with sandbox tamper demo, Simulator, Trust centre | Built | same |
| Tours for both modes | Built | `components/tour/` |
| Security hardening: Host allowlist on the Brain and the mock, proxy refuses foreign Host and cross-site GETs, SSE gate events held until sealed, engine snapshot readable only by its own persona | Built | [FEATURE_CATALOGUE §7](docs/FEATURE_CATALOGUE.md#7-security-controls) |
| MCP servers for any MCP client (ask as a person; compliance audit), with per-persona `mcp.json` setup | Built | `databridge_ib/mcp_server.py`, `databridge_ib/audit_mcp_server.py`, `databridge/scripts/mcp_client_setup.py` |
| Act: draft a reply or a follow-up ticket, created only after the person confirms | Built and tested | `databridge_ib/actions.py`; [backend_v1.md](docs/contracts/backend_v1.md) |
| Live graph growth and add-document (demo-only: `IB_DEMO_FEATURES=1` and the Settings switch) | Built and tested | `databridge_ib/live.py` |
| Deliverables from an answer (kill switch `IB_DELIVERABLES`): Table and Chart with no model, Analysis (needs a model), Slides `.pptx` export with the formula guard | Built and tested | `databridge_ib/deliverables/`, [FEATURE_CATALOGUE §12](docs/FEATURE_CATALOGUE.md) |
| File uploads into Drive (Word, Excel, PowerPoint, PDF, CSV, Markdown, chat export; demo-only), with a folder picker of permitted folders | Built and tested | [contracts/uploads.md](docs/contracts/uploads.md) |
| Everyday-company world (34 people, 1,207 documents, 72 facts, 546 questions) | Built and verified | `databridge/fixtures/enterprise/` |
| Onboarding workflow (Project Atlas) | Built | `databridge/fixtures/scenarios/atlas_onboarding/` |
| One-command launcher | Built | [`databridge/scripts/demo_up.sh`](databridge/scripts/demo_up.sh) |
| Live-ingestion kit | Written | [LIVE_INGEST_KIT.md](docs/live_kit/LIVE_INGEST_KIT.md) |
| Docker deployment for any host (Caddy HTTPS, internal backend network, read-only containers) | Built and run locally | [deploy/docker/](deploy/docker/README.md) |
| Vultr deploy kit: Cloud Compute VM, firewall group, cloud-init, Vultr API v2 provisioning (dry run by default), Serverless Inference preset and checker | First boot run on a clean Ubuntu userland and tested offline; not yet run on a live Vultr account | [deploy/vultr/](deploy/vultr/README.md) |
| Real-task workflow runner (procurement: ask, cited answer, draft, ticket on human approval, audit pull, contrast) | Built and tested in process and through the Docker edge | `databridge/scripts/workflow_run.py`, `tests/test_workflow_run.py` |

## 2. Tested

| Check | Result | Where |
|---|---|---|
| Backend tests (Internal Brain) | Run `PY -m pytest apps/internal_brain/tests -q` from `databridge/` for the current count | `databridge/apps/internal_brain/tests/` |
| Leak evaluation | 0 leaks in 7,374 requests; 0 of 400 pairs differ; 0 injection hard failures in 1,152; recall 100% | [RESULTS.md](databridge/evals/internal_brain/RESULTS.md), [eval_summary.json](databridge/apps/internal_brain_web/public/eval_summary.json) |
| Web end-to-end tests (Playwright, axe) | Mock mode | [TEST_REPORT.md](docs/TEST_REPORT.md) |
| CI (backend tests on Python 3.13, web typecheck on Node 20) | On push and pull request to `main` and `neutral` | [`.github/workflows/ci.yml`](.github/workflows/ci.yml) |

## 3. Open

| Item | Note |
|---|---|
| Real tenants | The connectors have only run against the mock platforms |
| Single sign-on | The demo sign-in stands in for it |
| A configured AI model in the evaluation | The evaluation numbers use a capturing test model and the quoted path; re-run it with the model you plug in |
| Off-host anchoring of the ledger head | The default anchor file is on the same host; point `IB_ANCHOR_FILE` at off-host storage in a deployment |
