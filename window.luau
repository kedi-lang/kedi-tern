tern.route.open(function(req, _cx)
    if string.lower(req.path):sub(-5) ~= ".kedi" then
        return nil
    end
    -- Keep location-aware links in Tern's file viewer until we support reveal.
    if req.line ~= nil or req.col ~= nil then
        return nil
    end
    -- Tern preserves req.how and opens the block on req.host.
    return { block = "kedi.viewer", args = { req.path } }
end)
