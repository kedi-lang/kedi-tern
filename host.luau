local ui = tern.ui
local MAX_BYTES = 1024 * 1024
local MAX_LINES = 20000
local TIMEOUT_MS = 10000

local function python_path()
    local override = tern.getenv("TERN_KEDI_PYTHON")
    if override and override ~= "" then
        return override
    end
    local unix = tern.plugin.dir .. "/.venv/bin/python"
    if tern.fs.exists(unix) then
        return unix
    end
    local windows = tern.plugin.dir .. "/.venv/Scripts/python.exe"
    if tern.fs.exists(windows) then
        return windows
    end
    return nil
end

local function running(pane)
    for _, item in tern.pane.list() do
        if item.pane == pane then
            return true
        end
    end
    return false
end

local function fail(state, message)
    state.loading = false
    state.error = message
end

local function error_detail(err)
    local first_line = string.match(tostring(err), "^[^\r\n]+") or "Unknown error"
    return (string.gsub(first_line, "^runtime error: ", ""))
end

local function validate_result(result, length)
    if type(result) ~= "table" or result.schema ~= 1
        or result.utf16_length ~= length or type(result.decorations) ~= "table"
        or type(result.has_errors) ~= "boolean" then
        error("Invalid highlighter response")
    end
    local previous = 0
    for _, span in result.decorations do
        if type(span) ~= "table" or type(span.from) ~= "number"
            or type(span.to) ~= "number" or type(span.s) ~= "string"
            or span.from % 1 ~= 0 or span.to % 1 ~= 0
            or span.from < previous or span.to <= span.from or span.to > length then
            error("Invalid highlighter decoration")
        end
        previous = span.to
    end
    return result
end

local function reload(state, cx)
    state.generation += 1
    local generation = state.generation
    state.loading, state.error, state.has_errors = false, nil, false
    state.decorations, state.source, state.gutter = {}, "", {}
    if state.path == "" then
        fail(state, "Open a .kedi file, or choose Open with → Kedi.")
        return
    end

    local ok, source = pcall(tern.fs.read, state.path, MAX_BYTES)
    if not ok then
        local detail = error_detail(source)
        local prefix = "tern.fs.read " .. state.path .. ": "
        if string.sub(detail, 1, #prefix) == prefix then
            detail = string.sub(detail, #prefix + 1)
        end
        fail(state, "Could not read file: " .. detail)
        return
    end
    if utf8.len(source) == nil then
        fail(state, "This file is not valid UTF-8.")
        return
    end
    local _, newlines = string.gsub(source, "\n", "")
    -- Tern gives the trailing empty editor line zero height; its gutter would
    -- otherwise be painted over the preceding line number.
    local lines = math.max(1, newlines + (if string.sub(source, -1) == "\n" then 0 else 1))
    if lines > MAX_LINES then
        fail(state, "This file exceeds the 20,000-line viewer limit.")
        return
    end
    state.source = source
    state.length = 0
    for _, codepoint in utf8.codes(source) do
        state.length += if codepoint > 0xFFFF then 2 else 1
    end
    for line = 1, lines do
        state.gutter[line] = tostring(line) .. " │ "
    end

    local python = python_path()
    if python == nil then
        fail(state, "Set up highlighting: run uv sync --locked --no-dev in " .. tern.plugin.dir)
        return
    end
    state.loading = true
    local started, err = pcall(function()
        tern.process.run({ python, tern.plugin.dir .. "/python/highlight.py" }, {
            stdin = source,
            timeout_ms = TIMEOUT_MS,
        }, function(result)
            -- A previous Reload may finish after the current request.
            if generation ~= state.generation or not running(cx.pane) then
                return
            end
            state.loading = false
            if result.timed_out then
                fail(state, "Highlighting timed out. The source is still available below.")
            elseif result.status ~= 0 then
                local detail = string.sub(result.stderr or "", 1, 1500)
                fail(state, "Highlighting failed (exit " .. tostring(result.status) .. "): " .. detail)
            else
                local decoded, response = pcall(function()
                    return validate_result(tern.json.decode(result.stdout), state.length)
                end)
                if decoded then
                    state.decorations = response.decorations
                    state.has_errors = response.has_errors
                else
                    fail(state, "Could not read highlight results. Try Reload or reinstall the Python dependencies.")
                end
            end
            cx:render()
        end)
    end)
    if not started then
        fail(state, "Could not start Python: " .. error_detail(err))
    end
end

tern.block.define("viewer", {
    init = function(cx, args, saved)
        local path = args[1]
        if path == nil and type(saved) == "table" then
            path = saved.path
        end
        local state = {
            path = if type(path) == "string" then path else "",
            source = "", decorations = {}, gutter = {},
            generation = 0, loading = false, has_errors = false,
        }
        reload(state, cx)
        return state
    end,

    title = function(state)
        return "Kedi · " .. (string.match(state.path, "[^/\\]+$") or "Viewer")
    end,

    view = function(state, cx)
        local children = {}
        if state.error then
            table.insert(children, ui.text({ ui.span(state.error, "error") }))
        end
        table.insert(children, ui.node("editor", {
            key = "source",
            text = state.source,
            lang = "kedi",
            highlight = false,
            readonly = true,
            decor = state.decorations,
            gutter = state.gutter,
            cursor = 0,
            followCursor = false,
            maxLines = math.max(3, cx.rows - (if state.error then 6 else 3)),
        }))
        local status = "Read only"
        if state.loading then
            status = "Highlighting…"
        elseif state.has_errors then
            status = "Read only · syntax errors detected"
        end
        local refresh = ui.badge("Reload", "accent")
        refresh.p = refresh.p or {}
        refresh.p.actions = { click = "reload" }
        return {
            main = ui.col(children),
            dock = ui.col({
                ui.row({ refresh, ui.text({ ui.span(status, "muted") }) }),
                ui.text({ ui.span(state.path, "dim") }),
            }),
        }
    end,

    event = function(state, ev, cx)
        if ev.ev == "action" and ev.act == "reload" then
            reload(state, cx)
        end
    end,

    key = function(state, key, cx)
        if key.name == "r" and not key.ctrl and not key.alt and not key.meta then
            reload(state, cx)
            return true
        end
        return false
    end,

    save = function(state)
        return { path = state.path }
    end,
})
