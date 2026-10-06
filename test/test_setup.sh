#!/bin/bash
# The hotkey block goes into a copy of hyprland.lua after the Omarchy defaults and comes
# out again leaving the file exactly as it was. Never touches the real file.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
cat >"$tmp/hyprland.lua" <<'LUA'
-- user config
require("default.hypr.omarchy")

require("hypr.bindings")
LUA
cp "$tmp/hyprland.lua" "$tmp/original.lua"
# shellcheck source=../setup
source "$here/../setup"
HYPR_MAIN="$tmp/hyprland.lua"
HYPR_HOST="$tmp/host.lua"
HYPR_CONFIG=$HYPR_MAIN
insert_block
grep -qF -- "-- >>> gg.arkship.herdr-ready >>>" "$HYPR_CONFIG"
[[ $(grep -n 'default.hypr.omarchy' "$HYPR_CONFIG" | cut -d: -f1) -lt $(grep -n '>>> gg.arkship' "$HYPR_CONFIG" | cut -d: -f1) ]]
has_block
remove_block
cmp "$tmp/original.lua" "$HYPR_CONFIG"
! has_block
[[ $(key_mask "SUPER + H") == 64 && $(key_name "SUPER + H") == H ]]
[[ $(key_mask "SUPER + CTRL + SHIFT + J") == 69 ]]
# With a per-machine host.lua (omarchy-config), the block goes there, through a link.
mkdir "$tmp/repo"
printf -- '-- AMD-LZM4 only\no.bind("SUPER + ALT + P", "Screenshot", "x")\n' >"$tmp/repo/host.lua"
cp "$tmp/repo/host.lua" "$tmp/host-original.lua"
ln -s "$tmp/repo/host.lua" "$HYPR_HOST"
HYPR_CONFIG=$HYPR_HOST
insert_block
[[ -L $HYPR_HOST ]]
grep -qF -- "-- >>> gg.arkship.herdr-ready >>>" "$tmp/repo/host.lua"
cmp "$tmp/original.lua" "$HYPR_MAIN"
[[ $(block_file) == "$HYPR_HOST" ]]
remove_block "$(block_file)"
[[ -L $HYPR_HOST ]]
cmp "$tmp/host-original.lua" "$tmp/repo/host.lua"
! block_file
echo "setup block: ok"
