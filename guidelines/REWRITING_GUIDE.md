# LoreKit -- Story Rewriting Guide

After a session ends, the player may want to turn the adventure into a
readable story. Use `export_dump` to dump all session data, then rewrite
it as prose narrative in Markdown.

## Guidelines

- **Few chapters, long scenes.** Group related events into large, continuous
  chapters. Do not create one chapter per scene. Each chapter should
  contain multiple beats that flow naturally into each other. Short chapters
  fragment the reading rhythm -- prefer fewer, denser ones.
- **Use the story acts as a skeleton.** Each act in the story plan maps
  roughly to one or two chapters. Let the act structure guide where to place
  chapter breaks -- at major turning points, not at every pause in action.
- **Prose, not screenplay.** Narrate fully. Expand terse timeline entries into
  vivid prose with atmosphere, physical detail, and interiority. Dialogue
  should be woven into the narration, not listed.
- **Preserve the player character's voice.** If the character was silent,
  keep them silent. If they were humorous, keep the humor. Do not flatten
  the character to fit a generic heroic template.
- **Include an epilogue** only if the timeline has one. Do not invent closure
  that did not happen in play.
- **Save the story to `stories/`.** Write the finished Markdown file to the
  `stories/` directory at the project root, using a descriptive filename
  (e.g. `stories/o_bastiao_de_talassa.md`).
