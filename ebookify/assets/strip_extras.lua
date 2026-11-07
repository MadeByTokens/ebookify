-- Default EPUB filter: drop every block the agent added (study aids, speaker notes,
-- widgets) so the EPUB is a faithful reading copy of the source.
local drop = {
  quiz = true, flashcards = true, notes = true, widget = true, ["interactive-only"] = true,
  keyidea = true, summary = true, tip = true, note = true, steps = true, pull = true,
}

function Div(el)
  for _, c in ipairs(el.classes) do
    if drop[c] then return {} end
  end
  return nil
end
