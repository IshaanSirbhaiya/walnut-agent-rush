# Docs: index

Product docs for **Walnut DataBridge** and **Internal Brain**, the ask product inside it. Start with the
repo [README.md](../README.md) (what it is, how to run it) and [INTERNAL_BRAIN.md](../INTERNAL_BRAIN.md)
(the guide).

| Doc | What it holds |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Components, the ask path, audit path, trust boundaries TB1-TB9, the optional model, developer views |
| [SECURITY.md](SECURITY.md) | Threat model, identity, ledger attacker model, prompt injection, side channels, secrets, review dispositions |
| [DATA_FLOWS.md](DATA_FLOWS.md) | What leaves the host, what is stored and where; synthetic data only |
| [RESPONSIBLE_AI.md](RESPONSIBLE_AI.md) | How the Brain keeps a model honest, accountable and inside the asker's permissions |
| [MAS_TRM_MAPPING.md](MAS_TRM_MAPPING.md) | Mapping to MAS TRM, MAS AI Risk Management Guidelines, PDPA, PCI DSS and AML tipping-off |
| [responsible_ai/](responsible_ai/README.md) | Responsible-AI evidence pack: system card, OWASP LLM red team, framework crosswalk, AI Verify, privacy, oversight, explainability, fairness, data card |
| [diagrams/](diagrams/README.md) | The trust-boundary diagram (Mermaid) and its legend |
| [FEATURE_CATALOGUE.md](FEATURE_CATALOGUE.md) | Every user-visible feature and backend capability: who can use it, where it is, how to try it, the rules it keeps, its tests and screenshots |
| [PLATFORM.md](PLATFORM.md) | The Walnut platform underneath: every package, its tests, its screens, and which parts Internal Brain uses |
| [contracts/backend_v1.md](contracts/backend_v1.md) | The backend API contract the web app builds against |
| [contracts/ui_foundation.md](contracts/ui_foundation.md) | The web app's design tokens, shell and component rules |
| [contracts/uploads.md](contracts/uploads.md) | The file-upload contract (demo-only feature) |
| [contracts/AGENT_RULES.md](contracts/AGENT_RULES.md) | Rules for parallel work on the web app |
| [DECISIONS.md](DECISIONS.md) | Product and engineering decisions, each with its reason (IDs `D-nn` are cited from code) |
| [CHANGELOG.md](CHANGELOG.md) | Changes, newest first, by area |
| [TEST_REPORT.md](TEST_REPORT.md) | The Playwright end-to-end suite (mock mode) |
| [live_kit/LIVE_INGEST_KIT.md](live_kit/LIVE_INGEST_KIT.md) | Showing live ingestion: a new note or file is answerable at once and invisible to people without access |
| [live_growth/GRAPH_PERF_DIAGNOSIS.md](live_growth/GRAPH_PERF_DIAGNOSIS.md) | Why a large knowledge graph takes time after sign-in, and what bounds it |
| [value_calculator.spec.json](value_calculator.spec.json) | The `/value` calculator's inputs, formulas and test vectors (read by the e2e test) |
| [screens/](screens/live/) | Screenshots, one folder per area (`live/` is taken against the real backend) |

Elsewhere in the repo:

| Doc | What it holds |
|---|---|
| [../AGENTS.md](../AGENTS.md) | Hard constraints and working rules for anyone changing the repo |
| [../STATUS.md](../STATUS.md) | Where the build is |
| [../databridge/evals/internal_brain/RESULTS.md](../databridge/evals/internal_brain/RESULTS.md) | The leak and injection evaluation (0 / 7,374; 0 / 400; 0 / 1,152) |
| [../deploy/docker/README.md](../deploy/docker/README.md) | Deploying on any Docker host |
| [../databridge/apps/frontend/README.md](../databridge/apps/frontend/README.md) | The original Walnut screens |
