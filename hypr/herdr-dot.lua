-- Herdr Dot: a key that opens the list of herdr agents waiting for you.
-- Loaded from ~/.config/hypr/hyprland.lua by the plugin's `setup install`. The key is
-- SUPER + H unless ~/.config/herdr-dot/hotkey names another (one line, e.g. SUPER + J);
-- change it with the plugin's `setup hotkey "SUPER + J"`.

local key = "SUPER + H"
local file = io.open((os.getenv("HOME") or "") .. "/.config/herdr-dot/hotkey", "r")
if file then
  local line = file:read("*l")
  file:close()
  if line and line:match("%S") then
    key = line:match("^%s*(.-)%s*$")
  end
end

-- Through the shell, not the plugin's own IPC target: every monitor's bar has its own copy of
-- the widget, and the target only reaches whichever copy claimed it first. The shell opens the
-- copy on the monitor Hyprland has focused.
o.bind(key, "Herdr agents waiting for you", "omarchy-shell shell toggle gg.arkship.herdr-dot")
