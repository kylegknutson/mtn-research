#!/bin/sh
# One-time: point git at the version-controlled hooks in .githooks/ so the
# pre-push gate is active. Re-run after a fresh clone.
cd "$(git rev-parse --show-toplevel)" || exit 1
git config core.hooksPath .githooks
chmod +x .githooks/* scripts/run_gates.py 2>/dev/null
echo "✓ core.hooksPath = .githooks (pre-push gate active). Override a push with: git push --no-verify"
