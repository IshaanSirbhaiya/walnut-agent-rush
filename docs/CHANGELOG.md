# Walnut DataBridge: changelog

**Answers you can prove.**

Product changes, newest first, grouped by area. Each line gives its short commit hash where one exists. What each
feature does and how it is tested: [FEATURE_CATALOGUE.md](FEATURE_CATALOGUE.md). Test results:
[TEST_REPORT.md](TEST_REPORT.md).

Current evaluation numbers (`eval_summary.json`): **0 leaks in 7,374 adversarial requests**, 0 of 400 differential
pairs differ, 0 injection hard failures in 1,152, recall 100% on both paths. A row below quotes the numbers of the run
made at that commit. Results: [`databridge/evals/internal_brain/RESULTS.md`](../databridge/evals/internal_brain/RESULTS.md).

## Neutral build

The product no longer depends on any AI vendor or hosting platform.

| Area | Change |
|---|---|
| Model | Runs with **no model by default**: every answer is the deterministic, quoted-evidence ("extractive") answer, through the same checks |
| Model | An optional AI model plugs in through one provider-neutral adapter (a plain HTTPS client for a chat-completions-style JSON endpoint), configured only by `IB_MODEL_URL`, `IB_MODEL_NAME`, `IB_MODEL_KEY` and, optionally, `IB_MODEL_FALLBACKS` (comma-separated model names). No vendor SDK, no default URL or model. Chain: the configured model, then its fallbacks, then the extractive answer. `IB_FORCE_OFFLINE=1` still forces the extractive path |
| MCP | The MCP servers (`ib-as-jdoe`, `ib-as-ken`, `ib-compliance`) work from any MCP client; the same two gates apply and every call is ledgered |
| Deploy | Generic Docker deployment in `deploy/docker/` for any Docker host |
| Docs | Competition material removed; the docs describe the product only |

## Workflows

| # | Workflow | Who | What it shows |
|---|---|---|---|
| 1 | **Onboarding**: "Your first day leading Project Atlas" | A new project lead | A briefing on a named project is scoped to that project's own documents, through both permission gates (`fixtures/scenarios/atlas_onboarding/`, `databridge_ib/subject.py`; run with `IB_WORLD=atlas bash scripts/demo_up.sh start`) |
| 2 | **The account-restriction call**: Amy vs Rachel | Amy (account manager) and Rachel ask the same question about Velquarry Trading | Each gets only what they may open; Amy gets the approved customer script and the constant refusal, never a hint that a case exists |
| 3 | **Audit and tamper check** | Maya (compliance) | The request end to end (journey, Gate-2 verdicts), **Verify audit chain**, and the tamper check on a copy: any edit, deletion or restore breaks the chain |

## Adapters, agents and connectors

- **Source connectors** for Slack, Confluence, Jira and Google Drive (`databridge_ib/connectors/`): each re-checks the asker's access live, per document, before a passage is used.
- **Adapter contract and policy** (`packages/adapter`), **AI adapter agents and the adapter builder** (`packages/adapter_agents`), **MCP ingest** (`packages/mcp_ingest`).
- **Federated engine** (`packages/federated`): one read-only agent per source; results combined with exact decimal arithmetic.
- **Orchestrator, agent definitions and agent runtime** (`orchestrator`, `agentdef`, `agent_runtime`): an agent runs only under compiled grants; every write is a proposal a named human approves.
- **MCP tools** (`9afd1bd`): answer receipt, what I can open, org summary, tamper check.

## Onboarding scenario (Workflow 1)

| Area | Change |
|---|---|
| Scenario | `fixtures/scenarios/atlas_onboarding/`: an additive world (Company A plus Atlas), sources, personas, `build.py`, `run_demo.py`, `verify.py`. Windows fixes: UTF-8 reads and writes, a locked SQLite file no longer fails the clean-up, re-runs write their proof to `var/` (D-45) |
| Brain | `databridge_ib/subject.py`: a briefing on a named project is scoped to it (search by section, the project's own documents only; the rules page reads more of them through both gates). `pipeline.py` and `views/service.py` call it; every other question is unchanged (D-45) |
| Run | `IB_WORLD=atlas bash scripts/demo_up.sh start` runs the stack on the Atlas world with its own state (`var/ib-atlas`); it refuses to reuse a stack already running. Default unchanged |
| Eval | `IB_EVAL_WORLD=<path>` runs the leak eval on another world. Atlas world: 0 leaks in 7,374 requests, 0 differential mismatches |
| Tests | `tests/test_subject_scope.py` (15). `demo_up.sh` keeps its STATE line (`c06daf8`) |

## Account-restriction call fixes (Workflow 2)

Fake models only in the tests.

| Area | Change |
|---|---|
| Answers | Approved customer wording is quoted, never re-worded by a model (D-43) |
| Answers | The prompt asks for every status fact the passages give (filings, decisions, counts); grounding wall unchanged (D-44, `ib-prompt-2026-10-30.1`) |
| Answers | `model.reason_code` on a quoted fallback: `model_rejected_evidence` or `model_unavailable` (backend_v1 v5) |
| User mode | True labels for quoted answers, EN and 简体中文, no provider name; "AI-generated" shown once |
| Pages | The page-or-chat prompt sends case and status overviews to a page; "Open as page" stays available |
| Page check | Value counters balance: proposed = kept + dropped |
| Security | HTTP client loggers at WARNING: no endpoint host in `ib.log` |
| Model | `IB_MODEL_ANSWER_TIMEOUT_S` (default 12 s, no retry) for the model answer call |
| Compare, journey | A "Different answers" line; the journey's model card shows "AI model" for an unnamed model |
| Preflight | 8 s quoted / 15 s with a model; rows say "AI model" |

## Pages beside the chat and model guardrails

| Area | Change |
|---|---|
| Pages (just-in-time views) | After each answer, page or chat is decided (by the optional model when it is on); a page opens in a canvas beside the chat, with every value checked against its source, rendered from A2UI v0.9 messages; changes in plain words ("make the table black"); the light Ask view and the icon-rail sidebar (D-37, D-38, D-39; `cddd878`, `e47069a`). Code: `databridge_ib/views/`, web `components/views/`, `components/user/ViewCanvas.tsx`, `lib/navRail.ts`. Tests: `tests/test_views.py` (25), `tests/test_views_composer.py` (14), `tests/e2e/views.spec.ts` (7, mock). Details: [FEATURE_CATALOGUE.md](FEATURE_CATALOGUE.md) section 14 |
| Model answers | With a model on, the model writes the chat answers (grounding wall unchanged), and follow-ups are rewritten into standalone questions (`POST /ib/rewrite`, D-40) |
| Model guardrails | One spend ledger and one set of caps for every model call, kept outside the demo state: `databridge_ib/model_guard.py`, `scripts/wipe_guard.sh`, `tests/test_model_guard.py`; total, daily, service-wide and per-person limits, fail closed, untouched by every reset; "Model budget" numbers on the preflight board and in `/ib/status` (admin and compliance) (D-42) |
| Labels | Deliverable and draft by-lines say "AI-generated from your cited sources" (en + 简体中文); `test_standin_labels.py` |

## Hardening after review

Every finding has a test.

| Area | Change |
|---|---|
| Act v3.2 | New ledger kind `action.requested` is written before the live source check, before the model call and before a replayed result (stages `accepted`, `decided`, `replayed`); a ledger failure is the 503 before Gate 2. The 80% draft floor also fails a negation that differs from its source, a number not in its anchor sentence and a capitalised word not in its cited facts. Two proposals confirmed together can never both create (one locked step; the second is `409 outcome_unknown`). The store cap holds under concurrent proposals; unknown-outcome holds are swept. An empty Jira `create` list grants nobody. Only the first over-limit call per person per window is ledgered. Tests: `test_act_round4.py`, `test_mock_jira_create.py`, `act.spec.ts` |
| `/ib/open/<token>` | An access-check error is the same 404 as an unknown token (no existence oracle); 30 a minute per person, one ledger row per window, no `doc.viewed` when refused. Tests: `test_open_route.py` |
| Deliverables | The `.pptx` writer strips control characters before the formula guard and writes every chart-workbook cell as a string; the export writes `deliverable.requested` before Gate 2 and the source read; a model title is re-checked after a revoked source and after any model fallback; each analysis number must sit in one row or clause with its names; the rate limit and a capped 4 KB read come before the body is parsed. `/audit/stats` counts exports apart from requests. Tests: `test_deliverables.py::test_r4_*`, `test_deliverables_verify.py::test_r4_*` |
| Sim, live poll, extraction, Drive | `write_ahead(None, ...)` fails closed. A live poll is ledgered before its live check. A sparse `.xlsx` is measured from its XML and refused over 1,000,000 cells before any reader runs. A Drive download is capped while streaming. Tests: `test_sim_add_document.py`, `test_live_growth.py`, `test_extract_files.py`, `test_connector_drive.py` |
| Web and kit | `/present/preflight` is served only on a loopback Host and a session the Brain confirms (404 otherwise, and always when `IB_DEPLOYED=1`); login chips are role-only; secrets go only to the Brain's own subshell; the proxy lets `ib/open/<32 hex>` through only for a real click; `fill_template.py` has the server's CSV guard; engine nodes are 24 px targets. Tests: `preflight.spec.ts`, `user.spec.ts`, `act.spec.ts`, `engine.spec.ts`, `test_round2_kit.py` |
| Session queue | `components/presenter/session.ts`: every change of who is signed in runs one at a time, and a Sign out wins over queued work |
| Wording | Act and Deliverables wording: "You can't create a follow-up ticket from this answer. You can still draft a reply."; "Too many requests in a short time. Try again in a minute."; "No AI model was used: this was built by code, straight from your sources."; "Download slides (.pptx)"; source chips have a screen-reader name |
| Upload folder picker | The upload tab lists, by name, only the Drive folders the person may upload into now, each checked live (`GET /sim/upload-folders`); the typed folder ID stays as a collapsed fallback; the upload re-checks WRITE before the write-ahead record and the Drive POST. Tests: `test_upload_folders.py`, `test_uploads.py`, `test_mock_drive_upload.py`, `grow.spec.ts` (D-34) |
| Tours | User and Developer tours are separate (D-36) |
| Backend | `/ib/map`: the in-flight build is keyed by session |
| Kit | `demo_up.sh` ignores Windows' PID 0 placeholder when it checks whether a port is held (`8ae0f1f`) |

## Presenter mode

| Commit | Change |
|---|---|
| `d8f8de7` | `Esc` never hides the HUD once the script has started and `H` does (D-33); `Space` drives the grow walk-up in a `?grow=1` tab |
| `90393b2` | Grow steps need `?grow=1` on the tab; `opencv-python-headless` pinned so a fresh install keeps PDF and PPTX uploads (D-27) |
| `82c12e7` | Proof slide: source paths wrap instead of overlapping |
| `edb0dee` | Generation-bound presenter actions, serialised session changes, safe reset, cancellable asks, honest SSE status line |
| `708d902` | Compare (two people; one person, two questions; "Identical responses" marker), Presenter mode with its keyboard script, `/present` slides |
| (no commit) | Mouse controls: clickable Next, Skip, Back, Start, Reset, Hide and Exit, each calling the same action as its key; `presenter.spec.ts` |

## User mode

| Commit | Change |
|---|---|
| `19603c8` | Web UX fixes for Deliverables, live growth and the engine refresh: focus return, no duplicate post, step-only announcements, `lang=en` on server text in 简体中文, 390 px layout, "Live updates stopped" state |
| `6de5cd6` | Labels default to "Quoted from sources (no model)"; login notes and starters no longer hint at hidden content; Act sheet fixes (`outcome_unknown` and 503 after Confirm worded honestly) |
| `1bc6b4c` | Voice dictation in the Ask composer: browser speech, English / 简体中文, never auto-sends, hidden when unsupported (`voice.spec.ts`) |
| `ac94931` | Interactive tours: User "Try it" and Developer; spotlight and "Do it for me"; English / 简体中文 |
| `b14f101` | User mode: persona sign-in, Ask with live stage events, cited answers, sources sheet, honest refusals, History, Settings, English / 简体中文 |
| `8fe6b68` | Foundation: tokens, primitives, shell with User / Developer modes, i18n, route skeletons, API client |

## Developer mode

| Commit | Change |
|---|---|
| `ca72003` | Robust graph layout fallback, readable Slack / Jira versions, citation attachment for live answers, audit `?latest=1`, waterfall seal ticks, Compare live-region status |
| `71456de` | Mission control (live pipeline), request journey (compliance waterfall and employee receipt), Analytics, `/value` ROI calculator |
| `06bc7c7` | Mock: the document panel takes authors and links from the graph mock, so both agree |
| `70b6fdc` | `/dev/graph`: permission-aware WebGL knowledge graph (Sigma): explore, search to focus, one-hop expand, node panel with passage and lineage, table view, compare two people |
| `a1c0547` | Audit console (plain-English search, hash-chain Verify, sandbox tamper check), Simulator, Trust centre |
| `7041b4d` | `/dev/brain` Walnut engine view (graph, time slider, provenance, ontology) behind a read-only proxy; dev and start bind to 127.0.0.1 |
| `c140561` | Per-area mock handler registry; agent rules ([AGENT_RULES.md](contracts/AGENT_RULES.md)) |

## Backend (Internal Brain)

| Commit | Change |
|---|---|
| `7a8f709` | The `.pptx` formula guard also quotes array formulas and link prefixes; `/sim/upload-file` mounted only with demo features and demo sign-in; add-document and upload write ledger records before and after the source call (503 if the ledger is down) |
| `2b339c8` | MCP tools frame answers, titles, citations and container names as data, never instructions, and neutralise forged markers; compliance MCP config kept apart (D-30); `check_absent` and `demo_preflight` refuse non-loopback hosts unless `--allow-remote`; mock Jira checks the caller like real Jira |
| `7fa6319` | Act draft grounding: a model draft sentence must take 80% of its content words from its own cited sources, else it is dropped (D-28) |
| `ca014cd` | Act v3.1: per-person rate limit and pending-proposal cap, opaque gated source links in tickets (`/ib/open/<hmac>` runs Gate 1 + Gate 2 for the clicker), confirm re-checks the cited sources, Jira timeouts and 5xx are `outcome_unknown` |
| `1701515` | **Deliverables from an answer** (table, chart, analysis; `.csv` and `.pptx` export; kill switch `IB_DELIVERABLES`, D-25). Table, Chart and Slides need no model; every string goes through the formula guard |
| `8312864` | **Act** (draft a reply or a follow-up Jira ticket, created only after the person confirms), **live graph growth and add-document** (demo-only, `IB_DEMO_FEATURES=1`), **file uploads** (demo-only) and the **everyday-company world** (34 people, 1,207 docs, 72 facts, 546 questions; `fixtures/enterprise/workplace.py`) |
| `7bf3246` | Graph edges from authorised current versions; SSE gate events held until sealed; caps after live auth; tamper lock safety; trace failure ledgered; Host allowlist on the Brain and the mock; graph re-search after denials. Eval at that commit: 0 / 5,958 and 0 / 400; 754 tests pass |
| `8582f4b` | Simulator reset runs a full reconciliation (revocations undone at once); offline plain-English audit search resolves document titles |
| `e9ce768` | Sandbox tamper endpoint, SSE stage events (`/ib/ask/stream`), model-assisted plain-English audit search with rule fallback, silent-revocation seeding |
| `9826de0` | Web proxy: unbuffered pass-through for `/ib/ask/stream` |
| `405d34b` | Permission-aware `/ib/graph` (+ `openable`), `/ib/doc`, `/ib/status`, trace as a public receipt, version-bound authz helper, ledgered failures, replay seeder, eval summary, proxy allowlist |
| `e5406b9` | Stage timings, `/audit/stats`, `/audit/journey`, own-request `/ib/trace` for Developer mode |

## Security

| Commit | Change |
|---|---|
| `8e53a0b` | Proxy: a 7 MB body cap for `POST sim/upload-file` only; every other route keeps 64 KiB |
| `1079bd2` | Proxy allowlist: `GET /ib/graph/changes` for the main session and Compare slots |
| `7bf3246` | Host allowlist (`TrustedHostMiddleware`) on the Brain and the mock platforms |
| `bc8414c` | Web proxy refuses a non-loopback Host (DNS rebinding) and cross-site GETs; the engine snapshot is readable only by its own persona |

## Accessibility and i18n

| Commit | Change |
|---|---|
| `ca7a2ff` | English starter questions tagged `lang="en"` in 简体中文 (WCAG 3.1.2) |
| `01d8ac7` | Top bar reflow at 130% text; 简体中文 skip link and roles; 24 px chips; unique landmarks; one live region; safe `?next` deep links with a session timeout; `safeHref`; graph layout cleared on persona change |

## Tests and evaluation

| Commit | Change |
|---|---|
| `9819855` | Full eval re-run after the backend changes: 0 leaks / 7,374, 0 / 400 pairs, 0 hard failures in 1,152 injection-relevant requests |
| `810ddbb` | Full e2e suite ported to the new UI: 124 passed, 0 failed, 38 env-gated skips; dead `AnswerPanel` / `SourcesPanel` removed |

## Scripts

| Commit | Change |
|---|---|
| `831297e` | Live kit: a `/sim` 404 is reported as "one of the three demo switches is wrong" |
| `a1ccc6c` | One-click local kit: Start/Stop/Reset/offline launchers, preflight board with pre-warm, duplicate-safe `demo_up` |
| `dda470b` | `demo_up.sh` starts the whole local stack (mock, Brain, seed, engine, web) on localhost |

## Baseline

The first release had 639 Internal Brain tests and 38 web e2e tests passing, and the leak evaluation gave 0 leaks.
The backend rules (two gates, identity from the token, write-ahead ledger, one response shape) are unchanged since then.
