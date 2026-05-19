#!/bin/bash
# Block plaintext secrets from being committed.
#
# Greps the working tree (or, if --staged, the staged diff) for known
# secret-shaped patterns and exits 1 on hits. Emits a remediation
# message that points to SECURITY.md.
#
# Usage:
#   scripts/lint_no_inline_secrets.sh             # scan working tree
#   scripts/lint_no_inline_secrets.sh --staged    # scan only staged diff
#   scripts/lint_no_inline_secrets.sh path/...    # scan specific paths
#
# Allowlist:
#   .security-allowlist — one "path:pattern" entry per line. Lines
#   beginning with '#' are comments. Both fields are matched as
#   literal substrings against "filename:line".

set -uo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$REPO_ROOT"

ALLOWLIST="${REPO_ROOT}/.security-allowlist"

# ---- Patterns ------------------------------------------------------------
# Each pattern is a (label, regex) tuple. Use ERE.
PATTERNS=(
  "slack-bot|xoxb-[A-Za-z0-9-]{10,}"
  "slack-user|xoxp-[A-Za-z0-9-]{10,}"
  "github-fpat|github_pat_[A-Za-z0-9_]{20,}"
  "github-classic|gh[pousr]_[A-Za-z0-9]{36,}"
  "aws-access|AKIA[A-Z0-9]{16}"
  "aws-temp|ASIA[A-Z0-9]{16}"
  "openai|sk-[A-Za-z0-9]{20,}"
  "secret-assign|[A-Z0-9_]+_(SECRET|TOKEN|PASSWORD|KEY)=[\"']?[A-Za-z0-9/+_=-]{16,}"
)

# ---- File selection ------------------------------------------------------
mode="tree"
files=()
for arg in "$@"; do
  case "$arg" in
    --staged) mode="staged" ;;
    -h|--help)
      sed -n '1,/^set -uo/p' "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *) files+=("$arg") ;;
  esac
done

if [[ "$mode" == "staged" ]]; then
  mapfile -t targets < <(git diff --cached --name-only --diff-filter=AM)
elif [[ ${#files[@]} -gt 0 ]]; then
  targets=("${files[@]}")
else
  # Working tree — only files git knows about, exclude binaries and
  # well-known noise paths.
  mapfile -t targets < <(git ls-files | grep -E -v '^(\.venv|node_modules|\.git|uv\.lock|.*\.lock|.*\.png|.*\.jpg|.*\.jpeg|.*\.gif|.*\.ico)$')
fi

# Apply allowlist filter.
# Allowlist line format: ``filepath:pattern``
# A hit ``filepath:lineno:matchedline`` is allowed when the hit's filepath
# starts with the allowlist filepath AND the hit's matchedline contains
# the allowlist pattern.
allow_match() {
  local hit="$1"
  [[ -f "$ALLOWLIST" ]] || return 1
  local hit_file="${hit%%:*}"
  local hit_rest="${hit#*:}"     # "<lineno>:<matchedline>"
  local hit_line="${hit_rest#*:}" # "<matchedline>"
  while IFS= read -r line; do
    [[ -z "$line" || "${line:0:1}" == "#" ]] && continue
    local allow_file="${line%%:*}"
    local allow_pattern="${line#*:}"
    if [[ "$hit_file" == "$allow_file"* && "$hit_line" == *"$allow_pattern"* ]]; then
      return 0
    fi
  done < "$ALLOWLIST"
  return 1
}

hits=0
hit_log=""

for target in "${targets[@]}"; do
  [[ -f "$target" ]] || continue
  for entry in "${PATTERNS[@]}"; do
    label="${entry%%|*}"
    regex="${entry#*|}"
    while IFS= read -r match; do
      [[ -z "$match" ]] && continue
      if allow_match "$match"; then
        continue
      fi
      hit_log+="  [${label}] ${match}\n"
      hits=$((hits + 1))
    done < <(grep -n -E "$regex" "$target" 2>/dev/null | sed "s|^|${target}:|")
  done
done

if [[ "$hits" -gt 0 ]]; then
  echo "❌ scripts/lint_no_inline_secrets.sh: found $hits inline-secret pattern(s)"
  echo ""
  printf "%b" "$hit_log" | head -50
  echo ""
  echo "Move secrets to AWS SSM Parameter Store (SecureString) and have the"
  echo "workload's IAM role read them at cold-start. See SECURITY.md."
  echo ""
  echo "If a hit is a genuine fixture or false-positive, add the path:pattern"
  echo "snippet to .security-allowlist (one per line). Reviewers must check"
  echo "every new allowlist entry."
  exit 1
fi

echo "✓ scripts/lint_no_inline_secrets.sh: no inline secrets found"
exit 0
