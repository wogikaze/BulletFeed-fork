#!/usr/bin/env bash
# Runs local, repeatable security checks for BulletFeed.
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repository_root"

python_bin="${PYTHON_BIN:-}"
if [[ -z "$python_bin" && -x backend/.venv/bin/python ]]; then
  python_bin="backend/.venv/bin/python"
fi
python_bin="${python_bin:-python3}"
gitleaks_bin="${GITLEAKS_BIN:-gitleaks}"
pip_audit_cache_dir="${PIP_AUDIT_CACHE_DIR:-${TMPDIR:-/tmp}/bulletfeed-pip-audit-cache}"
pip_audit_requirements="$(mktemp "${TMPDIR:-/tmp}/bulletfeed-pip-audit-requirements.XXXXXX")"
trap 'rm -f "$pip_audit_requirements"' EXIT

if [[ -n "${SEMGREP_BIN:-}" ]]; then
  semgrep_bin="$SEMGREP_BIN"
elif [[ -x "$(dirname "$python_bin")/semgrep" ]]; then
  semgrep_bin="$(dirname "$python_bin")/semgrep"
else
  semgrep_bin="semgrep"
fi

require_command() {
  local command_name="$1"
  local install_hint="$2"

  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Missing required command: $command_name" >&2
    echo "Install it with: $install_hint" >&2
    exit 127
  fi
}

require_command "$gitleaks_bin" "brew install gitleaks"
require_command "$python_bin" "python3 --version"
require_command "$semgrep_bin" "python -m pip install -e 'backend[dev]'"

echo "==> Secret scan (gitleaks)"
"$gitleaks_bin" git --redact --exit-code 1 .
"$gitleaks_bin" git --pre-commit --redact --exit-code 1 .

echo "==> Python security lint (Bandit)"
"$python_bin" -m bandit -r backend/app -ll --quiet

echo "==> Python dependency audit (pip-audit)"
"$python_bin" -m pip freeze --exclude-editable >"$pip_audit_requirements"
"$python_bin" -m pip_audit \
  --strict \
  --requirement "$pip_audit_requirements" \
  --cache-dir "$pip_audit_cache_dir"

echo "==> Source-pattern scan (Semgrep)"
"$semgrep_bin" scan \
  --config .semgrep/security.yml \
  --error \
  --metrics=off \
  backend/app app/src

if [[ "${1:-}" != "--backend-only" ]]; then
  echo "==> Android security and quality lint"
  ./gradlew ktlintCheck lint
fi

echo "Security checks passed."
