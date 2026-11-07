-- EPUB filter with --keep-extras: keep readable study aids (key ideas, summaries,
-- steps, pull quotes) but drop what only works interactively.
local drop = { quiz = true, flashcards = true, notes = true, widget = true, ["interactive-only"] = true }

function Div(el)
  for _, c in ipairs(el.classes) do
    if drop[c] then return {} end
  end
  return nil
end
