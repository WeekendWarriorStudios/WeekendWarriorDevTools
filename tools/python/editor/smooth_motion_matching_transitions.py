"""Tune a Motion Matching node for smooth starts, stops and pivots.

Motion matching re-picks a pose every frame. Left at defaults that reads as a jitter on exactly
the transitions where the pose changes most — starts, stops and pivots — for three separate
reasons, all fixable in the node's settings:

* ``bUseInertialBlend`` is **false** by default, so switching pose does a crossfade between two
  clips rather than an inertial blend. Crossfades on locomotion look like a limb briefly doing
  both things at once. Inertial blending instead carries the current pose's velocity into the new
  one, which is what makes a stop look like a deceleration rather than a cut. It requires an
  ``Inertialization`` node downstream in the same pose chain, which this script inserts.

* ``PlayRate`` is clamped to exactly ``(1.0, 1.0)``, so the node cannot time-warp a clip even
  slightly to match the character's real speed. Any mismatch between the movement model and the
  animation has to come out as foot sliding or a pose pop. A small window lets it absorb that.

* ``PoseJumpThresholdTime`` is ``(0, 0)``, so nothing stops the search hopping between two poses a
  few frames apart *within the same clip* — visually a stutter, since the two poses are nearly
  identical but not quite. A threshold makes it stay put unless a genuinely better match appears.

Values below are a starting point for infantry locomotion, not a universal answer: raise
``BlendTime`` for heavier characters, lower it for twitchier ones. Everything is overridable.

Run it
------
    UnrealEditor-Cmd.exe <Project>.uproject -run=pythonscript ^
        -script="...\\smooth_motion_matching_transitions.py" -unattended -nopause -nosplash
"""

from __future__ import annotations

import unreal

from editor_toolset.toolsets.blueprint import BlueprintTools as BT

MOTION_MATCHING = "PoseSearch|MotionMatching"
INERTIALIZATION = "Animation|Misc.|Inertialization"

# Applied to FAnimNode_MotionMatching. Each entry is (candidate property names, value) — UE's
# Python bindings strip the Hungarian `b` from bools inconsistently across versions, so both
# spellings are tried rather than assumed.
DEFAULT_SETTINGS = [
    (("b_use_inertial_blend", "use_inertial_blend"), True),
    (("blend_time",), 0.25),
    (("pose_reselect_history",), 0.3),
]


def _set_first(struct_value, names, value) -> str | None:
    for name in names:
        try:
            struct_value.set_editor_property(name, value)
            return name
        except Exception:
            continue
    return None


def _pin(info, name, outputs=False):
    for p in (info.output_pins if outputs else info.input_pins):
        if str(p.name) == name:
            return p
    raise RuntimeError(f"{info.type_id} has no pin {name!r}")


def _infos(graph):
    return BT.get_node_infos(BT.find_nodes(graph))


def tune(
    anim_bp_path: str,
    blend_time: float = 0.25,
    play_rate_min: float = 0.8,
    play_rate_max: float = 1.2,
    pose_jump_threshold: float = 0.2,
    add_inertialization: bool = True,
    save: bool = True,
) -> bool:
    blueprint = unreal.EditorAssetLibrary.load_asset(anim_bp_path)
    if blueprint is None:
        raise RuntimeError(f"Could not load {anim_bp_path}")

    graph = None
    for candidate in BT.list_graphs(blueprint):
        if str(candidate.get_name()) == "AnimGraph":
            graph = candidate
    if graph is None:
        raise RuntimeError("No AnimGraph")

    infos = _infos(graph)
    mm_infos = [i for i in infos if str(i.type_id) == MOTION_MATCHING]
    if not mm_infos:
        raise RuntimeError(f"No {MOTION_MATCHING} node in {anim_bp_path}")

    changed = False

    for info in mm_infos:
        node = info.node
        settings = node.get_editor_property("Node")

        applied = []
        for names, value in DEFAULT_SETTINGS:
            value = blend_time if names[0] == "blend_time" else value
            hit = _set_first(settings, names, value)
            applied.append(f"{hit or names[0]}={value}{'' if hit else ' (FAILED)'}")

        # Float intervals are structs in their own right.
        try:
            play_rate = unreal.FloatInterval()
            play_rate.set_editor_property("min", play_rate_min)
            play_rate.set_editor_property("max", play_rate_max)
            settings.set_editor_property("play_rate", play_rate)
            applied.append(f"play_rate=({play_rate_min}, {play_rate_max})")
        except Exception as err:
            applied.append(f"play_rate FAILED ({err})")

        try:
            jump = unreal.FloatInterval()
            jump.set_editor_property("min", -pose_jump_threshold)
            jump.set_editor_property("max", pose_jump_threshold)
            settings.set_editor_property("pose_jump_threshold_time", jump)
            applied.append(f"pose_jump_threshold_time=(±{pose_jump_threshold})")
        except Exception as err:
            applied.append(f"pose_jump_threshold_time FAILED ({err})")

        # Structs are value types in Python; the mutated copy has to be written back.
        node.set_editor_property("Node", settings)
        changed = True
        unreal.log(f"[smooth] {MOTION_MATCHING}: " + ", ".join(applied))

    # ---- Inertialization ------------------------------------------------
    if add_inertialization:
        if [i for i in infos if str(i.type_id) == INERTIALIZATION]:
            unreal.log("[smooth] an Inertialization node is already present")
        else:
            # It has to sit downstream of the Motion Matching node for inertial blending to have
            # anything to act on. Placing it at the very end of the local-space chain also means
            # montage blends through the Slot get smoothed by the same node.
            tail = None
            for info in infos:
                if str(info.type_id) in ("Animation|Montage|Slot'DefaultSlot'", "PoseSearch|PoseHistory"):
                    tail = info
                    if "Slot" in str(info.type_id):
                        break
            if tail is None:
                raise RuntimeError("Could not find a Slot or Pose History node to insert after")

            downstream = list(_pin(tail, "Pose", outputs=True).connected_pins)
            inert = BT.create_node(graph, INERTIALIZATION, unreal.IntPoint(-300, 60))
            if not inert:
                raise RuntimeError(f"Could not create {INERTIALIZATION}")
            inert_info = BT.get_node_infos([inert])[0]

            BT.connect_pins(_pin(tail, "Pose", outputs=True).pin_id, _pin(inert_info, "Source").pin_id)
            for target in downstream:
                BT.connect_pins(_pin(inert_info, "Pose", outputs=True).pin_id, target)
            unreal.log(f"[smooth] inserted Inertialization after {tail.type_id}")
            changed = True

    if changed:
        BT.compile_blueprint(blueprint)
        if save:
            unreal.EditorAssetLibrary.save_loaded_asset(blueprint, only_if_is_dirty=False)
            unreal.log(f"[smooth] compiled and saved {anim_bp_path}")
    return changed


if __name__ == "__main__":
    tune("/MovementLocomotion/Movement/Human/AnimBlueprints/CD_MovementLocomotion")
