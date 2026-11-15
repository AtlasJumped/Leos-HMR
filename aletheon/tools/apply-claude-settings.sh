#!/usr/bin/env bash
# apply-claude-settings — merge claude-settings.recommended.json into ~/.claude/settings.json.
#
# Keeps everything already in your settings. Objects merge key by key; lists gain only the
# entries they don't already have. One exception: an auto-mode environment line for the same
# slot ("Primary use of Claude Code:", "Host containment:", "Sensitive data locations &
# audiences:") is replaced by the recommended one, so the classifier never sees two answers.
# Backs up the old file first, keeps its permissions (and a dotfiles symlink, if it is one),
# and refuses to write anything that isn't valid JSON.
#
#   bash apply-claude-settings.sh --dry-run  # show the change only; touches nothing
#   bash apply-claude-settings.sh            # show the change, then ask before writing
#
# Undo: copy the printed backup file back over ~/.claude/settings.json.
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
rec="$here/claude-settings.recommended.json"
dst="$HOME/.claude/settings.json"

command -v jq >/dev/null || { echo "needs jq: sudo apt install jq" >&2; exit 1; }
jq -e . "$rec" >/dev/null || { echo "recommended file is not valid JSON: $rec" >&2; exit 1; }

if [ -e "$dst" ]; then
  real=$(readlink -f "$dst")
  jq -e 'type == "object"' "$real" >/dev/null 2>&1 \
    || { echo "$dst is not a valid JSON object — fix it first (jq . $dst shows where)" >&2; exit 1; }
  current=$(cat "$real")
else
  real=$dst
  current='{}'
fi

merged=$(jq -n --argjson cur "$current" --slurpfile rec "$rec" '
  def slot: if type == "string" then (split(":")[0] | gsub("[*]"; "") | ascii_downcase | ltrimstr(" ") | rtrimstr(" ")) else null end;
  def merge(a; b):
    reduce (b | keys_unsorted[]) as $k (a;
      if (.[$k] | type) == "object" and (b[$k] | type) == "object" then .[$k] = merge(.[$k]; b[$k])
      elif (.[$k] | type) == "array" and (b[$k] | type) == "array" then .[$k] = (.[$k] + (b[$k] - .[$k]))
      else .[$k] = b[$k] end);
  ($rec[0].autoMode.environment // [] | map(select(. != "$defaults") | slot)) as $slots
  | ($cur | if (.autoMode.environment | type) == "array"
            then .autoMode.environment |= map(select((slot) as $s | ($s == null) or (. == "$defaults") or (($slots | index($s)) == null)))
            else . end) as $cur2
  | merge($cur2; $rec[0])')

if [ "$(jq -S . <<<"$current")" = "$(jq -S . <<<"$merged")" ]; then
  echo "Nothing to change: ~/.claude/settings.json already has every recommended entry."
  exit 0
fi
echo "Changes to ~/.claude/settings.json:"
diff -u --label current --label proposed <(jq -S . <<<"$current") <(jq -S . <<<"$merged") || true

[ "${1:-}" = "--dry-run" ] && exit 0
if [ ! -t 0 ]; then
  echo "Not written: run this from a terminal so it can ask you (or use --dry-run)." >&2
  exit 1
fi
read -r -p "Write these changes? [y/N] " ok || ok=
case "$ok" in y|Y) ;; *) echo "Not written."; exit 0 ;; esac

mkdir -p "$(dirname "$real")"
tmp=$(mktemp "$real.XXXXXX")
trap 'rm -f "$tmp"' EXIT
printf '%s\n' "$merged" > "$tmp"
jq -e . "$tmp" >/dev/null
if [ -e "$real" ]; then
  backup="$real.bak-$(date +%Y%m%d-%H%M%S)"
  cp -p "$real" "$backup"
  chmod --reference="$real" "$tmp"
else
  backup="(none — the file did not exist)"
  chmod 600 "$tmp"
fi
mv "$tmp" "$real"
trap - EXIT
echo "Written to $real. Backup: $backup"
echo "Next: run  claude auto-mode critique  and  claude auto-mode config  to review the result."
