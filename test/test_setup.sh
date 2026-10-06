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
HYPR_CONFIG="$tmp/hyprland.lua"
insert_block
grep -qF -- "-- >>> gg.arkship.herdr-ready >>>" "$HYPR_CONFIG"
[[ $(grep -n 'default.hypr.omarchy' "$HYPR_CONFIG" | cut -d: -f1) -lt $(grep -n '>>> gg.arkship' "$HYPR_CONFIG" | cut -d: -f1) ]]
has_block
remove_block
cmp "$tmp/original.lua" "$HYPR_CONFIG"
! has_block
[[ $(key_mask "SUPER + H") == 64 && $(key_name "SUPER + H") == H ]]
[[ $(key_mask "SUPER + CTRL + SHIFT + J") == 69 ]]
echo "setup block: ok"
