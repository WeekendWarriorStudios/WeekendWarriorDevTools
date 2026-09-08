"""Replace a hand-rolled motion-matching AnimGraph with the real Motion Matching node.

Epic's `UPoseSearchLibrary::MotionMatch` Blueprint function returns an (animation, time) pair plus
a play rate, a loop flag and a mirror flag. A common mistake is to feed only the animation into a
Sequence Player and push the time into its `StartPosition` pin — which looks right and is not.
`FAnimNode_SequencePlayerBase::UpdateAssetPlayer` never reads `StartPosition`; only
`Initialize_AnyThread` does. From the second frame onward the matched time is discarded, each newly
selected clip resumes at the previous clip's playhead, and the play rate, looping and mirroring are
dropped too. There is no blend stack either, so every change of selection is a hard cut.

`FAnimNode_MotionMatching` does all of that internally — continuing-pose bias, the blend stack, time,
play rate, loop and mirror. This script rewires the graph to use it:

    Motion Matching (Database <- SelectedDatabase)
      -> Pose History        (trajectory already wired; see wire_trajectory_to_pose_history.py)
      -> Slot 'DefaultSlot'  (so montages are actually visible)
      -> ... whatever post-processing already followed the Pose History node

and reduces the thread-safe update function to a single Chooser evaluation that stores the chosen
database, replacing the MotionMatch / MakeArray / Break / Cast / Set chain.

It is idempotent: a graph already containing a Motion Matching node is left alone.

Run it
------
    UnrealEditor-Cmd.exe <Project>.uproject -run=pythonscript ^
        -script="...\\rebuild_motion_matching_animgraph.py" -unattended -nopause -nosplash
"""

from __future__ import annotations

import unreal

from editor_toolset.toolsets.blueprint import BlueprintTools as BT

MOTION_MATCHING = "PoseSearch|MotionMatching"
POSE_HISTORY = "PoseSearch|PoseHistory"
SLOT = "Animation|Montage|Slot'DefaultSlot'"

# Nodes the old hand-rolled approach needed and the Motion Matching node makes redundant.
DEAD_ANIMGRAPH_TYPES = {
    "Animation|Sequences|SequencePlayer",
    "Utilities|Casting|CastToAnimSequenceBase",
    "|GetSelectedAnim",
    "|GetSelectedAnimTime",
}
DEAD_FUNCTION_TYPES = {
    "Animation|PoseSearch|MotionMatch",
    "Utilities|Array|MakeArray",
    "Utilities|Struct|BreakPoseSearchBlueprintResult",
    "Utilities|Casting|CastToAnimationAsset",
    "|SetSelectedAnim",
    "|SetSelectedAnimTime",
}


def _pin(info, name, outputs=False):
    for p in (info.output_pins if outputs else info.input_pins):
        if str(p.name) == name:
            return p
    raise RuntimeError(
        f"{info.type_id} has no {'output' if outputs else 'input'} pin {name!r}; "
        f"saw {[str(p.name) for p in (info.output_pins if outputs else info.input_pins)]}"
    )


def _infos(graph):
    return BT.get_node_infos(BT.find_nodes(graph))


def _by_type(infos, type_id):
    return [i for i in infos if str(i.type_id) == type_id]


def _create_variable_node(graph, accessor: str, pos):
    """Create a variable getter/setter node, e.g. accessor='GetSelectedDatabase'.

    Two id shapes exist and neither covers both cases. A C++ UPROPERTY is namespaced by its
    Blueprint category (``Variables|CollateralDamage|Locomotion|GetTrajectory``) and *is*
    discoverable through find_node_types. A Blueprint-declared variable uses the bare
    ``|SetSelectedAnim`` form and is not listed by find_node_types at all — so discovery alone
    is not enough, and neither is hard-coding. Try the discovered ids first, then the bare forms.
    """
    candidates = [t for t in BT.find_node_types(graph, accessor)
                  if t.startswith("Variables|") and t.rsplit("|", 1)[-1] == accessor]
    candidates += [f"|{accessor}", f"Variables|Default|{accessor}"]

    errors = []
    for type_id in candidates:
        try:
            return BT.create_node(graph, type_id, pos)
        except Exception as err:  # create_node asserts when the type id does not resolve
            errors.append(f"{type_id}: {err}")
    raise RuntimeError(f"Could not create a variable node for {accessor!r}. Tried:\n  " +
                       "\n  ".join(errors))


def _graph(blueprint, name):
    for g in BT.list_graphs(blueprint):
        if str(g.get_name()) == name:
            return g
    raise RuntimeError(f"No graph named {name!r}")


def rebuild(
    anim_bp_path: str,
    database_variable: str = "SelectedDatabase",
    add_slot: bool = True,
    save: bool = True,
) -> bool:
    blueprint = unreal.EditorAssetLibrary.load_asset(anim_bp_path)
    if blueprint is None:
        raise RuntimeError(f"Could not load {anim_bp_path}")

    anim_graph = _graph(blueprint, "AnimGraph")
    fn_graph = _graph(blueprint, "BlueprintThreadSafeUpdateAnimation")

    if _by_type(_infos(anim_graph), MOTION_MATCHING):
        unreal.log("[rebuild] a Motion Matching node is already present — nothing to do")
        return False

    # ---- 1. the property the Chooser result lands in ---------------------
    # Expected to already exist on the C++ AnimInstance base class. See _create_variable_node
    # for why a Blueprint-side variable cannot work here.

    # ---- 2. thread-safe update: chooser -> set variable -----------------
    infos = _infos(fn_graph)
    chooser = [i for i in infos if str(i.type_id).startswith("Animation|EvaluateChooser")]
    if not chooser:
        raise RuntimeError("No EvaluateChooser node in BlueprintThreadSafeUpdateAnimation")
    chooser = chooser[0]

    for info in infos:
        if str(info.type_id) in DEAD_FUNCTION_TYPES:
            BT.delete_node(info.node)
            unreal.log(f"[rebuild] removed {info.type_id} from the update function")

    setter = _create_variable_node(fn_graph, f"Set{database_variable}", unreal.IntPoint(500, 0))
    setter_info = BT.get_node_infos([setter])[0]
    chooser_info = BT.get_node_infos([chooser.node])[0]

    BT.connect_pins(_pin(chooser_info, "execute", outputs=True).pin_id,
                    _pin(setter_info, "execute").pin_id)
    BT.connect_pins(_pin(chooser_info, "Result", outputs=True).pin_id,
                    _pin(setter_info, database_variable).pin_id)
    unreal.log(f"[rebuild] update function now: EvaluateChooser -> Set {database_variable}")

    # ---- 3. AnimGraph ---------------------------------------------------
    infos = _infos(anim_graph)
    history = _by_type(infos, POSE_HISTORY)
    if not history:
        raise RuntimeError(f"No {POSE_HISTORY} node in the AnimGraph")
    history = history[0]

    # Remember what the Pose History currently feeds, so the Slot can be spliced in front of it.
    downstream = list(_pin(history, "Pose", outputs=True).connected_pins)

    for info in infos:
        if str(info.type_id) in DEAD_ANIMGRAPH_TYPES:
            BT.delete_node(info.node)
            unreal.log(f"[rebuild] removed {info.type_id} from the AnimGraph")

    mm = BT.create_node(anim_graph, MOTION_MATCHING, unreal.IntPoint(-1100, 0))
    mm_info = BT.get_node_infos([mm])[0]

    getter = _create_variable_node(anim_graph, f"Get{database_variable}", unreal.IntPoint(-1400, 120))
    getter_info = BT.get_node_infos([getter])[0]

    BT.connect_pins(_pin(getter_info, database_variable, outputs=True).pin_id,
                    _pin(mm_info, "Database").pin_id)

    history_info = BT.get_node_infos([history.node])[0]
    BT.connect_pins(_pin(mm_info, "Pose", outputs=True).pin_id,
                    _pin(history_info, "Source").pin_id)
    unreal.log("[rebuild] Motion Matching -> Pose History")

    if add_slot and downstream:
        slot = BT.create_node(anim_graph, SLOT, unreal.IntPoint(-500, 0))
        slot_info = BT.get_node_infos([slot])[0]
        BT.connect_pins(_pin(history_info, "Pose", outputs=True).pin_id,
                        _pin(slot_info, "Source").pin_id)
        for target in downstream:
            BT.connect_pins(_pin(slot_info, "Pose", outputs=True).pin_id, target)
        unreal.log("[rebuild] spliced Slot 'DefaultSlot' after the Pose History node")

    # ---- 4. drop the now-unused variables --------------------------------
    for stale in ("SelectedAnim", "SelectedAnimTime"):
        if stale in [str(v) for v in BT.list_variables(blueprint)]:
            BT.remove_variable(blueprint, stale)
            unreal.log(f"[rebuild] removed unused variable {stale}")

    BT.compile_blueprint(blueprint)
    if save:
        unreal.EditorAssetLibrary.save_loaded_asset(blueprint, only_if_is_dirty=False)
        unreal.log(f"[rebuild] compiled and saved {anim_bp_path}")
    return True


if __name__ == "__main__":
    rebuild("/MovementLocomotion/Movement/Human/AnimBlueprints/CD_MovementLocomotion")
