#!/usr/bin/env bash
# apply-claude-settings — merge claude-settings.recommended.json into ~/.claude/settings.json.
#
# Keeps everything already in your settings. Objects merge key by key; lists gain only the
# entries they don't already have (nothing is removed or reordered). Backs up the old file
# first and refuses to write anything that isn't valid JSON.
#
#   bash apply-claude-settings.sh            # show the change, then ask before writing
#   bash apply-claude-settings.sh --dry-run  # show the change only
#
# Undo: cp the printed backup file back over ~/.claude/settings.json.
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
rec="$here/claude-settings.recommended.json"
dst="$HOME/.claude/settings.json"

command -v jq >/dev/null || { echo "needs jq: sudo apt install jq" >&2; exit 1; }
jq -e . "$rec" >/dev/null || { echo "recommended file is not valid JSON: $rec" >&2; exit 1; }
mkdir -p "$HOME/.claude"
[ -f "$dst" ] || echo '{}' > "$dst"
jq -e . "$dst" >/dev/null || { echo "$dst is not valid JSON — fix it first (jq . $dst shows where)" >&2; exit 1; }

merged=$(jq -n --slurpfile cur "$dst" --slurpfile rec "$rec" '
  def merge(a; b):
    reduce (b | keys_unsorted[]) as $k (a;
      if (.[$k] | type) == "object" and (b[$k] | type) == "object" then .[$k] = merge(.[$k]; b[$k])
      elif (.[$k] | type) == "array" and (b[$k] | type) == "array" then .[$k] = (.[$k] + (b[$k] - .[$k]))
      else .[$k] = b[$k] end);
  merge($cur[0]; $rec[0])')

if diff <(jq -S . "$dst") <(printf '%s' "$merged" | jq -S .) >/dev/null; then
  echo "Nothing to change: ~/.claude/settings.json already has every recommended entry."
  exit 0
fi
echo "Changes to ~/.claude/settings.json:"
diff -u <(jq -S . "$dst") <(printf '%s' "$merged" | jq -S .) --label current --label proposed || true

[ "${1:-}" = "--dry-run" ] && exit 0
read -r -p "Write these changes? [y/N] " ok
[ "$ok" = "y" ] || [ "$ok" = "Y" ] || { echo "Not written."; exit 0; }

backup="$dst.bak-$(date +%Y%m%d-%H%M%S)"
cp -p "$dst" "$backup"
printf '%s\n' "$merged" > "$dst.tmp" && mv "$dst.tmp" "$dst"
echo "Written. Backup: $backup"
echo "Next: run  claude auto-mode critique  and  claude auto-mode config  to review the result."
