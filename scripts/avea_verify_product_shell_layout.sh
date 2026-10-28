#!/usr/bin/env bash
# Guardrails for Avea product shell layout (flush pane + no horizontal overflow).
# Run after SCSS edits and after web.assets_web regen on deploy.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCSS="$REPO_ROOT/avea_dashboard/static/src/scss"
COMPILED=0

usage() {
  echo "usage: $(basename "$0") [--compiled]" >&2
  echo "  default: verify SCSS source invariants" >&2
  echo "  --compiled: also verify PROD minified CSS (requires PETSEMPIRE_SSH_PRIVATE_KEY)" >&2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --compiled) COMPILED=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown arg: $1" >&2; usage; exit 1 ;;
  esac
done

fail() {
  echo "error: $*" >&2
  exit 1
}

verify_source() {
  local inv="$SCSS/_avea_action_pane_invariants.scss"
  local shell="$SCSS/ux/_avea_product_shell_layout.scss"
  local catalogue="$SCSS/_avea_catalogue_list_pane.scss"

  [[ -f "$inv" ]] || fail "missing _avea_action_pane_invariants.scss"
  [[ -f "$shell" ]] || fail "missing _avea_product_shell_layout.scss"
  [[ -f "$catalogue" ]] || fail "missing _avea_catalogue_list_pane.scss"

  grep -q 'o_avea_action_pane_fill' "$inv" || fail "action pane mixin missing"
  grep -q '@include o_avea_action_pane_fill' "$shell" || fail "product shell must @include o_avea_action_pane_fill"
  grep -q '@include o_avea_action_pane_fill' "$catalogue" || fail "catalogue shell must @include o_avea_action_pane_fill"

  # Forbidden: width 100% on action manager in shell layout (sidebar margin overflow).
  if grep -E '\.o_action_manager\s*\{' "$shell" | grep -q .; then
    awk '
      /\.o_action_manager/ { block=1; buf=$0; next }
      block { buf=buf "\n" $0; if ($0 ~ /\}/) { block=0; if (buf ~ /width:[[:space:]]*100%/) print buf; buf="" } }
    ' "$shell" | grep -q . && fail ".o_action_manager must not use width:100% in _avea_product_shell_layout.scss"
  fi

  if rg -n 'width:[[:space:]]*100%[[:space:]]*;' "$catalogue" -B5 2>/dev/null | rg -q 'o_avea_catalogue_action_manager_shell|o_action_manager'; then
    fail "catalogue action_manager shell must not use width:100% (use o_avea_action_pane_fill)"
  fi

  local manifest="$REPO_ROOT/avea_dashboard/__manifest__.py"
  if [[ -f "$manifest" ]]; then
    local pane_line shell_line
    pane_line=$(grep -n '_avea_catalogue_list_pane.scss' "$manifest" | head -1 | cut -d: -f1)
    shell_line=$(grep -n '_avea_product_shell_layout.scss' "$manifest" | head -1 | cut -d: -f1)
    if [[ -n "$pane_line" && -n "$shell_line" && "$pane_line" -lt "$shell_line" ]]; then
      fail "_avea_catalogue_list_pane.scss must load after _avea_product_shell_layout.scss in __manifest__.py"
    fi
  fi

  echo "ok: product shell layout SCSS invariants"
}

verify_compiled_css() {
  if [[ -z "${PETSEMPIRE_SSH_PRIVATE_KEY:-}" ]]; then
    fail "--compiled requires PETSEMPIRE_SSH_PRIVATE_KEY"
  fi

  local ssh_host="${PETSEMPIRE_SSH_HOST:-178.105.141.142}"
  local ssh_user="${PETSEMPIRE_SSH_USER:-root}"
  local prod_container="${LAYOUT_VERIFY_CONTAINER:-${PROD_CONTAINER:-odoo-odoo-1}}"
  local prod_db="${LAYOUT_VERIFY_DB:-${PROD_DB:-petsempire}}"

  local keyfile
  keyfile="$(mktemp)"
  trap 'rm -f "$keyfile"' RETURN
  printf '%s\n' "$PETSEMPIRE_SSH_PRIVATE_KEY" > "$keyfile"
  chmod 600 "$keyfile"

  ssh -i "$keyfile" -o BatchMode=yes -o ConnectTimeout=20 "${ssh_user}@${ssh_host}" \
    "PROD_CONTAINER=${prod_container} PROD_DB=${prod_db} bash -s" <<'EOF'
set -euo pipefail
CSS=$(docker exec odoo-db-1 psql -U odoo -d "$PROD_DB" -t -A -c \
  "SELECT store_fname FROM ir_attachment WHERE url LIKE '%/web.assets_web.min.css' ORDER BY id DESC LIMIT 1;")
FP="/var/lib/odoo/.local/share/Odoo/filestore/${PROD_DB}/${CSS}"
check_rule() {
  local label=$1 pattern=$2
  local rule
  rule=$(docker exec "$PROD_CONTAINER" sh -c "grep -o '${pattern}' '$FP' | head -1" || true)
  if [[ -z "$rule" ]]; then
    echo "error: compiled CSS missing ${label} (pattern: ${pattern})" >&2
    exit 1
  fi
  if [[ "$rule" != *"width: auto"* ]]; then
    echo "error: ${label} must compile to width: auto (got: $rule)" >&2
    exit 1
  fi
  if echo "$rule" | grep -qE '(^|[;{[:space:]])width:[[:space:]]*100%'; then
    echo "error: ${label} must not compile to width: 100%" >&2
    exit 1
  fi
}

if ! docker exec "$PROD_CONTAINER" sh -c "grep -o 'body.o_avea_product_shell .o_action_manager{[^}]*}' '$FP' | grep -F 'background-color: #fff' | grep -F 'calc(100% - var(--avea-sidebar-width)' | grep -q ."; then
  echo "error: compiled CSS missing product shell .o_action_manager width calc beside sidebar" >&2
  exit 1
fi
check_rule "catalogue flush .o_action_manager" \
  'body.o_avea_product_shell .o_action_manager:has(.o_avea_catalogue_flush){[^}]*overflow: hidden !important[^}]*}'
if docker exec "$PROD_CONTAINER" sh -c "grep -o 'body.o_avea_product_shell .o_action_manager{[^}]*}' '$FP' | grep -q 'max-width:100%'"; then
  echo "error: .o_action_manager must not compile to max-width:100% (sidebar margin overflow)" >&2
  exit 1
fi
echo "ok: product shell layout compiled CSS invariants"
EOF
}

verify_source
if [[ "$COMPILED" -eq 1 ]]; then
  verify_compiled_css
fi
