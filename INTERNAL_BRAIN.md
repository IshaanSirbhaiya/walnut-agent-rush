# Internal Brain: guide

**Answers you can prove.** Ask your whole company a question, and get an answer built only from what
you're allowed to open.

**Walnut DataBridge** is the product; **Internal Brain** is the ask product inside it: a permission-aware
knowledge system over Confluence, Jira, Slack and Google Drive, with role-based access, security logging
and an audit trail. How to install and start it: [README.md → Run it](README.md#1-run-it).

Every feature, who can use it, where it is and the test that proves it:
[docs/FEATURE_CATALOGUE.md](docs/FEATURE_CATALOGUE.md). The Walnut platform underneath:
[docs/PLATFORM.md](docs/PLATFORM.md).

---

## In two minutes

The Internal Brain answers plain-English questions across **Confluence, Jira, Slack and Google Drive**.
Before any passage is used, every source is checked twice: once against the permissions copied from each
platform, and again live with the platform itself. The answer cites every source with its version and the
time access was checked. Every question, every allow/deny decision and every answer is written to an
audit log that is chained and sealed, so an edit or a deletion is detectable.

| Need | What the Brain does | Where to see it | Proof |
|---|---|---|---|
| Knowledge across tools | One cited answer from all four platforms | **Ask** as `jdoe` | `test_scenarios_e2e.py::test_canonical` |
| Restrictions per person | Each person's answer uses only what they can open; "restricted" looks exactly like "doesn't exist" | **Compare** (Amy beside Rachel; Ken's two questions), **Knowledge graph** | 0 leaks in 7,374 requests; 0 of 400 paired answers differ |
| Security logging and an audit trail | Every question and decision is logged before the answer is shown, and the log is tamper-evident | **Audit** as `maya.compliance` → **Verify audit chain** and the tamper demo; **Journey** | `test_audit_tamper.py`, `test_tamper_demo_route.py`, `test_audit_query.py::test_s5_reconstruction` |

Everything runs on a synthetic fintech called **Company A** (34 people, 231 Confluence pages, 261 Jira
issues, 628 Slack threads, 87 Drive files). No real company or customer data is used anywhere.

**What's real and what's simulated.** The four platforms are mock servers that speak the real APIs'
shapes (their permission models, webhooks, errors and rate limits); the connectors have not been run
against a live tenant. By default no AI model is configured, so answers are quoted straight from the
sources and say so. An optional AI model goes through exactly the same checks
([README.md §2](README.md#2-optional-plug-in-an-ai-model)).

## The model, in one paragraph

The Brain needs no model. The deterministic path quotes the permitted passages that answer the question,
with citations. An optional AI model can be plugged in through one provider-neutral adapter, a plain HTTPS
client for a chat-completions-style JSON endpoint, configured only by `IB_MODEL_URL`, `IB_MODEL_NAME`,
`IB_MODEL_KEY` and optional `IB_MODEL_FALLBACKS`. The model sees only passages that passed both gates; the
grounding wall checks its answer; if it fails or every model is down, the quoted answer is served.
`IB_FORCE_OFFLINE=1` forces the deterministic path. Each answer is labelled with the path that served it.

## Three workflows

| # | Workflow | Who | What it shows |
|---|---|---|---|
| 1 | **Onboarding**: "Your first day leading Project Atlas" | A new project lead | A briefing on a named project, scoped to that project's own documents, through both permission gates (`fixtures/scenarios/atlas_onboarding/`, `databridge_ib/subject.py`; run with `IB_WORLD=atlas bash databridge/scripts/demo_up.sh start`) |
| 2 | **The account-restriction call**: Amy vs Rachel | Amy (account manager) and Rachel (`mlro.tan`, money-laundering reporting officer) ask the same question about Velquarry Trading | Each gets only what they may open. Amy gets the approved customer script and the constant refusal, never a hint that a case exists |
| 3 | **The audit and tamper check** | Maya (`maya.compliance`) | The request end to end (journey, Gate-2 verdicts), **Verify audit chain**, and the tamper demo on a copy: any edit, deletion or restore breaks the chain |

## Walk-through

Start the stack: `bash databridge/scripts/demo_up.sh start --fresh` ([README.md](README.md#1-run-it)),
then open http://127.0.0.1:3100. To change person, use **Sign out** in the menu at the top right and
pick someone else. There is no password.

**Part A: User mode**

| # | Person | Click | What to notice |
|---|---|---|---|
| 1 | **Amy** (`amy.am`, account manager) | On the sign-in page, pick Amy | Each card shows the person's role and what they can open |
| 2 | Amy | **Ask** → the suggestion "Why has Velquarry Trading's account been restricted, and what should I tell the customer?" | Live stage events while it runs, then a cited answer: the approved customer script, and nothing about the case |
| 3 | Amy | Type "Has a suspicious transaction report been filed on Velquarry Trading?" | The constant refusal: "I couldn't find an answer to that in the sources you can access." No count, no hint that a case exists |
| 4 | Amy | **Compare** → "Same question · two people". First **Amy**, second **Rachel** (`mlro.tan`); paste the Velquarry question; **Ask both** | Same brain, two truths. Amy gets the script; Rachel gets the case (synthetic case FC-2026-0147). Each side is its own signed-in session |
| 5 | (Compare) | In Rachel's answer, press the chip **[2]** | The source sheet: platform, version, "Checked live at", and the cited sentences highlighted. **Esc** closes it and returns focus to the chip |
| 6 | (Compare) | "Same person · two questions". Person **Ken** (`ken.ext`, contractor); left: the Velquarry question; right: the same question about "Bayfront Spice Traders" (a company that does not exist); **Ask both** | Two refusals and the marker "Identical responses: same text, same sources". Restricted looks exactly like non-existent |
| 7 | Amy | **EN** in the header (or **Settings** → Language) | The interface flips to 简体中文. Settings also has text size, reduce motion and high contrast |

**Part B: Developer mode**

| # | Person | Click | What to notice |
|---|---|---|---|
| 8 | **Maya** (`maya.compliance`, compliance officer) | Sign out, pick Maya, then **Developer** at the top left. **Mission control** opens | The pipeline: signed identity, ledger, Gate 1, relevance, Gate 2, ledger, model, grounding, ledger, answer. Each step shows its live p50 from sealed timings |
| 9 | Maya | **Journey** → the row with `mlro.tan` and the Velquarry question | The request end to end as compliance sees it: a millisecond waterfall, the Gate-2 verdict for each document with its reason code, and the three sealed ledger records. Never the answer text |
| 10 | Maya | **Audit** → **Verify audit chain** | "Chain intact", and the head matches the copy published off-host |
| 11 | Maya | Same page, **Tamper demo** → **Run the tamper demo on a copy** | "Your real audit log was not modified." One row per attack on the copy: editing one old record gives "Chain broken at entry n"; deleting, restoring an old backup and deleting the anchors are flagged. One row honestly reads "Not detectable: the stated window" (a rollback after the last off-host publication) |
| 12 | Maya | **Analytics** | Requests, answer rate, latency p50/p95, Gate-2 deny rate and reasons, grounding drops, fallback use, all from the verified ledger. Seeded replay is labelled; **Live only** removes it |
| 13 | **Jordan** (`jdoe`, backend engineer) | Sign out, pick Jordan, Developer → **Knowledge graph** | Everything Jordan can open as one graph: 867 items, 17 places, 4 platforms. Select a node: the panel shows the passage and its lineage, each re-checked live |
| 14 | Jordan | **Compare two people** (top right of the graph) → Ken | A second, separately signed-in graph: Ken can open 24 items on 2 platforms, and none of Jordan's. No greyed placeholders for what Ken cannot open |
| 15 | Jordan | **Journey** | Jordan sees only a receipt of his own requests. **Analytics** and **Audit** show a lock card |
| 16 | Jordan | **Walnut engine**, then **Trust centre** | The engine underneath (932 entities, 2,246 links, 4,710 pointers; read-only). The Trust centre lists seven controls, each with the test that proves it |

**Tours:** **Take the tour** in the header (User mode 4 steps, Developer mode 5 steps).

### Screenshots

From the live backend, in [docs/screens/live/](docs/screens/live/):

| # | Screen | File |
|---|---|---|
| 1 | Sign-in: pick a person | [login.png](docs/screens/live/login.png) |
| 2 | Amy asks about a suspicious-transaction report: the constant refusal | [user-amy.am-answers.png](docs/screens/live/user-amy.am-answers.png) |
| 3 | Compare: Amy vs Rachel on Velquarry | [compare-amy-rachel.png](docs/screens/live/compare-amy-rachel.png) |
| 4 | The source sheet: version, checked live, cited sentences | [compare-amy-rachel-sheet.png](docs/screens/live/compare-amy-rachel-sheet.png) |
| 5 | Ken: Velquarry vs a made-up company, identical | [compare-ken-identical.png](docs/screens/live/compare-ken-identical.png) |
| 6 | Mission control as compliance | [dev-maya-mission.png](docs/screens/live/dev-maya-mission.png) |
| 7 | Journey waterfall as compliance | [dev-maya-journey-fresh.png](docs/screens/live/dev-maya-journey-fresh.png) |
| 8 | Journey of a real Gate-2 denial (seeded replay) | [dev-maya-journey-seeded-denial.png](docs/screens/live/dev-maya-journey-seeded-denial.png) |
| 9 | Journey receipt as Jordan (own request only) | [dev-jdoe-receipt.png](docs/screens/live/dev-jdoe-receipt.png) |
| 10 | Sandbox tamper demo | [dev-maya-audit-tamper.png](docs/screens/live/dev-maya-audit-tamper.png) |
| 11 | Knowledge graph: Jordan and Ken side by side | [dev-jdoe-graph-compare.png](docs/screens/live/dev-jdoe-graph-compare.png) |
| 12 | Analytics as compliance | [dev-maya-analytics.png](docs/screens/live/dev-maya-analytics.png) |
| 13 | Walnut engine | [dev-jdoe-brain.png](docs/screens/live/dev-jdoe-brain.png) |
| 14 | Trust centre | [dev-jdoe-trust.png](docs/screens/live/dev-jdoe-trust.png) |

## What you can see

| Mode | Screen | Who to sign in as | What it shows |
|---|---|---|---|
| User | **Ask** (`/`) | anyone (try `jdoe` or `amy.am`) | One cited answer from several platforms, live stage events while it runs, and a source sheet with each source's version and "checked live" time. Optional voice dictation (browser speech; you still press Ask) |
| User | **Compare** (`/compare`) | anyone | The same question asked by two people side by side, or one person asking two questions, each in its own signed session |
| User | **History** (`/history`) | anyone | Your own questions by day; a row opens your receipt |
| User | **Settings** (`/settings`) | anyone | English / 简体中文, theme, text size, reduce motion, high contrast, replay the tour |
| User | **Value** (`/value`) | anyone | A value calculator; inputs visible, result labelled an estimate |
| User | **Map** (`/map`) | anyone | Everything *you* can open, by platform and space. `jdoe` sees 867 items on 4 platforms; `ken.ext` sees 24 on 2 |
| Developer | **Mission control** (`/dev`) | anyone; organisation numbers need `maya.compliance` | The pipeline with live p50 per stage, source freshness, ledger head, model status |
| Developer | **Journey** (`/dev/journey`) | `maya.compliance` for any request; anyone for their own | Compliance: the full waterfall with Gate-2 reasons. Everyone else: a receipt of their own request |
| Developer | **Knowledge graph** (`/dev/graph`) | anyone | Your permitted documents, places, people and links as one graph; compare two separately signed-in people |
| Developer | **Walnut engine** (`/dev/brain`) | `jdoe` only | The engine's entity graph of Company A as `jdoe` sees it, the time slider, provenance to the row, the ontology. Read-only. The snapshot is not re-checked live and its reads are not logged, so everyone else, compliance included, sees a lock card |
| Developer | **Analytics** (`/dev/analytics`) | `maya.compliance` | End-to-end numbers from the verified ledger; replay history labelled |
| Developer | **Audit** (`/dev/audit`) | `maya.compliance` | Plain-English audit search, reveal-with-reason, **Verify audit chain**, and the sandbox tamper demo |
| Developer | **Simulator** (`/dev/sim`) | `admin.it` | Change access live (remove someone from a channel, restrict a page, edit a runbook) and watch the next answer change |
| Developer | **Trust centre** (`/dev/trust`) | anyone | Seven controls, their framework mappings and the tests that prove them |
| Both | **Take the tour** | header button | A guided walk: 4 steps in User mode, 5 in Developer mode |
| Outside the app | **Any MCP client** | one folder per persona | Ask the Brain from an MCP client, as an engineer, a contractor, or the compliance officer ([README.md §5](README.md#5-mcp-ask-from-any-mcp-client)) |
| Outside the app | **Original Walnut screens** (http://localhost:3300) | started by `demo_up.sh` | The Walnut engine's own views on Company A |

**Demo people** (all fictional): `jdoe` backend engineer · `priya.sre` on-call SRE · `ken.ext` contractor
(Slack Connect guest) · `sara.sec` security · `leo.ops` product/ops · `amy.am` account manager ·
`mlro.tan` (Rachel) money-laundering reporting officer · `maya.compliance` compliance officer ·
`admin.it` IT admin.

## How it works

1. **Who's asking.** A signed token from the web app or an MCP client. No request body, tool argument or
   model output can name a person.
2. **First check (Gate 1).** Search only documents this person may open, using each platform's own
   permission model (Confluence page restrictions, Jira project roles and issue security, Slack private
   and Connect channels, Drive inheritance). Ranking statistics come from those documents only, so
   restricted content can't even shift the results.
3. **Second check (Gate 2).** Ask the platform again, live, for every passage about to be used. An error,
   timeout or rate limit means no. A document that changed is re-read and re-checked.
4. **Answer.** The deterministic path quotes the passages that passed. With an AI model configured, the
   model sees only those passages and is told to cite one for every sentence. Walnut's grounding wall drops any
   number or name that isn't in the evidence; if the answer fails, the Brain quotes the evidence instead.
5. **Record.** The audit log is written ahead: `request.accepted` before retrieval, `retrieval.decided`
   before any model call, `answer.released` before the response. If it can't be written, nothing is
   answered (503).
6. **One response shape.** A constant scope note, no counts and no denial reasons to the asker.
   "Restricted" is indistinguishable from "does not exist".

## Proof

Evaluation numbers are from [RESULTS.md](databridge/evals/internal_brain/RESULTS.md), run with a
capturing test model and the deterministic quoting path. Test paths are under
`databridge/apps/internal_brain/tests/` unless shown otherwise.

| What | Result | Where |
|---|---|---|
| Restricted content in any answer, prompt or response | **0 leaks** in 7,374 adversarial requests (3,687 probes, each run on both answer paths; 95% upper bound 0.08% per request on each path) | `RESULTS.md` |
| "Restricted" vs "doesn't exist" | **0 differences** across 400 paired answers | `RESULTS.md` |
| Prompt injection planted on all four platforms | **0 hard failures** in 1,152 injection-relevant requests | `RESULTS.md` |
| Allowed sources reaching the answer step | **100%** of 442 positive probes; the answer cites the expected source in 93.2% (quoted path) to 97.1% (model path) | `RESULTS.md` |
| Map identical with and without restricted documents | test | `test_knowledge_map.py::test_map_is_identical_with_and_without_restricted_docs` |
| Audit log edits, deletions, truncation, rollback, edited stored answers | detected | `test_audit_tamper.py`, `test_audit_verify_content.py` |
| Knowledge graph and document view identical with and without restricted documents; restricted and unknown documents give the same 404 | tests | `test_graph_doc.py::test_graph_is_identical_with_and_without_restricted_docs`, `::test_doc_restricted_and_unknown_are_the_same_404` |
| Employee receipt lists only cited sources still openable; journey and stats are compliance-only | tests | `test_graph_doc.py::test_trace_lists_only_cited_docs_still_openable`, `test_dev_views.py::test_journey_is_compliance_only_and_has_no_answer_text` |
| Tamper demo runs on a copy; the live log's bytes are unchanged | tests | `test_tamper_demo_route.py` |
| Live stage events never time the permission checks; a foreign `Host` header is refused before any route | tests | `test_final_review_fixes.py::test_gate1_and_gate2_are_held_until_the_checks_are_sealed`, `::test_a_foreign_host_header_is_refused_before_any_route` |
| The engine snapshot is readable only by the persona it was built for | tests | `internal_brain_web/tests/e2e/engine-proxy.spec.ts`, `engine.spec.ts` |
| Web end-to-end tests (Playwright, including axe accessibility checks) | mock mode | [docs/TEST_REPORT.md](docs/TEST_REPORT.md) |

The evaluation's own canaries prove it can fail: a deliberately leaky configuration (both checks
switched off) is caught on 18 of 20 probes, and a deny-everything configuration scores 0% usefulness.

## Five reference scenarios

| # | Scenario | Try it | Proven by |
|---|---|---|---|
| 1 | One question, answered from several platforms, private channel omitted | Ask as `jdoe`: "What's the status of the database migration project and were there any blockers raised in Slack last week?" | `test_scenarios_e2e.py::test_canonical` |
| 2 | Fresh content is answerable quickly, citing the new version | Simulator → "Edit failover runbook (new version)", then ask as `priya.sre`: "What's the latest runbook for the payment-service incident?" | `test_scenarios_e2e.py::test_s2_freshness_via_webhook` |
| 3 | A contractor gets the same refusal for a restricted report and an invented one | Ask as `ken.ext`: "Show me the security incident report from the Q3 breach.", then the same with Q7 | `test_scenarios_e2e.py::test_s3_existing_vs_nonexistent_identical` |
| 4 | Access removed at the source is honoured on the very next question, even if the webhook is lost | Simulator → "Remove jdoe from #db-migration", then ask as `jdoe`: "What backfill throttle are we using for the ledger copy job?" | `test_scenarios_e2e.py::test_s4_revocation_live`, `::test_s4_revocation_without_webhook` |
| 5 | Compliance reconstructs everything one person accessed in a space over 30 days | Audit as `maya.compliance`: "Show me everything jdoe accessed related to the payment-gateway space in the last 30 days" | `test_audit_query.py::test_s5_reconstruction` |

The end-to-end tests run the real mock platforms, the real connectors with signed webhooks, and the full
pipeline over the generated world.

## The fintech layer

Added as data and configuration on top of the general system. Tests are in
`databridge/apps/internal_brain/tests/test_fintech_scenarios.py` unless shown otherwise.

| Rule | What it does | Proven by |
|---|---|---|
| **FinCrime compartment** | Suspicious-transaction case notes are readable only by the money-laundering reporting officer. An account manager asking about that customer gets the approved customer script, and the answer reads exactly like the answer for a company that doesn't exist (anti-tipping-off) | `::test_fc_real_vs_nonexistent_customer_is_byte_identical`, `::test_fc_account_manager_gets_only_the_approved_script` |
| **Market-specific answers** | "What can we offer this SME?" is answered per market (Singapore, Indonesia), each citing that market's approved policy | `::test_mk_singapore_and_indonesia_answers_cite_different_market_facts` |
| **Approved policies only** | A draft fee schedule with different numbers is never cited | `::test_fee_draft_is_never_indexed_considered_or_released` |
| **Card and ID masking** | Card numbers, CVVs, IBANs and NRICs are masked before indexing, so they never reach the index or a model | `::test_sens_raw_values_appear_nowhere_in_the_index`, `test_sensitive.py` |

## Honest limits

- **The platforms are mocked**, with their real API shapes and permission rules. The connectors are real
  code on the same path a real tenant would use, but have not been run against a real tenant.
- **No model is configured by default.** The evaluation numbers come from a capturing test model and the
  deterministic quoting path; a model you plug in is not covered by them until you re-run the evaluation.
- **Demo history is replay.** `--fresh` seeds about 300 questions through the real pipeline with past
  dates. They are labelled `replay` in the ledger and in Analytics, which offers "Live only".
- **Sign-in is a demo login** standing in for single sign-on. A deployed build refuses to start without a
  passcode.
- **Voice dictation uses the browser's own speech service**; the button is hidden where the browser has
  none. The app stores no audio.
- **The grounding check verifies values and names, not the relations between them, and not which
  passage a sentence cites.** A model sentence that cites the wrong permitted passage is kept, and a
  sentence with no number, date or ID is kept if it shares one content word with the evidence.
- **The audit log has a key-holder window.** It detects tampering by anyone who doesn't hold its sealing
  key; beyond the last off-host published head, a key holder could rewrite records. The tamper demo shows
  this row as "Not detectable: the stated window".
- **The map is slower than a search.** It re-checks every item live before listing it, so a big map takes
  a few seconds.
- **Relevance is lexical.** The relevance check answered 7 of the evaluation's expected-refusal questions
  (on each answer path) from related pages the asker can open. None was a leak; all are listed in
  `RESULTS.md`.
- **Recall depends on what you count.** 100% is the share of allowed documents that reach the answer
  step. The share of answers that cite the expected source is 93.2% to 97.1%.

## What's inside

- **Parts of the Walnut platform**, imported unchanged: `core` (source pointers, the sealed ledger, value
  forms), the model harness, `convert` (file readers) and the gateway's grounding wall. The Internal Brain
  keeps its own permission-first retrieval index; it does not use the platform's retrieval package.
- **The Internal Brain** on top: the permission compilers, the two checks, the audit log and console, the
  web app, the mock platforms, the Company A world, the fintech rules, the MCP servers, the evaluation and
  the original-screen configuration.

## Everything else

| Doc | What it covers |
|---|---|
| [README.md](README.md) | Running it, the optional model, architecture, MCP, deployment, and Walnut, the engine underneath |
| [docs/FEATURE_CATALOGUE.md](docs/FEATURE_CATALOGUE.md) | Every feature and backend capability: who, where, how, guarantees, tests, screenshots |
| [docs/PLATFORM.md](docs/PLATFORM.md) | The Walnut platform underneath: every package, its tests, its screens |
| [docs/contracts/](docs/contracts/backend_v1.md) | The backend, UI and upload contracts |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Decisions and their reasons |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | Changes by area |
| [RESULTS.md](databridge/evals/internal_brain/RESULTS.md) | The leak and injection evaluation |
| [Original Walnut screens](databridge/apps/frontend/README.md) | How to start them and what each screen shows on Company A |
| [deploy/docker/](deploy/docker/README.md) | Deploying on any Docker host |
