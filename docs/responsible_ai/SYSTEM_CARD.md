# System card: Walnut DataBridge, Internal Brain

> **Status.** Written 30 Oct 2026. Self-assessed by the team. Not certified, not
> audited by a third party, not legal advice. Synthetic data only.
>
> **How to read references.** `databridge_ib/…` means `databridge/apps/internal_brain/databridge_ib/…`.
> `tests/…` means `databridge/apps/internal_brain/tests/…`. Line numbers refer to
> commit `e5406b9` (30 Oct). The function or test name is the stable part.
>
> **Eval numbers** come from [RESULTS.md](../../databridge/evals/internal_brain/RESULTS.md) (run of
> 14 Oct). The headline numbers were re-run on the current code on 30 Oct and match `eval_summary.json`.

This card follows the shape of a model card ([Mitchell et al., 2019](https://arxiv.org/abs/1810.03993)),
adapted to a whole system. Section 9 is laid out as an AI inventory record for the MAS Guidelines on AI
Risk Management (issued 7 Oct 2026). Section 8 is the risk materiality assessment those guidelines ask for.

---

## 1. Purpose and scope

| Item | Statement | Evidence |
|---|---|---|
| What it does | Answers a staff member's plain-English question from Confluence, Jira, Slack and Google Drive, using only what that person can open in the source system at that moment. Answers cite their sources. Every question and answer is logged first. | `INTERNAL_BRAIN.md:10-16`; `databridge_ib/pipeline.py:1-10` |
| Intended users | Employees of a fintech (engineers, SREs, ops, account managers, security, compliance) and contractors. | `INTERNAL_BRAIN.md:129-131` |
| Out of scope | Not a decision-maker. Not advice to customers. Not a system of record. It grants no access, takes no actions and calls no tools. | [RESPONSIBLE_AI.md](../RESPONSIBLE_AI.md) |
| A refusal is normal | One constant refusal text for "restricted", "does not exist" and "not relevant". | `databridge_ib/models.py:20-21` |
| Deployment today | A laptop demo on synthetic data. Four mock platforms with real API shapes. No live tenant. No public URL. | `INTERNAL_BRAIN.md:29-33`; [DECISIONS.md](../DECISIONS.md) D-03 |

**Misuse we warn against.** Wiring the answers into decisions about people (hiring, credit, conduct)
would change the risk class (see [FRAMEWORK_CROSSWALK.md](FRAMEWORK_CROSSWALK.md), EU AI Act row). The
scope statement above is the control.

## 2. Users and roles

| Role (persona) | Can do | Cannot do | Evidence |
|---|---|---|---|
| Employee (`jdoe`, `priya.sre`, `leo.ops`, `sara.sec`, `amy.am`, `mlro.tan`) | Ask; see their own map, history and own-request trace | See audit, other people's requests, counts or denial reasons | `databridge_ib/app.py:138-203` |
| Contractor / guest (`ken.ext`) | Same as an employee, limited by the source's own guest rules | Same as above | `tests/test_scenarios_e2e.py::test_s3_existing_vs_nonexistent_identical` (line 53) |
| Compliance officer (`maya.compliance`) | Audit search, accessors, reasoned reveal, verify chain, `/audit/stats`, `/audit/journey` | Read more *content* than their own source permissions allow | `databridge_ib/audit/routes.py:46, 84`; `tests/test_audit_routes.py::test_non_compliance_roles_forbidden` (line 68) |
| IT admin (`admin.it`) | Run a fixed list of platform changes in the simulator | Reach audit | `databridge_ib/sim.py:29`; same test |
| Data owners | Stay the authority: the Brain mirrors source permissions and never grants | — | [RESPONSIBLE_AI.md](../RESPONSIBLE_AI.md) |

## 3. Model chain

| Order | Model | Provider | When it is used | Evidence |
|---|---|---|---|---|
| 1 | `IB_MODEL_NAME` (optional; no default) | The chat-completions-style endpoint in `IB_MODEL_URL` (no default), with an optional bearer key in `IB_MODEL_KEY` | Only when `IB_MODEL_URL` and `IB_MODEL_NAME` are set and `IB_FORCE_OFFLINE` is not `1` | `databridge_ib/llm.py` `model_configured`; `tests/test_model_config.py::test_nothing_configured_means_the_deterministic_path` |
| 2 | Each name in `IB_MODEL_FALLBACKS` (optional) | Same endpoint | When the previous model errors, times out, returns 429, returns empty text or fails grounding | `databridge_ib/llm.py`; `tests/test_llm_chain.py::test_main_model_failure_falls_back_to_the_next_model` |
| 3 | `extractive-v1` (deterministic) | None: quotes up to 4 verbatim sentences from released passages | When no model is configured, the kill switch is on, every model fails, or a model answer cites no released passage | `databridge_ib/narrate.py:145-197`; `databridge_ib/pipeline.py:171-179`; `tests/test_llm_chain.py::test_both_fail_pipeline_serves_extractive` |

- **Default: no model.** With nothing configured, every answer is the deterministic quoted answer, and
  it says so. All numbers on this card come from a capturing fake model and the extractive path; no
  real-model run is published.
- **Bring your own model.** One provider-neutral adapter: a plain HTTPS client for any
  chat-completions-style JSON endpoint, configured only by `IB_MODEL_URL`, `IB_MODEL_NAME`, `IB_MODEL_KEY`
  and `IB_MODEL_FALLBACKS`. No vendor SDK, no vendor default (`databridge_ib/llm.py`;
  `tests/test_model_config.py::test_the_chain_sends_the_configured_name_through_the_neutral_adapter`).
- **The model has no tools.** It gets a system message and a user message only (`databridge_ib/llm.py`).
- **Prompt version.** `ib-prompt-2026-10-13.1` (`databridge_ib/narrate.py:19`), written to every
  `answer.released` event (`databridge_ib/pipeline.py:190-191`).
- **Seed.** Fixed at 7 (`databridge_ib/llm.py`). Whether a given endpoint honours it is not verified.
- **Kill switch.** `IB_FORCE_OFFLINE=1` stops every model call (`databridge_ib/llm.py` `force_offline`;
  `tests/test_model_config.py::test_force_offline_wins_over_any_configuration`). It is global and read at start-up.

## 4. Data

| Item | Statement | Evidence |
|---|---|---|
| Source data | Synthetic "Company A": 34 people, 1,207 documents, 72 planted facts | [DATA_CARD_COMPANY_A.md](DATA_CARD_COMPANY_A.md) |
| Training | None. No model is trained or fine-tuned on any data. | No training code in `databridge/apps/internal_brain/` |
| Sent to the model | Per question only: the system prompt, at most 14 released passages (at most 2 per document) and the question | `databridge_ib/pipeline.py:34-35, 147`; [DATA_FLOWS.md](../DATA_FLOWS.md) |
| Masked before indexing | Card numbers (first 6 + last 4), card security codes, NRIC/FIN, IBANs | `databridge_ib/ingest.py:64, 102`; `databridge_ib/pipeline.py:232`; `tests/test_fintech_scenarios.py::test_sens_raw_values_appear_nowhere_in_the_index` (line 206) |
| Embeddings | Local offline hashing embedder; nothing leaves at ingest | `databridge_ib/index.py:159-168`; `databridge_ib/bootstrap.py:63` |
| Kept | Question text and ids/hashes in the ledger; answer text in a separate store | [DATA_FLOWS.md](../DATA_FLOWS.md) |

## 5. Controls

| Control | What it does | Evidence |
|---|---|---|
| Identity from a signed token only | HMAC token, 60 s to 8 h, revocable; no identity in any request body | `databridge_ib/auth.py:19, 36, 41, 62-63`; `databridge_ib/models.py:154-155`; `tests/test_app_routes.py::test_identity_from_token_only` (line 60) |
| Gate 1 | Ranks only documents the stored source permissions allow; BM25 statistics come from those documents only | `databridge_ib/index.py:1-12, 289-316`; `databridge_ib/pipeline.py:114-118` |
| Relevance gate | Nothing relevant means no Gate 2 call, no model call and the constant refusal | `databridge_ib/index.py:39-42, 377`; `tests/test_pipeline_core.py::test_s3_contractor_refusal_is_the_constant` (line 161) |
| Gate 2 | Asks each source live, one 2 s budget per batch; error, timeout or 429 means deny | `databridge_ib/gates.py:28-54`; `tests/test_scenarios_e2e.py::test_s4_revocation_without_webhook` (line 83) |
| Write-ahead ledger | `request.accepted` → `retrieval.decided` → `answer.released`; a ledger failure means 503 | `databridge_ib/pipeline.py:106-110, 151-158, 184-197`; `tests/test_pipeline_core.py::test_write_ahead_fail_closed` (line 181); `tests/test_app_routes.py::test_ledger_failure_is_503` (line 93) |
| Grounding wall | Numbers, dates and names must appear in cited evidence; else next model, then extractive | `databridge_ib/narrate.py:113-134`; `tests/test_llm_chain.py::test_ungrounded_number_refused_by_grounding_wall` (line 198) |
| Injection containment | Passages are labelled untrusted; citation-shaped text is neutralised; sentences addressed to an AI are dropped | `databridge_ib/narrate.py:31-32, 43-67`; `databridge_ib/pipeline.py:169-170` |
| One response shape | Constant `scope_note`, no counts, no denial reasons | `databridge_ib/models.py:18-21, 179-185`; `tests/test_pipeline_core.py::test_p2_differential_world_with_and_without_restricted` (line 153) |
| Tamper evidence | Sealed hash chain, separate anchor ledger, external head | [SECURITY.md](../SECURITY.md); `tests/test_audit_tamper.py` |
| Reasoned reveal | Answer text only with a reason, ledgered before it is read, re-hashed against the seal | `databridge_ib/audit/routes.py:183-222`; `tests/test_audit_routes.py::test_reveal_requires_reason_and_is_ledgered` (line 119) |

## 6. Evaluation summary

| Measure | Result | Source |
|---|---|---|
| Leaks | 0 of 7,374 requests; 95% upper bound 0.0814% per request per path (re-run 30 Oct) | `RESULTS.md:9-11` |
| Requests where the fake model received passages | 1,047; 95% upper bound on payload leak rate 0.2865% (re-run 30 Oct) | `RESULTS.md:12` |
| Restricted vs non-existent (P2) | 400 compared, 0 mismatches; control rebuild 0 (re-run 30 Oct) | `RESULTS.md:16, 101-108` |
| Injection hard failures | 0 in 1,152 injection-relevant requests (re-run 30 Oct) | `RESULTS.md:17, 110-116` |
| Released recall on positive probes | 100% on both paths (re-run 30 Oct) | `RESULTS.md:18` |
| Cited recall | 97.1% (fake model), 93.2% (extractive) (re-run 30 Oct) | `RESULTS.md:131, 141` |
| Eval canaries | Valid: leaky config caught on 18 of 20; deny-all scores 0% utility (re-run 30 Oct) | `RESULTS.md:143-146` |
| Backend tests | 1,274 passed, 0 failed, 4 skipped, 30 Oct evening, clean checkout (Linux, Python 3.13) | `python -m pytest apps/internal_brain/tests -q` (see [TEST_REPORT.md](../TEST_REPORT.md)) |
| Real-model run | **Not run** | `RESULTS.md` |

## 7. Known limits and gaps

Copied in substance from `INTERNAL_BRAIN.md:243-261` and [SECURITY.md](../SECURITY.md), plus the
30 Oct status.

1. **No real model has been measured.** Every number comes from a capturing fake model or the extractive path.
2. **Platforms are mocked.** The connector code is the same; the base URL is injected (`databridge_ib/config.py:36-38`).
3. **Sign-in is a demo login**, not SSO (`databridge_ib/app.py:92-113`). A deployed build refuses to start without a passcode (`databridge_ib/config.py:62-66`).
4. **Grounding checks values and names, not relations between them.** One valid citation is enough for a model answer to be accepted (`databridge_ib/pipeline.py:171-173`; review track 1 finding 15).
5. **Relevance is lexical.** 7 expected-refusal questions per path were answered from related permitted pages; none was a leak (`RESULTS.md:24`).
6. **Ledger key-holder window.** A key holder could rewrite records after the last off-host head ([SECURITY.md](../SECURITY.md)).
7. **No retention period** for the ledger or answer store ([DATA_FLOWS.md](../DATA_FLOWS.md)).
8. **No human review queue, feedback routing or dual-control reveal** ([RESPONSIBLE_AI.md](../RESPONSIBLE_AI.md)).
9. **No rate limiter; timing side channel not controlled** ([SECURITY.md](../SECURITY.md)).
10. **Review track 1 (35 findings) has no written disposition;** findings 3, 9, 11, 12 and 15 are open by our reading ([SECURITY.md](../SECURITY.md)).
11. **English only.** Market-specific policy content for SG and ID only.
12. **Built (30 Oct):** per-stage timings, `/audit/stats`, `/audit/journey` and `/ib/trace` (`tests/test_dev_views.py`), and the permission-aware graph (`/ib/graph`) and document view (`/ib/doc`) (`tests/test_graph_doc.py`) are built and tested.

## 8. Risk materiality assessment (self-assessed)

The MAS guidelines ask for risk materiality per use case, along impact, complexity and reliance. This is our
reading for the intended use in section 1.

| Dimension | Rating | Why | What keeps it there |
|---|---|---|---|
| **Impact** if it goes wrong | **High** for disclosure; **Low** for wrong answers | A leak of restricted content, or confirming that a suspicious-transaction file exists, is a data-protection and tipping-off exposure (CDSA s.57; [MAS_TRM_MAPPING.md](../MAS_TRM_MAPPING.md)). A wrong answer misleads one staff member about internal content, and the citation lets them check it. | Disclosure is controlled by deterministic code before the model (Gates 1 and 2, P2), not by model behaviour. Wrong answers are bounded by grounding and citations. |
| **Complexity** | **Medium-High** | Retrieval over four platforms with different permission models; an optional third-party LLM; webhooks and polling. | Each platform's permission model compiles to `nobody` when unsupported ([SECURITY.md](../SECURITY.md)); fail-closed everywhere. |
| **Reliance** | **Low-Medium** | Advisory only. People read cited sources and decide. No automated action, no customer-facing output. | Scope statement; no tools; no decision outputs. |
| **Autonomy** | **None** | The model cannot act, fetch or choose an identity. | `databridge_ib/llm.py`; `tests/test_mcp_server.py::test_internal_brain_tools_have_no_identity_argument` |

**Overall: Medium materiality, with one high-impact failure mode (disclosure) that is controlled outside
the model.** A deploying institution should re-assess when moving from synthetic to real data, when a live
tenant is connected, and when any model is configured.

## 9. AI inventory record (MAS AIRG format, draft)

| Field | Value |
|---|---|
| System name | Walnut DataBridge: Internal Brain |
| Version | Commit `e5406b9` (30 Oct 2026); prompt `ib-prompt-2026-10-13.1`; policy `ib-policy-1` (`databridge_ib/config.py:21`) |
| Business owner | To be named by the deploying institution (prototype today) |
| Technical owner | Team Walnut |
| Use case | Internal knowledge retrieval with citations for staff; no decisions about people or customers |
| Approved scope of use | Internal staff and contractors; content they can already open; synthetic data in this build |
| Jurisdiction | Singapore (deployment). Content covers SG and ID market policies. |
| AI type | Permission-filtered retrieval with a deterministic extractive answer; optional retrieval-augmented generation over an operator-chosen LLM |
| Models | `extractive-v1` (always); optionally `IB_MODEL_NAME` and `IB_MODEL_FALLBACKS` (names, not pinned builds) |
| Third parties | None by default. Optionally: the model endpoint the operator configures (generation); any MCP client (second front door, outside our ledger: TB7, [ARCHITECTURE.md](../ARCHITECTURE.md)) |
| Data used | Source documents filtered per person; question text; see section 4 |
| Personal data | Employee names and authored text in source documents; masked card, NRIC/FIN and IBAN values |
| Materiality | Medium (section 8) |
| Key controls | Section 5 |
| Validation | Leak and injection eval, canaries, 1,274 backend tests, recorded security reviews ([SECURITY.md](../SECURITY.md) §7-14) |
| Monitoring | Ledger events, `/audit/verify`, `/audit/stats` (counts and timings only, `databridge_ib/audit/stats.py:1-5`). No alerting yet. |
| Kill switch | `IB_FORCE_OFFLINE=1` (global, needs a restart) |
| Incident process | [HUMAN_OVERSIGHT_AND_INCIDENT_RUNBOOK.md](HUMAN_OVERSIGHT_AND_INCIDENT_RUNBOOK.md) |
| Status | Prototype. Not in production. |

## 10. Change log

| Date | Change | Evidence |
|---|---|---|
| 13 Oct 2026 | First eval run: 0 leaks; 6 forged-citation injection failures; 102 uncited model answers | [SECURITY.md](../SECURITY.md); [RESPONSIBLE_AI.md](../RESPONSIBLE_AI.md) |
| 14 Oct 2026 | Fixes in `8b5eb57` and `d69ab97`; final run: 0 leaks, 0 injection failures, 0 uncited answers | `RESULTS.md:3` |
| 15 Oct 2026 | Review tracks 5-7 and two further review rounds; fixes recorded | [SECURITY.md](../SECURITY.md) |
| 30 Oct 2026 | Per-stage timings, `/audit/stats`, `/audit/journey`, `/ib/trace` (`e5406b9`). Eval re-run 30 Oct. | `git show e5406b9`; `tests/test_dev_views.py` |
