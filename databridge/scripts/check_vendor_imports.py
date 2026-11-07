"""CI rule: no AI-vendor SDK is imported anywhere (P2 / ADR-0001, ADR-0002).

Every model call goes through ``packages/harness``'s one provider-neutral client
(``ChatBackend``: plain HTTPS to a chat-completions-style JSON endpoint). No vendor SDK, and no
multi-vendor router library, may be imported by any first-party file, the harness included.
This makes the model-agnostic principle structurally enforceable: it fails LOUDLY the moment a
vendor import appears anywhere.

The denylist is kept as SHA-256 digests (first 16 hex characters) of the module names, so the
source names no vendor. An import is a violation when the digest of its top-level module, or of
any dotted prefix of its full module path, is in ``FORBIDDEN_DIGESTS``. To add a module, add
``hashlib.sha256(name.encode()).hexdigest()[:16]``.

Usage:
    python scripts/check_vendor_imports.py        # exits 1 on any violation
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: digests of the forbidden module names: the hosted-model vendor SDKs, the multi-vendor routers
#: and framework adapters, the cloud model-platform SDKs, and the local model-runtime bindings
FORBIDDEN_DIGESTS = frozenset({
    "c70eca6b0f88f44d", "7d3194f79e645c42", "dcc8d7506b63db23", "72e8088a05b38ae3",
    "938973a5d41077ec", "76e3c7bfe641ea12", "0b79cf2de0ee6b8e", "0c24734d7bf5954f",
    "b23b068c8142639b", "89281cb06677e3ad", "dc4cb570e960a328", "3fc38a59fe636186",
    "adc2bb3b2f9f9491", "50fb974a65e0e362", "8bdc3c22e340202b", "0caee180da9d0f3f",
    "a8182c1c17bb2847", "f3f2184b56f946c6", "cf3f16fbe198f00a", "03cdc00d39024419",
    "c49d7ef2f725ac09", "beef45df8ad1acc4", "ab3f100045f82c2a", "fb49d6d5dd712290",
    "6f7ac1823da81d2e", "4f918d6f90b1a40e", "17758f158c4be5d0", "c05ba74abcae3311",
    "5c95797f5b41ef59", "a57e8b9f0bb73ce9", "c2e500e453c03138", "48263d91c58a2899",
    "6749675d80a1faa7", "e1517be14d06cdb7", "f01ea329ad9fc5d0", "524f70ba83a75020",
})

# Directories never scanned (not first-party source).
SKIP_DIRS = {
    ".git", "__pycache__", ".venv", "venv", ".uv", "build", "dist", "node_modules",
    ".pytest_cache", ".ruff_cache", ".mypy_cache", "docs", ".agents",
}

_IMPORT_RE = re.compile(r"^[ \t]*(?:import|from)[ \t]+([A-Za-z_][\w.]*(?:[ \t]*,[ \t]*[A-Za-z_][\w.]*)*)")


def digest(name: str) -> str:
    return hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]


def is_forbidden(module: str) -> bool:
    """True when ``module`` or any dotted prefix of it is on the denylist."""
    parts = module.split(".")
    return any(digest(".".join(parts[:i])) in FORBIDDEN_DIGESTS for i in range(1, len(parts) + 1))


def scan_text(text: str) -> list[tuple[int, str]]:
    """Return (line_no, line) for every forbidden vendor import statement in ``text``."""
    hits: list[tuple[int, str]] = []
    for i, line in enumerate(text.splitlines(), start=1):
        m = _IMPORT_RE.match(line)
        if not m:
            continue
        modules = [part.strip().split(" ")[0] for part in m.group(1).split(",")]
        if any(is_forbidden(mod) for mod in modules if mod):
            hits.append((i, line.strip()))
    return hits


def find_violations(root: Path) -> list[tuple[str, int, str]]:
    """Scan every first-party .py file under ``root`` for violations. Nothing is exempt."""
    violations: list[tuple[str, int, str]] = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        for line_no, line in scan_text(path.read_text(encoding="utf-8", errors="replace")):
            violations.append((rel, line_no, line))
    return violations


def main() -> int:
    violations = find_violations(REPO_ROOT)
    if violations:
        print(f"[FAIL] vendor-import rule — {len(violations)} forbidden import(s) (P2):")
        for rel, line_no, line in violations:
            print(f"   - {rel}:{line_no}: {line}")
        return 1
    print(f"[ok] vendor-import rule — no vendor SDK import anywhere "
          f"({len(FORBIDDEN_DIGESTS)} modules denied, no exceptions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
