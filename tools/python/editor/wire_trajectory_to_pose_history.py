"""Connect an AnimInstance's trajectory property to the Pose History node's Trajectory pin.

Motion matching builds its query from two halves: the recent pose history, which the Pose History
node collects itself, and the *trajectory* — where the character has been and where it is heading.
The second half has to be supplied. If it is not, the query describes a character standing still
and the search returns near-idle poses no matter how fast the character is actually moving. Nothing
is logged, in the editor or at runtime.

The node can generate its own trajectory (`bGenerateTrajectory`), but that path calls
`FPoseSearchTrajectoryData::UpdateData`, which reads `ACharacter::GetCharacterMovement()`. On a
project driven by Chaos Mover the legacy `UCharacterMovementComponent` is typically parked at
`MOVE_None` with ticking off, so it reports zero velocity, zero acceleration and a zero max speed
forever. The fix is to feed the pin from a property the AnimInstance fills itself — for Mover, via
`UMoverTrajectoryPredictor` and `UPoseSearchTrajectoryLibrary::PoseSearchGenerateTransformTrajectoryWithPredictor`.

This script wires that pin. It is idempotent: an already-connected pin is left alone.

Run it
------
    python ue_remote_exec.py --file wire_trajectory_to_pose_history.py

or headless, with no editor running:

    UnrealEditor-Cmd.exe <Project>.uproject -run=pythonscript ^
        -script="...\\wire_trajectory_to_pose_history.py" -unattended -nopause -nosplash

Configure the target at the bottom of the file, or call `wire()` yourself from the console.
"""

from __future__ import annotations

import unreal

from editor_toolset.toolsets.blueprint import BlueprintTools as BT

POSE_HISTORY_TYPES = ("PoseSearch|PoseHistory", "PoseSearch|ComponentSpacePoseHistory")
TRAJECTORY_PIN = "TransformTrajectory"


def _find_pin(info, name: str, outputs: bool = False):
    pins = info.output_pins if outputs else info.input_pins
    for pin in pins:
        if str(pin.name) == name:
            return pin
    return None


def _resolve_getter_type_id(graph, property_name: str) -> str:
    """Find the node type id for a variable getter.

    The id is not simply ``|Get<Name>``: it is namespaced by the property's Blueprint category,
    so a C++ UPROPERTY declared with ``Category = "CollateralDamage|Locomotion|Trajectory"``
    becomes ``Variables|CollateralDamage|Locomotion|Trajectory|GetTrajectory``. Discovering it
    rather than hard-coding it means re-categorising the property in C++ does not break this.
    """
    wanted = f"Get{property_name}"
    matches = [t for t in graph_node_types(graph, wanted)
               if t.startswith("Variables|") and t.rsplit("|", 1)[-1] == wanted]
    if not matches:
        raise RuntimeError(
            f"No variable getter found for {property_name!r}. Either the property does not exist "
            f"on the AnimInstance class, it is not BlueprintReadOnly/BlueprintReadWrite, or the "
            f"module has not been recompiled since it was added."
        )
    if len(matches) > 1:
        raise RuntimeError(f"Ambiguous getter for {property_name!r}: {matches}")
    return matches[0]


def graph_node_types(graph, filter_text: str) -> list[str]:
    return list(BT.find_node_types(graph, filter_text))


def wire(
    anim_bp_path: str,
    trajectory_property: str = "Trajectory",
    graph_name: str = "AnimGraph",
    getter_position=(-1150, 120),
    save: bool = True,
) -> bool:
    """Connect ``trajectory_property`` to every Pose History node's Trajectory pin.

    Returns True if the asset was modified.
    """
    blueprint = unreal.EditorAssetLibrary.load_asset(anim_bp_path)
    if blueprint is None:
        raise RuntimeError(f"Could not load {anim_bp_path}")

    graph = None
    for candidate in BT.list_graphs(blueprint):
        if str(candidate.get_name()) == graph_name:
            graph = candidate
    if graph is None:
        raise RuntimeError(f"{anim_bp_path} has no graph named {graph_name!r}")

    infos = BT.get_node_infos(BT.find_nodes(graph))
    history_infos = [i for i in infos if str(i.type_id) in POSE_HISTORY_TYPES]
    if not history_infos:
        raise RuntimeError(f"No Pose History node in {graph_name}; nothing to wire")

    changed = False
    for info in history_infos:
        pin = _find_pin(info, TRAJECTORY_PIN)
        if pin is None:
            unreal.log_warning(
                f"[trajectory] {info.type_id} has no {TRAJECTORY_PIN} pin — it is probably set to "
                f"generate its own trajectory (bGenerateTrajectory), which hides the pin. Turn that "
                f"off first."
            )
            continue

        if len(pin.connected_pins) > 0:
            unreal.log(f"[trajectory] {info.type_id}.{TRAJECTORY_PIN} already connected — skipping")
            continue

        getter_type_id = _resolve_getter_type_id(graph, trajectory_property)
        getter = BT.create_node(graph, getter_type_id,
                                unreal.IntPoint(int(getter_position[0]), int(getter_position[1])))
        getter_info = BT.get_node_infos([getter])[0]
        source = _find_pin(getter_info, trajectory_property, outputs=True)
        if source is None:
            outs = [str(p.name) for p in getter_info.output_pins]
            raise RuntimeError(
                f"Variable getter for {trajectory_property!r} produced no matching output pin "
                f"(saw {outs}). Check the property exists on the AnimInstance class and that the "
                f"module has been compiled."
            )

        BT.connect_pins(source.pin_id, pin.pin_id)
        unreal.log(f"[trajectory] connected {trajectory_property} -> {info.type_id}.{TRAJECTORY_PIN}")
        changed = True

    if changed:
        BT.compile_blueprint(blueprint)
        if save:
            unreal.EditorAssetLibrary.save_loaded_asset(blueprint, only_if_is_dirty=False)
            unreal.log(f"[trajectory] compiled and saved {anim_bp_path}")
    else:
        unreal.log("[trajectory] nothing to do")

    return changed


if __name__ == "__main__":
    wire("/MovementLocomotion/Movement/Human/AnimBlueprints/CD_MovementLocomotion")
