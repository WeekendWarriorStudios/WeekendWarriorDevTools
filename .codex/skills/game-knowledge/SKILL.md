---
name: game-knowledge
description: Analyze, design, critique, or implement game systems and Unreal Engine workflows using the local game-design transcript library and Unreal plugin analyses. Use for mechanics, levels, controls, cameras, combat, puzzles, AI, progression, accessibility, game feel, prototyping, UE architecture, plugin selection, production risk, and design-to-implementation planning. Do not use for generic software work unrelated to games.
---

# Game Knowledge

Use the user's local knowledge library to turn a game question into a clear design argument, an implementation direction, or a testable production plan. Treat the library as evidence and inspiration, not as unquestionable authority.

## Source libraries

- Game-design transcripts: `C:\Users\pruss\My Drive\Documentation\YouTubeTranscripts\markdowns`
- Raw transcript JSON: `C:\Users\pruss\My Drive\Documentation\YouTubeTranscripts`
- Unreal analyses: `C:\Users\pruss\My Drive\Documentation\Unreal Engine\Markdowns`

The Unreal folder contains `.gdoc` pointers. Read `doc_id` from a pointer, then fetch that native Google Doc through the connected Google Drive tools. Never edit the pointer files.

## Route the request

Read only the references relevant to the job:

- For mechanics, controls, game feel, cameras, combat, challenge, progression, economies, accessibility, feedback, or tutorials, read [references/game-design.md](references/game-design.md).
- For level, world, puzzle, stealth, detective, systemic, narrative, or procedural design, read [references/worlds-and-systems.md](references/worlds-and-systems.md).
- For Unreal architecture, plugin choice, editor/runtime boundaries, content pipelines, profiling, validation, packaging, or production readiness, read [references/unreal-production.md](references/unreal-production.md).
- For critique, diagnosis, feature proposals, design documents, or design-to-implementation plans, read [references/deliverables.md](references/deliverables.md).
- When exact source support matters, read [references/evidence-and-retrieval.md](references/evidence-and-retrieval.md) and search the corpus with `scripts/search_game_knowledge.ps1`.

For mixed requests, read the smallest useful combination. Usually pair one design reference with `unreal-production.md` and `deliverables.md`.

## Working method

1. Identify the player experience, target audience, platform/input constraints, and production constraints that are known. State consequential assumptions instead of inventing requirements.
2. Frame the problem as a relationship between player verbs, information, decisions, feedback, consequences, and mastery. Do not begin with features or engine classes.
3. Search the source library for two to five relevant cases. Prefer cases with different failure modes or genres over a pile of similar examples.
4. Extract transferable principles. Separate what a source observed from the inference being made for this project.
5. If Unreal implementation is involved, map the design to data ownership, runtime/editor boundaries, content authoring, observability, validation, and platform constraints.
6. Produce a concrete recommendation with alternatives, tradeoffs, failure modes, and a cheap validation plan.

## Non-negotiable reasoning rules

- Preserve the user's creative direction. Use references to sharpen it, not replace it with the cited game's solution.
- Diagnose before prescribing. A request such as “make combat better” requires an explicit hypothesis about what currently feels wrong.
- Prefer a small number of interacting rules over isolated feature count. Depth comes from meaningful combinations, not surface complexity alone.
- Treat controls, camera, animation, audio, VFX, UI, and timing as one feedback loop when evaluating game feel.
- Treat accessibility as configurable access to information, timing, execution, and consequence—not as a single global difficulty slider.
- Distinguish intrinsic motivation, extrinsic rewards, and retention pressure. Do not recommend manipulative engagement patterns.
- For Unreal claims, distinguish verified project/engine facts from source summaries and speculation. Never invent class names, module names, console commands, descriptor fields, or version history.
- Do not present a transcript's opinion or an Unreal analysis document's confidence as consensus. Cite the local source title when a recommendation materially depends on it.

## Output standard

Match the artifact to the request, but make decisions inspectable. A useful answer normally contains:

- the intended player experience or production outcome;
- the diagnosed tension or opportunity;
- the recommended design/architecture;
- why it should work, grounded in relevant cases;
- important tradeoffs and risks;
- a prototype or playtest with observable success criteria;
- for Unreal work, implementation boundaries and verification steps.

Keep facts, assumptions, proposals, and open questions visibly distinct. If the source library does not support a claim, say so and rely on direct project evidence or current authoritative documentation.
