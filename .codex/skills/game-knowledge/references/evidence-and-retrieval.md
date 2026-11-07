# Evidence and Retrieval

## Search the transcript library

Run:

```powershell
& scripts/search_game_knowledge.ps1 -Query 'camera framing occlusion' -Source Transcripts -Context 2
```

Search concise concepts, synonyms, and known title words. Use several small searches rather than one long natural-language query. Read the full matching Markdown before relying on a passage.

Useful title families:

- feel and controls: `Game Feel`, `Celeste`, `Controllers`, `Camera`, `Movement`, `Jump`;
- combat and AI: `Combat`, `DOOM`, `Stealth`, `AI`, `Bosses`, `Balance`;
- levels and worlds: `Level`, `World`, `Mario`, `Zelda`, `Elden Ring`, `Deus Ex`;
- puzzles and mystery: `Puzzle`, `Detective`, `Obra Dinn`, `Baba`, `Jonathan Blow`;
- systems and emergence: `Systemic`, `Immersive Sim`, `Nemesis`, `Spelunky`, `Random`;
- progression and motivation: `Skill Trees`, `Progression`, `Economies`, `Rewards`, `Engaged`;
- accessibility and teaching: `Accessible`, `Assist Mode`, `Tutorial`, `Difficulty`, `Protect Players`.

## Read Unreal analyses

The `.gdoc` files are JSON pointers containing a `doc_id`. Extract it without modifying the file, then use the Google Drive document-text read action. Search filenames first to narrow the 163-document library.

The Unreal analyses frequently use phrases such as “likely,” “may,” or confident-looking class/module names without primary evidence. Classify each claim:

- **Observed:** directly supported by descriptor metadata, code, logs, or fetched document evidence.
- **Corroborated:** confirmed by target-version engine source or authoritative documentation.
- **Inferred:** reasonable architectural interpretation, still requiring verification.
- **Speculative:** unsupported possibility or invented detail; do not repeat as fact.

## Source use

- Cite local sources by human-readable title; include the video ID or document filename when ambiguity matters.
- Paraphrase and synthesize. Quote only the short phrase necessary to preserve meaning.
- Use examples to support a principle, then explain why that principle transfers to the current project.
- Record counterexamples or boundary conditions. A technique that works for a precision platformer may be wrong for horror, simulation, multiplayer, or accessibility needs.
- If a recommendation depends on engine-version behavior, verify it outside the secondary analysis document.
