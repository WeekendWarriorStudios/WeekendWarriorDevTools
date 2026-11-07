# Unreal Engine Production Guidance

Use the Unreal analysis documents as a discovery map. Many contain inferred or speculative details. Verify exact behavior in the target engine version, project source, plugin descriptor, module rules, or current Epic documentation before implementation.

## Architecture questions to answer

1. Who owns the state: world, game instance, local player, controller, pawn, component, subsystem, asset, or save data?
2. What is authoritative: server, owning client, local simulation, editor, build pipeline, or external service?
3. What must exist at runtime, and what can remain editor-only?
4. Which configuration belongs in code, data assets, project settings, or per-level content?
5. How will designers author, preview, validate, migrate, and debug it?
6. What is the lifetime, replication model, loading model, and failure behavior?
7. What evidence will reveal CPU, GPU, memory, network, streaming, or content regressions?

## Runtime/editor separation

- Keep editor modules out of packaged runtime dependency chains. Confirm module `Type`, loading phase, public/private dependencies, and conditional compilation from actual descriptors and `Build.cs` files.
- Avoid runtime references to editor-only asset types, widgets, utilities, or developer modules.
- Put asset creation, bulk processing, visualization, and validation in editor tooling; keep the shipped representation minimal and deterministic.
- Treat a plugin's “enabled by default,” beta, experimental, or content flags as metadata to verify, not proof of production suitability.

Relevant source documents include `Asset Manager Editor`, `Data Validation`, `Plugin Browser`, `Plugin Utilities`, `Automation Utilities`, `Editor Performance`, and source-control integration analyses.

## Input, cameras, AI, and gameplay systems

- For input, model actions separately from physical keys, apply mapping contexts by player state, and define conflict/remapping behavior. Verify the actual Enhanced Input APIs used by the project version.
- For cameras, separate desired framing from collision/occlusion resolution, blending, shake, and cinematic control. Make camera state observable and testable under split screen, variable frame rate, extreme geometry, and accessibility settings.
- For AI, specify sensing, decision ownership, movement, animation handoff, replication, debugging, and performance budgets. Do not infer AI architecture from a plugin title.
- Use gameplay tags for stable semantic classification when appropriate, but define ownership, replication, hierarchy, redirects, and validation rules.

Relevant source documents include `Enhanced Input`, `Gameplay Cameras`, `Camera Shake Previewer`, `CharacterAI`, `AISupport`, `Environment Query Editor`, and `GameplayTagsEditor`.

## Assets, streaming, and content pipelines

- Define primary asset identity, dependency direction, soft versus hard references, bundles, cooking rules, and async loading before scaling content.
- Build validation around naming, forbidden dependencies, missing metadata, platform restrictions, memory budgets, and stale redirects.
- For World Partition/HLOD, test streaming boundaries, actor ownership, data layers, cook output, traversal speed, memory, and representative target hardware.
- For import/export pipelines, record source-of-truth ownership, reimport behavior, deterministic settings, version compatibility, and how failures are surfaced.

Relevant source documents include `Asset Manager Editor`, `Asset Tags`, `Data Validation`, `World Partition HLOD Utilities`, `Interchange Framework`, `Datasmith Content`, `glTF Exporter`, `Geometry Cache`, and platform profile selectors.

## Rendering, VFX, audio, and animation

- Measure the actual bottleneck before changing quality. Separate game thread, render thread, RHI/GPU, memory, shader compilation, streaming, and editor overhead.
- Budget effects by aggregate scene cost, not isolated showcase cost. Include overdraw, translucency, simulation, bounds, collisions, lights, and scalability behavior.
- For animation systems, define authoring ownership, retargeting, runtime evaluation, LOD, compression, threading, and gameplay synchronization.
- For audio, account for concurrency, virtualization, spatialization, mix states, platform output, and debugging.

Relevant source documents include `Niagara`, `Chaos Niagara`, `MetaSound`, `Synthesis and DSP Effects`, `Control Rig`, `IK Rig`, `Animation Compression Library`, `RDG Insights`, `RenderDoc`, `PIX`, and `Dump GPU Services`.

## Multiplayer, online, platforms, and packaging

- Establish authority, prediction, reconciliation, session/lobby identity, reconnection, version compatibility, and offline behavior before selecting an online layer.
- Keep platform services behind project-owned interfaces when portability matters.
- Validate cook, package, chunk/install, entitlement, save, networking, device profile, and media behavior on real target hardware.
- Treat NULL or local online providers as development aids, not proof that platform authentication and lifecycle work.

Relevant source documents include `Online Subsystem`, provider-specific online subsystem analyses, `Online Base`, `MsQuic`, `Oodle Network`, `Chunk Downloader`, `Launcher Chunk Installer`, `Project Launcher`, and device-profile selectors.

## Verification hierarchy

Use the strongest available evidence in this order:

1. Target project's compiled code, configuration, assets, logs, traces, and tests.
2. Installed engine/plugin source and descriptors for the exact version.
3. Current Epic documentation and release notes for that version.
4. Reproduction in a minimal project.
5. Local Unreal analysis documents as leads and checklists.

If sources conflict, report the conflict and favor direct target-version evidence.
