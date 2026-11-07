-- Safety filter, always the first filter in both builders. Book text comes from untrusted
-- sources (web pages, PDFs, captions) and the output may be published, so this filter
-- works on pandoc's parsed document instead of on markdown text (regex sanitizers lose
-- to parser differentials):
--
-- 1. Raw HTML/LaTeX anywhere is shown as literal text, EXCEPT inside
--    ::: {.widget key="<book.json widget_key>"} blocks. Only the agent knows the key
--    (passed with -M ebookify_widget_key=...), so fetched text cannot create a live widget.
-- 2. Images: only files directly in images/ and data:image URIs. Inside trusted widgets,
--    src/srcset/poster/data/background attributes follow the same rule, and tags that
--    load other documents (<link>, <iframe>, <object>, <embed>, <base>, <meta>) are removed.
-- 3. Links: only http(s), mailto and #fragment targets; others (javascript:, data:,
--    file:, relative paths) keep their text but lose the link.
--
-- Every removal is reported on stderr as "[ebookify] removed ...", which the build
-- scripts turn into report problems.

local exts = { png = true, jpg = true, jpeg = true, gif = true, webp = true, svg = true }
local TRUSTED = "ebookify-trusted-html"

local function report(what, value)
  io.stderr:write("[ebookify] removed " .. what .. ": " .. tostring(value):sub(1, 160) .. "\n")
end

local function allowed_media(src)
  if src:match("^data:image/[%w.+-]+[;,]") then return true end
  local name = src:match("^images/([^/\\]+)$")
  if not name or name:find("%.%.") then return false end
  local ext = name:match("%.([%w]+)$")
  return ext ~= nil and exts[ext:lower()] == true
end

-- case-insensitive Lua pattern for a literal word ("src" -> "[sS][rR][cC]")
local function ci(word)
  return (word:gsub("%a", function(c) return "[" .. c:lower() .. c:upper() .. "]" end))
end

local function clean_widget_html(text)
  for _, tag in ipairs({ "link", "iframe", "object", "embed", "base", "meta" }) do
    text = text:gsub("<%s*" .. ci(tag) .. "[^>]*>", function(t)
      report("<" .. tag .. "> tag", t)
      return ""
    end)
  end
  for _, attr in ipairs({ "src", "srcset", "data", "poster", "background" }) do
    local name = ci(attr)
    text = text:gsub("(%s" .. name .. "%s*=%s*)([\"'])(.-)%2", function(prefix, q, value)
      if allowed_media(value) then return prefix .. q .. value .. q end
      report(attr .. "= in widget HTML", value)
      return prefix .. q .. q
    end)
    text = text:gsub("(%s" .. name .. "%s*=%s*)([^%s>\"']+)", function(prefix, value)
      if allowed_media(value) then return prefix .. value end
      report(attr .. "= in widget HTML", value)
      return prefix .. '""'
    end)
  end
  return text
end

-- Pass 1: find trusted widgets and mark their raw HTML.
local key = ""

local mark = {
  RawBlock = function(el)
    if el.format == "html" then el.format = TRUSTED end
    return el
  end,
  RawInline = function(el)
    if el.format == "html" then el.format = TRUSTED end
    return el
  end,
}

local pass1 = {
  Meta = function(meta)
    if meta.ebookify_widget_key then
      key = pandoc.utils.stringify(meta.ebookify_widget_key)
    end
    meta.ebookify_widget_key = nil  -- never write the key into the output
    return meta
  end,
}

local pass2 = {
  Div = function(el)
    if el.classes:includes("widget") then
      local given = el.attributes.key or ""
      el.attributes.key = nil
      if key ~= "" and given == key then
        return pandoc.walk_block(el, mark)
      end
      report("widget without the book's widget_key (its raw HTML is shown as text)", given)
    end
    return el
  end,
}

-- Pass 3: neutralize everything that was not marked; enforce media and link rules.
local pass3 = {
  RawBlock = function(el)
    if el.format == TRUSTED then
      return pandoc.RawBlock("html", clean_widget_html(el.text))
    end
    report("raw " .. el.format .. " block (shown as text)", el.text:gsub("%s+", " "))
    return pandoc.CodeBlock(el.text)
  end,
  RawInline = function(el)
    if el.format == TRUSTED then
      return pandoc.RawInline("html", clean_widget_html(el.text))
    end
    return pandoc.Str(el.text)  -- e.g. "<b>" in fetched prose stays visible, inert
  end,
  Image = function(el)
    if allowed_media(el.src) then return nil end
    report("image reference (only images/ files are allowed)", el.src)
    if #el.caption > 0 then return pandoc.Emph(el.caption) end
    return {}
  end,
  Link = function(el)
    local t = el.target
    if t:match("^[hH][tT][tT][pP][sS]?://") or t:match("^[mM][aA][iI][lL][tT][oO]:") or t:match("^#") then
      return nil
    end
    report("link target", t)
    return el.content
  end,
}

return { pass1, pass2, pass3 }
