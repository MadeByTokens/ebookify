-- Media allow-list, run before any other filter and before pandoc's writers fetch
-- resources. Book text comes from untrusted sources (web pages, PDFs, captions), and
-- pandoc embeds whatever an image or raw-HTML src points to: a reference such as
-- ../../.ssh/id_rsa or http://169.254.169.254/ would end up inside a book that may be
-- published. Allowed: files directly inside images/ with an image extension, and
-- inline data:image/ URIs. Everything else is removed and reported on stderr with the
-- prefix "[ebookify] removed", which the build scripts turn into report problems.

local exts = { png = true, jpg = true, jpeg = true, gif = true, webp = true, svg = true }

local function allowed(src)
  if src:match("^data:image/[%w.+-]+[;,]") then return true end
  local name = src:match("^images/([^/\\]+)$")
  if not name or name:find("%.%.") then return false end
  local ext = name:match("%.([%w]+)$")
  return ext ~= nil and exts[ext:lower()] == true
end

local function report(what, src)
  io.stderr:write("[ebookify] removed " .. what .. ": " .. src:sub(1, 160) .. "\n")
end

function Image(el)
  if allowed(el.src) then return nil end
  report("image reference (only images/ files are allowed)", el.src)
  if #el.caption > 0 then
    return pandoc.Emph(el.caption)
  end
  return {}
end

-- attributes that make a browser or pandoc load something
local load_attrs = { "src", "srcset", "data", "poster", "background", "xlink:href" }

-- case-insensitive Lua pattern for a literal attribute or tag name ("src" -> "[sS][rR][cC]")
local function ci(word)
  return (word:gsub("%a", function(c) return "[" .. c:lower() .. c:upper() .. "]" end):gsub("%-", "%%-"))
end

local function clean_html(text)
  -- tags that only load external resources are dropped entirely
  for _, tag in ipairs({ "link", "iframe", "object", "embed", "base", "meta" }) do
    text = text:gsub("<%s*" .. ci(tag) .. "[^>]*>", function(t)
      report("<" .. tag .. "> tag", t)
      return ""
    end)
  end
  for _, attr in ipairs(load_attrs) do
    local name = ci(attr)
    -- quoted values
    text = text:gsub("(%s" .. name .. "%s*=%s*)([\"'])(.-)%2", function(prefix, q, value)
      if allowed(value) then return prefix .. q .. value .. q end
      report(attr .. "= in raw HTML", value)
      return prefix .. q .. q
    end)
    -- unquoted values
    text = text:gsub("(%s" .. name .. "%s*=%s*)([^%s>\"']+)", function(prefix, value)
      if allowed(value) then return prefix .. value end
      report(attr .. "= in raw HTML", value)
      return prefix .. '""'
    end)
  end
  return text
end

function RawInline(el)
  if el.format:match("html") then el.text = clean_html(el.text) end
  return el
end

function RawBlock(el)
  if el.format:match("html") then el.text = clean_html(el.text) end
  return el
end
