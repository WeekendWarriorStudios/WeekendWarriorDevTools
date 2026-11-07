# Game Design Reasoning

Use this reference for player-facing mechanics and moment-to-moment experience.

## Start from the experience loop

Model a feature as `perception -> interpretation -> decision -> action -> feedback -> consequence -> learning`.

Find the weakest link. More content rarely repairs unclear perception, low-agency decisions, mushy action, weak feedback, or consequences that do not teach.

## Player verbs and depth

- Prefer versatile verbs that solve multiple problem types. Mario's jump, Shovel Knight's shovel, Prey's Gloo Cannon, and Downwell's gun-boots are useful cases because one action supports traversal, combat, defense, economy, or expression.
- Evaluate a verb by readability, responsiveness, expressive range, interactions, and the quality of decisions around it—not by animation count.
- Create depth through orthogonal pressures: space, timing, target priority, resource state, risk, information, and positioning. Avoid adding redundant moves that solve the same situation in the same way.
- Teach through safe introduction, focused development, surprising twist, and synthesis. `Super Mario 3D World's 4 Step Level Design` and `How Mega Man 11's Levels Do More With Less` are strong search anchors.

## Game feel and feedback

Treat feel as a coordinated stack: input sampling and buffering; acceleration, deceleration, anticipation, and recovery; collision and target forgiveness; camera framing, lag, shake, and occlusion; animation pose clarity and timing; audio transients and dynamic mix; VFX, hit-stop, deformation, and UI response; and state clarity before, during, and after the action.

Tune for the desired fantasy, not maximum intensity. Excessive shake, particles, latency, or hit-stop can reduce readability and comfort. Search anchors: `Secrets of Game Feel and Juice`, `Why Does Celeste Feel So Good to Play`, `Forging God of War's Leviathan Axe`, `The Challenge of Cameras`, and `How to Make a Good 2D Camera`.

## Challenge, failure, and accessibility

- Separate cognitive challenge, execution challenge, endurance, information burden, and punishment. Adjust the dimension causing exclusion without flattening the rest.
- Use invisible assistance when it preserves intent: coyote time, input buffering, dynamic recovery, encounter pacing, contextual hints, and forgiving checkpoints.
- Use explicit assist options when players need agency over timing, execution, perception, or consequence. Explain effects plainly and avoid moralizing labels.
- Failure should create information, tension, or a meaningful new state. Repetition without learning is usually friction.

Search anchors: `Super Mario's Invisible Difficulty Settings`, `What Makes Celeste's Assist Mode Special`, `How Accessible Were`, `Should Dark Souls Have an Easy Mode`, `Playing Past Your Mistakes`, and `Redesigning Death`.

## Progression, economies, and rewards

- Distinguish player learning, character power, content access, and status. A progression system can advance one without inflating all four.
- Skill trees should create playstyle commitments or new decisions, not merely hide expected baseline functionality behind incremental percentages.
- Map every source and sink. Check faucet rates, stockpiling, dominant purchases, runaway feedback, and whether scarcity supports the intended emotion.
- Extrinsic rewards can crowd out curiosity or mastery when they become the reason to perform an already satisfying action. Use rewards to expose possibility, mark achievement, or support goals—not to replace the core pleasure.

Search anchors: `Building Better Skill Trees`, `Roguelikes, Persistency, and Progression`, `How Video Game Economies are Designed`, `How Games Use Feedback Loops`, `This Psychological Trick Makes Rewards Backfire`, and `How to Keep Players Engaged (Without Being Evil)`.

## Controls and camera

- Input mappings communicate what matters. Prioritize frequent, time-sensitive, combinable actions; avoid chords or holds that conflict with simultaneous play.
- Context-sensitive actions reduce button count but increase ambiguity. Use them only when context is legible and the wrong action is cheap or preventable.
- Camera behavior is part of control. Define what the player must see, when autonomy may be taken, how targets and hazards affect framing, and how motion comfort is protected.
- Test with different devices, remapping needs, handedness, motor constraints, and frame rates.

Search anchors: `Controllers Control Everything`, `A Deep Dive into Star Fox Zero's Controls`, `Does Spidey's Web-Swinging`, `Can I fix Zelda's UI`, and `The Power of Video Game HUDs`.

## Combat and AI

- Combat quality depends on the pressure topology: movement, enemy roles, arena geometry, resource cadence, and readable threat—not only weapon statistics.
- Give enemy roles complementary jobs and readable states. A good enemy changes player decisions before it deals damage.
- AI should be legible enough to form plans and variable enough to avoid rote execution. Apparent intelligence often comes from sensing rules, animation, barks, search behavior, and encounter staging.
- Balance through explicit goals and matchup data. Protect viable strategies without forcing numerical symmetry.

Search anchors: `The 4 Ps of DOOM's Amazing Combat`, `What Makes a Good Combat System`, `How Games Get Balanced`, `What Makes Good AI`, `How Stealth Game Guards See and Hear`, `How do Stealth Games Deal with Detection`, and `How Cuphead's Bosses (Try to) Kill You`.
