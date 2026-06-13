"""
Procedurally spawn actors in a grid pattern in the current editor level.
Run from the Unreal Editor Python console or an Editor Utility Widget.

Usage (editor console):
    import spawn_procedural_grid
    spawn_procedural_grid.spawn_grid(
        actor_path="/Game/Core/Environment/BP_GridNode.BP_GridNode_C",
        rows=10,
        cols=10,
        spacing=300.0,
        origin=(0.0, 0.0, 0.0)
    )
"""

import unreal
from typing import Tuple


def spawn_grid(
    actor_path: str,
    rows: int = 10,
    cols: int = 10,
    spacing: float = 300.0,
    origin: Tuple[float, float, float] = (0.0, 0.0, 0.0),
    mark_procedural: bool = True,
    dry_run: bool = False,
) -> list:
    """
    Spawn actors in a rows x cols grid centered on `origin`.
    Returns list of spawned actors (empty on dry_run).
    """
    editor_asset_subsystem = unreal.get_editor_subsystem(unreal.EditorAssetSubsystem)
    actor_subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)

    actor_class = editor_asset_subsystem.load_asset(actor_path)
    if not actor_class:
        unreal.log_error(f"Could not load actor class: {actor_path}")
        return []

    ox, oy, oz = origin
    # Center the grid on the origin
    offset_x = (rows - 1) * spacing / 2.0
    offset_y = (cols - 1) * spacing / 2.0

    spawned = []
    rotation = unreal.Rotator(0.0, 0.0, 0.0)

    total = rows * cols
    unreal.log(f"Spawning {total} actors ({rows}x{cols}, spacing={spacing}) from '{actor_path}'...")

    with unreal.ScopedEditorTransaction("Spawn Procedural Grid") as trans:
        for r in range(rows):
            for c in range(cols):
                location = unreal.Vector(
                    ox + r * spacing - offset_x,
                    oy + c * spacing - offset_y,
                    oz,
                )

                if dry_run:
                    unreal.log(f"  [DRY RUN] Would spawn at {location}")
                    continue

                actor = actor_subsystem.spawn_actor_from_class(actor_class, location, rotation)
                if actor:
                    if mark_procedural:
                        try:
                            actor.set_editor_property("bIsProcedurallyGenerated", True)
                        except Exception:
                            pass  # property may not exist on all actor types
                    spawned.append(actor)

    if dry_run:
        unreal.log(f"Dry run complete. Would have spawned {total} actors.")
    else:
        unreal.log(f"Spawned {len(spawned)} actors successfully.")

    return spawned


def clear_procedural_actors(actor_path: str) -> int:
    """Remove all actors in the current level that were spawned from actor_path."""
    actor_subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    editor_asset_subsystem = unreal.get_editor_subsystem(unreal.EditorAssetSubsystem)

    actor_class = editor_asset_subsystem.load_asset(actor_path)
    if not actor_class:
        unreal.log_error(f"Could not load actor class: {actor_path}")
        return 0

    all_actors = actor_subsystem.get_all_level_actors()
    to_delete = [a for a in all_actors if isinstance(a, actor_class)]

    with unreal.ScopedEditorTransaction("Clear Procedural Grid") as trans:
        actor_subsystem.destroy_actors(to_delete)

    unreal.log(f"Removed {len(to_delete)} procedural actors.")
    return len(to_delete)
