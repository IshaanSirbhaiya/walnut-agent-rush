# AGENTS.md: rules for changing this repo

For anyone changing this repository, person or coding agent. Read it before you edit.

## What this repo is

**Walnut** is a general evidence substrate for AI and agent systems:
- Every value carries a re-executable `SourcePointer`.
- A deterministic policy engine decides access.
- A sealed, hash-chained ledger records decisions.
- A grounding wall refuses unsupported model output.
- Domains (healthcare, finance, government, enterprise) are **packs**. The engine knows no domain.

**Walnut DataBridge** is the product built on it, and **Internal Brain** is the ask product inside it: a
permission-aware knowledge system over Confluence, Jira, Slack and Google Drive, with role-based access,
security logging and an audit trail. It is built as an app **on top of** the unchanged Walnut engine.

| Read first | What it holds |
|---|---|
| [README.md](README.md) | What it is, how to run it, the optional model, architecture, evaluation |
| [INTERNAL_BRAIN.md](INTERNAL_BRAIN.md) | The Internal Brain guide: walk-through, how it works, proof, limits |
| [docs/README.md](docs/README.md) | Index of the docs: feature catalogue, contracts, decisions, changelog |
| [STATUS.md](STATUS.md) | Where the build is |
| [docs/contracts/ui_foundation.md](docs/contracts/ui_foundation.md) | The web app's design rules (tokens, shell, components) |

| Code | Role |
|---|---|
| `databridge/apps/internal_brain/` | The Internal Brain service (`databridge_ib`), port 8100 |
| `databridge/apps/mock_platforms/` | Real-API-shaped Slack, Confluence, Jira and Drive, port 8200 |
| `databridge/apps/internal_brain_web/` | The web app, port 3100 |
| `databridge/fixtures/enterprise/` | The deterministic synthetic "Company A" world |
| `databridge/evals/internal_brain/` | The leak and injection evaluation |
| `databridge/packages/**` | The Walnut engine: **reused by import, not modified** |

## Hard constraints: never violate these

1. **Filter before the model.** No passage the asker cannot open in the source system may enter any
   model request (Gate 1 index pre-filter, then Gate 2 live source check). Any error, timeout or 429
   means deny.
2. **Identity only from the signed token.** No request body, tool argument or model output names a
   principal. Tools take no `user` argument.
3. **Write-ahead audit.** `request.accepted` before retrieval, `retrieval.decided` before any model
   call, `answer.released` before the response. A ledger failure means 503.
4. **One response shape.** Constant scope note, no counts and no denial reasons to the asker.
   "Restricted" is indistinguishable from "does not exist" (differential test P2).
5. **No value without a pointer.** Answers are bound to cited, permitted evidence by Walnut's grounding
   wall. On violation, serve the deterministic extractive answer.
6. **No per-domain branching in the engine** (`test_no_domain_branching`). Platform semantics live in
   connectors; domain lives in data and packs.
7. **Synthetic data only.** No real company, customer or personal data. "Company A" is fictional.
   Never use a real company's name or branding.
8. **Never claim more than a test proves.** Every claim in a doc maps to a test, an eval or a
   `file:line`.
9. **No vendor lock-in.** The product runs with no model. An optional model is reached only through the
   provider-neutral adapter (`IB_MODEL_URL`, `IB_MODEL_NAME`, `IB_MODEL_KEY`, `IB_MODEL_FALLBACKS`): no
   model SDK, no vendor default URL or model name. Model calls go through `packages/harness` and
   `databridge_ib/llm.py` only.

## Working rules

1. **Parallel work only on disjoint files.** One owner for shared registrations and `pipeline.py` order.
2. **Verify every automated review's output** before acting on it; a review that returns nothing is a
   failure, not a pass.
3. **Never run `git stash`, `git checkout --`, `git reset --hard`** or any other tree-wide git command
   while someone else is working in the tree.
4. **Nothing is hard-coded except synthetic data.** Derive test expectations from the world's fact
   manifest; never write the answer down.
5. **"Pre-existing failure" is a claim to verify.** Compare against a recorded baseline (Python 3.13,
   `requirements-lock.txt`), not memory.
6. **Replace or rename; never shadow** an existing surface.
7. **Secrets stay out of git.** Only `*.example` env files are committed; `.env.ib.local` and the
   deploy env file are local.

## Running it

```powershell
cd databridge
py -3.13 -m venv .venv; .venv\Scripts\python -m pip install -r requirements-lock.txt
# mock platforms
$env:PYTHONPATH="apps/mock_platforms"; .venv\Scripts\python -m mock_platforms --port 8200
# Internal Brain (another shell)
$env:PYTHONPATH="apps/internal_brain;packages/core;packages/harness;packages/adapter;packages/retrieval"
$env:IB_DEMO_LOGIN="1"; .venv\Scripts\python -m databridge_ib
# web (another shell)
cd apps/internal_brain_web; npm install; npm run dev     # http://localhost:3100
# tests
.venv\Scripts\python -m pytest apps/internal_brain/tests -q
```

The Walnut platform suites run per directory (`python -m pytest <dir> -m "not integration"`). The
one-command launcher is `bash databridge/scripts/demo_up.sh start` ([README.md](README.md#1-run-it)).
