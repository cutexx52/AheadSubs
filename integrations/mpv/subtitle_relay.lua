local mp = require "mp"
local utils = require "mp.utils"
local options = require "mp.options"
local msg = require "mp.msg"

local config = { launcher = "", pythonw = "", port = 8769 }
options.read_options(config, "subtitle_relay")
local title = "AheadSubs"
local session = "mpv-" .. tostring(utils.getpid()) .. "-" .. tostring(os.time())
local enabled, pending = false, false
local source, target, ahead = nil, nil, 20
local subtitle, revision, generation = nil, nil, 0
local subtitle_generation
local last_status, next_launch = "", 0

local function track_for(path)
    for _, track in ipairs(mp.get_property_native("track-list", {})) do
        if track.type == "sub" and track["external-filename"] == path then
            return track.id
        end
    end
end

local function unpublish()
    local id = subtitle and track_for(subtitle)
    if id then mp.commandv("sub-remove", id) end
    subtitle, revision = nil, nil
end

local function request(route, payload, callback)
    mp.command_native_async({
        name = "subprocess", playback_only = false, capture_stdout = true, capture_stderr = true,
        args = { "curl.exe", "--silent", "--show-error", "--fail-with-body", "--noproxy", "*", "--max-time", "3",
                 "-H", "Content-Type: application/json", "--data-binary", utils.format_json(payload),
                 "http://127.0.0.1:" .. config.port .. "/v1/" .. route },
    }, callback)
end

local function launcher(background)
    if config.launcher == "" or config.pythonw == "" then
        mp.osd_message("Open AheadSubs settings to install its launcher.", 4)
        return
    end
    local args = {config.pythonw, config.launcher}
    if background then args[#args + 1] = "--background" end
    mp.command_native_async({name = "subprocess", playback_only = false, detach = true, args = args},
                            function() end)
end

local function poll()
    if not enabled or pending then return end
    local path = mp.get_property("path")
    local pos = mp.get_property_number("time-pos")
    if not path or not pos or path:find("://", 1, true) then return end
    local audio, selected = {}, nil
    for _, track in ipairs(mp.get_property_native("track-list", {})) do
        if track.type == "audio" and not track.external then
            audio[#audio + 1] = track
            if track.selected then selected = track.id end
        end
    end
    if not selected then return end
    table.sort(audio, function(a, b) return (a["ff-index"] or a.id) < (b["ff-index"] or b.id) end)
    local index
    for i, track in ipairs(audio) do if track.id == selected then index = i - 1 end end
    local absolute = mp.command_native({"expand-path", path})
    if absolute:sub(2, 2) ~= ":" and absolute:sub(1, 1) ~= "/" then
        absolute = utils.join_path(mp.get_property("working-directory", "."), absolute)
    end
    local request_generation = generation
    pending = true
    request("playback", {
        session = session, path = absolute, position = pos, audio = index,
        speed = mp.get_property_number("speed", 1), duration = mp.get_property_number("duration"),
        source = source, target = target, ahead = ahead
    }, function(success, result)
        pending = false
        if not enabled or generation ~= request_generation then return end
        if not success or result.status ~= 0 then
            last_status = "Waiting for AheadSubs service"
            if result then
                msg.verbose("Relay request failed: " .. tostring(result.error_string) .. " " ..
                            tostring(result.stderr) .. " " .. tostring(result.stdout))
            end
            if mp.get_time() >= next_launch then
                next_launch = mp.get_time() + 15
                launcher(true)
            end
            return
        end
        local reply = utils.parse_json(result.stdout)
        if not reply then return end
        if (not reply.subtitle or reply.subtitle_has_cues == false)
            and subtitle_generation and reply.subtitle_generation ~= subtitle_generation then
            unpublish()
        end
        subtitle_generation = reply.subtitle_generation
        last_status = reply.error or string.format("Translated buffer: %.1f s", reply.ready_ahead or 0)
        mp.set_property_native("user-data/subtitle-relay", {
            enabled = true, ready_ahead = reply.ready_ahead, revision = reply.revision,
            error = reply.error,
        })
        if not reply.subtitle or reply.subtitle_has_cues == false
            or reply.subtitle == subtitle and reply.revision == revision then return end
        if subtitle ~= reply.subtitle then unpublish() end
        local id = track_for(reply.subtitle)
        local info = utils.file_info(reply.subtitle)
        local ok
        if id then
            ok = mp.commandv("sub-reload", tostring(id))
        elseif info and info.size > 1 then
            ok = mp.commandv("sub-add", reply.subtitle, "select", title)
        end
        if ok then subtitle, revision = reply.subtitle, reply.revision end
    end)
end

local function reset()
    generation = generation + 1
    subtitle_generation = nil
    unpublish()
end

mp.register_script_message("relay-toggle", function()
    enabled = not enabled
    reset()
    if enabled then
        mp.osd_message("AheadSubs enabled")
        poll()
    else
        mp.set_property_native("user-data/subtitle-relay", {enabled = false})
        request("close", {session = session}, function() end)
        mp.osd_message("AheadSubs disabled")
    end
end)
mp.register_script_message("relay-source", function(value)
    if value == "default" then source = nil
    elseif value == "auto" then source = ""
    else source = value end
    reset()
    poll()
end)
mp.register_script_message("relay-target", function(value)
    if value == "default" then target = nil else target = value end
    reset(); poll()
end)
mp.register_script_message("relay-ahead", function(value) ahead = tonumber(value) or ahead; poll() end)
mp.register_script_message("relay-status", function() mp.osd_message(enabled and last_status or "AheadSubs disabled", 4) end)
mp.register_script_message("relay-settings", function() launcher(false) end)
mp.register_event("start-file", reset)
mp.register_event("seek", poll)
mp.observe_property("aid", "native", function() reset(); poll() end)
mp.add_periodic_timer(0.6, poll)

local function item(label, command)
    return {title = label, type = "", cmd = "script-message-to " .. mp.get_script_name() .. " relay-" .. command}
end

mp.observe_property("menu-data", "native", function(_, menu)
    if not menu or #menu == 0 then return end
    for _, entry in ipairs(menu) do if entry.title == title then return end end
    menu[#menu + 1] = {title = title, type = "submenu", submenu = {
        item("Enable / disable subtitles", "toggle"), item("Buffer status", "status"),
        {title = "Source language", type = "submenu", submenu = {
            item("Desktop setting", "source default"), item("Automatic", "source auto"), item("English", "source en"),
            item("Japanese", "source ja"), item("Korean", "source ko"),
            item("Chinese", "source zh"),
        }},
        {title = "Target language", type = "submenu", submenu = {
            item("Desktop setting", "target default"), item("Simplified Chinese", "target zh"), item("Traditional Chinese", "target zh-TW"),
            item("English", "target en"), item("Japanese", "target ja"),
        }},
        {title = "Look-ahead", type = "submenu", submenu = {
            item("10 seconds", "ahead 10"), item("20 seconds", "ahead 20"), item("40 seconds", "ahead 40"),
        }},
        item("Open settings", "settings"),
    }}
    mp.set_property_native("menu-data", menu)
end)
