-- Herdr Ready: a key that opens the list of herdr agents waiting for you.
-- Loaded from ~/.config/hypr/hyprland.lua by the plugin's `setup install`. The key is
-- SUPER + H unless ~/.config/herdr-ready/hotkey names another (one line, e.g. SUPER + J);
-- change it with the plugin's `setup hotkey "SUPER + J"`.

local key = "SUPER + H"
local file = io.open((os.getenv("HOME") or "") .. "/.config/herdr-ready/hotkey", "r")
if file then
  local line = file:read("*l")
  file:close()
  if line and line:match("%S") then
    key = line:match("^%s*(.-)%s*$")
  end
end

o.bind(key, "Herdr agents waiting for you", "omarchy-shell gg.arkship.herdr-ready toggle")
