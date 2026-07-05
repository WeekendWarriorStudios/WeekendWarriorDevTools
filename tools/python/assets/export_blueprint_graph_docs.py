"""
Export every Blueprint's graph nodes and pin wiring to human-readable markdown.

Blueprint EventGraph/FunctionGraph/MacroGraph node and pin data isn't reachable through
generic Python reflection: UEdGraphPin stopped being a UObject around UE 4.24 (a compile-time
performance change), so its Direction/PinType/LinkedTo fields are invisible to
get_editor_property. This script instead calls
unreal.BlueprintGraphExportLibrary.export_blueprint_graphs_to_text() (a small C++ bridge in
Plugins/ColossusMCPTools) which wraps FEdGraphUtilities::ExportNodesToText — the same engine
facility that backs Blueprint node copy/paste — then parses that text into markdown here.

Run from the Unreal Editor Python console:
    import sys
    sys.path.insert(0, r"A:\Projects\ColossusRising\WeekendWarriorDevTools\tools\python\assets")
    import export_blueprint_graph_docs as ebgd
    ebgd.export_all_blueprint_docs()

Output layout (default):
    Documentation/generated-api/content/Project/<BlueprintName>.md
    Documentation/generated-api/content/Plugins/<PluginRoot>/<BlueprintName>.md
"""

import glob
import json
import os
import re

import unreal


# ---------------------------------------------------------------------------
# T3D-style text parsing (matches FEdGraphUtilities::ExportNodesToText output)
# ---------------------------------------------------------------------------

_BEGIN_OBJECT_RE = re.compile(r'^\s*Begin Object Class=(?P<cls>\S+)\s+Name="(?P<name>[^"]+)"', re.MULTILINE)
_PIN_LINE_RE = re.compile(r'^\s*CustomProperties Pin (?P<body>\(.*\))\s*$')
_PROP_LINE_RE = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$')

# Node-class-specific properties whose value contains a human-meaningful title
# (usually MemberName="..." from an FMemberReference-shaped struct).
_TITLE_PROPERTIES = [
    "FunctionReference",
    "VariableReference",
    "EventReference",
    "DelegateReference",
    "MacroGraphReference",
]
_MEMBER_NAME_RE = re.compile(r'MemberName="([^"]*)"')

# Structural nodes whose class name alone is a better title than any property.
_STRUCTURAL_TITLES = {
    "K2Node_IfThenElse": "Branch",
    "K2Node_ExecutionSequence": "Sequence",
    "K2Node_DynamicCast": "Cast",
    "K2Node_Self": "Self",
    "K2Node_InputAction": "Input Action",
    "K2Node_Timeline": "Timeline",
    "K2Node_SpawnActorFromClass": "Spawn Actor",
    "K2Node_FunctionEntry": "Entry",
    "K2Node_FunctionResult": "Return",
}

# Node properties folded into dedicated markdown fields, so the catch-all
# "Properties" list below doesn't repeat them.
_SKIP_PROPERTY_KEYS = {
    "NodePosX", "NodePosY", "NodeComment", "bCommentBubbleVisible",
    "NodeGuid", "NodeWidth", "NodeHeight", "ErrorType", "ErrorMsg",
    "AdvancedPinDisplay", "EnabledState",
}


def _split_top_level(s, sep=","):
    """Split s on sep, but only where paren/bracket depth is 0 and outside quotes."""
    parts = []
    depth = 0
    in_quotes = False
    start = 0
    for i, c in enumerate(s):
        if in_quotes:
            if c == '"' and (i == 0 or s[i - 1] != '\\'):
                in_quotes = False
        else:
            if c == '"':
                in_quotes = True
            elif c in "([":
                depth += 1
            elif c in ")]":
                depth -= 1
            elif c == sep and depth == 0:
                parts.append(s[start:i])
                start = i + 1
    parts.append(s[start:])
    return parts


def _parse_kv(s):
    """Parse 'K1=V1,K2=V2,K3=(nested,vals)' into a dict of raw (unparsed) string values."""
    result = {}
    for part in _split_top_level(s.strip(), ","):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, _, value = part.partition("=")
        result[key.strip()] = value.strip()
    return result


def _unescape_cstring(s):
    return (s.replace("\\r\\n", "\n")
             .replace("\\n", "\n")
             .replace("\\t", "\t")
             .replace('\\"', '"')
             .replace("\\\\", "\\"))


def _strip_quotes(v):
    v = (v or "").strip()
    if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
        v = v[1:-1]
    return _unescape_cstring(v)


def _parse_pin(body):
    """body is the full '(PinId=...,PinName="...",...)' text for one CustomProperties Pin line."""
    inner = body.strip()
    if inner.startswith("(") and inner.endswith(")"):
        inner = inner[1:-1]
    fields = _parse_kv(inner)

    direction_raw = fields.get("Direction", "")
    direction = "Output" if "Output" in direction_raw else "Input"

    pin = {
        "id": _strip_quotes(fields.get("PinId", "")),
        "name": _strip_quotes(fields.get("PinName", "")),
        "direction": direction,
        "category": _strip_quotes(fields.get("PinType.PinCategory", "")),
        "subcategory": _strip_quotes(fields.get("PinType.PinSubCategory", "")),
        "container": _strip_quotes(fields.get("PinType.ContainerType", "")),
        "default": _strip_quotes(fields.get("DefaultValue", "")),
        "default_object": _strip_quotes(fields.get("DefaultObject", "")),
        "linked": [],
    }

    linked_raw = fields.get("LinkedTo", "").strip()
    if linked_raw.startswith("(") and linked_raw.endswith(")"):
        linked_raw = linked_raw[1:-1]
    for entry in _split_top_level(linked_raw, ","):
        entry = entry.strip()
        if not entry:
            continue
        node_name, _, pin_guid = entry.rpartition(" ")
        if node_name:
            pin["linked"].append((node_name.strip(), pin_guid.strip()))

    return pin


def _derive_title(node_class, properties):
    if node_class in _STRUCTURAL_TITLES:
        return _STRUCTURAL_TITLES[node_class]

    for prop_name in _TITLE_PROPERTIES:
        raw = properties.get(prop_name)
        if raw:
            m = _MEMBER_NAME_RE.search(raw)
            if m and m.group(1):
                return m.group(1)

    custom_name = properties.get("CustomFunctionName")
    if custom_name:
        return _strip_quotes(custom_name)

    return node_class.replace("K2Node_", "") or node_class


def parse_graph_text(text):
    """Parse one graph's exported node text into a list of node dicts, in export order."""
    nodes = []
    matches = list(_BEGIN_OBJECT_RE.finditer(text))
    for idx, m in enumerate(matches):
        node_class = m.group("cls").rsplit(".", 1)[-1]
        node_name = m.group("name")

        body_start = m.end()
        body_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        body = text[body_start:body_end]

        properties = {}
        pins = []
        nested_depth = 0
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped:
                continue

            if stripped.startswith("Begin Object"):
                nested_depth += 1
                continue
            if stripped.startswith("End Object"):
                nested_depth = max(0, nested_depth - 1)
                continue
            if nested_depth > 0:
                continue

            pin_match = _PIN_LINE_RE.match(line)
            if pin_match:
                pins.append(_parse_pin(pin_match.group("body")))
                continue

            prop_match = _PROP_LINE_RE.match(line)
            if prop_match:
                properties[prop_match.group(1)] = prop_match.group(2)

        nodes.append({
            "class": node_class,
            "name": node_name,
            "title": _derive_title(node_class, properties),
            "properties": properties,
            "pins": pins,
        })

    return nodes


# ---------------------------------------------------------------------------
# Markdown generation
# ---------------------------------------------------------------------------

def _pin_type_label(pin):
    label = pin["category"] or "?"
    if pin["subcategory"] and pin["subcategory"] != "None":
        label = pin["subcategory"]
    if pin["container"] and pin["container"] not in ("None", ""):
        label = f"{pin['container']} of {label}"
    return label


def _format_wiring(pin, pin_lookup):
    if not pin["linked"]:
        return ""
    targets = []
    for node_name, pin_guid in pin["linked"]:
        target = pin_lookup.get((node_name, pin_guid))
        if target:
            targets.append(f"{target[0]}.`{target[1]}`")
        else:
            targets.append(f"`{node_name}` (external/unresolved)")
    return "; ".join(targets)


def generate_graph_markdown(graph_key, nodes):
    lines = [f"## Graph: {graph_key}", ""]

    if not nodes:
        lines.append("_Empty graph._")
        lines.append("")
        return "\n".join(lines)

    # Pin GUID -> (node display label, pin name), used to resolve LinkedTo wiring.
    pin_lookup = {}
    for node in nodes:
        label = f"**{node['title']}** (`{node['name']}`)"
        for pin in node["pins"]:
            if pin["id"]:
                pin_lookup[(node["name"], pin["id"])] = (label, pin["name"])

    lines.append(f"{len(nodes)} node(s).")
    lines.append("")

    for node in nodes:
        lines.append(f"### {node['title']}")
        lines.append("")
        lines.append(f"- **Class:** `{node['class']}`")
        lines.append(f"- **Export Name:** `{node['name']}`")

        pos_x = node["properties"].get("NodePosX")
        pos_y = node["properties"].get("NodePosY")
        if pos_x is not None and pos_y is not None:
            lines.append(f"- **Position:** ({pos_x}, {pos_y})")

        comment = node["properties"].get("NodeComment")
        if comment and _strip_quotes(comment):
            lines.append(f"- **Comment:** {_strip_quotes(comment)}")

        extra_props = {k: v for k, v in node["properties"].items() if k not in _SKIP_PROPERTY_KEYS}
        if extra_props:
            lines.append("- **Properties:**")
            for k, v in extra_props.items():
                lines.append(f"  - `{k}` = {v}")

        if node["pins"]:
            lines.append("")
            lines.append("| Pin | Dir | Type | Default | Linked To |")
            lines.append("|-----|-----|------|---------|-----------|")
            for pin in node["pins"]:
                wiring = _format_wiring(pin, pin_lookup)
                default = pin["default"] or pin["default_object"] or ""
                lines.append(
                    f"| {pin['name']} | {pin['direction']} | {_pin_type_label(pin)} | "
                    f"{default} | {wiring} |"
                )
        lines.append("")

    return "\n".join(lines)


def generate_blueprint_markdown(blueprint_name, package_path, parent_class_name, graph_texts):
    lines = [f"# {blueprint_name}", "", f"**Path:** `{package_path}`"]
    if parent_class_name:
        lines.append(f"**Parent Class:** `{parent_class_name}`")
    lines.append("")

    if not graph_texts:
        lines.append("_No graphs with nodes found._")
        return "\n".join(lines)

    for graph_key in sorted(graph_texts.keys()):
        nodes = parse_graph_text(graph_texts[graph_key])
        lines.append("---")
        lines.append("")
        lines.append(generate_graph_markdown(graph_key, nodes))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Asset discovery + orchestration
# ---------------------------------------------------------------------------

# The project's own top-level content package, e.g. "/Game/ColossusRising". Everything else
# under "/Game" (marketplace samples like FluidNinjaLive, vendored demo content, etc.) is
# untracked in git per this project's own convention and excluded from the default scan.
_PROJECT_CONTENT_ROOT = "/Game/ColossusRising"


def _project_root():
    return unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir())


def _uproject_plugin_names():
    """Every plugin listed as enabled in <ProjectRoot>/*.uproject. This is how engine-level
    plugins (GameplayAbilities, CommonUI, Mover, ModelContextProtocol, marketplace installs
    like VoxelPluginInstaller, etc.) get surfaced — they have no folder under the project's
    own Plugins/, only a .uproject entry."""
    uproject_matches = glob.glob(os.path.join(_project_root(), "*.uproject"))
    if not uproject_matches:
        return []

    with open(uproject_matches[0], "r", encoding="utf-8") as f:
        data = json.load(f)

    return [
        entry["Name"]
        for entry in data.get("Plugins", [])
        if entry.get("Enabled", True) and entry.get("Name")
    ]


def _plugins_folder_names():
    """Every .uplugin found anywhere under the project's own Plugins/ folder (recursively, so
    this covers top-level plugins as well as Plugins/GameFeatures/* and Plugins/GameModes/*,
    which are ExplicitlyLoaded and never appear in the .uproject's Plugins list)."""
    plugins_dir = os.path.join(_project_root(), "Plugins")

    names = []
    for dirpath, _dirnames, filenames in os.walk(plugins_dir):
        for filename in filenames:
            if filename.endswith(".uplugin"):
                names.append(os.path.splitext(filename)[0])
    return names


def _discover_plugin_scan_roots(exclude_plugins=None):
    """Union of every plugin declared enabled in the .uproject and every plugin physically
    present under this project's own Plugins/ folder — deliberately not vendor-filtered, so
    it includes marketplace plugins (Voxel, PCGExtendedToolkit) as well as every GameFeature
    and GameMode plugin. Pass exclude_plugins to drop specific names if needed."""
    exclude_plugins = set(exclude_plugins or [])
    all_names = set(_uproject_plugin_names()) | set(_plugins_folder_names())
    return [f"/{name}" for name in sorted(all_names) if name not in exclude_plugins]


def _output_bucket(package_name):
    """Return (dir_segments, is_project) for a package like '/Game/Foo' or '/Combat/Foo'."""
    root = package_name.strip("/").split("/", 1)[0]
    if root == "Game":
        return ["Project"], True
    return ["Plugins", root], False


def export_all_blueprint_docs(output_dir=None, scan_roots=None, exclude_plugins=None):
    """
    Find every Blueprint asset under scan_roots and export its graphs to markdown.

    scan_roots: list of content mount points to scan (e.g. ["/Game/ColossusRising", "/Combat"]).
                Defaults to None, which scans this project's own content
                (_PROJECT_CONTENT_ROOT) plus every plugin under this project's Plugins/ folder,
                excluding vendor plugins (see _DEFAULT_EXCLUDED_PLUGINS / exclude_plugins).
    """
    if output_dir is None:
        output_dir = os.path.join(_project_root(), "Documentation", "generated-api", "content")

    if scan_roots is None:
        scan_roots = [_PROJECT_CONTENT_ROOT] + _discover_plugin_scan_roots(exclude_plugins)

    asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()
    editor_asset_subsystem = unreal.get_editor_subsystem(unreal.EditorAssetSubsystem)

    ar_filter = unreal.ARFilter(
        class_paths=[unreal.TopLevelAssetPath("/Script/Engine", "Blueprint")],
        recursive_classes=True,
        package_paths=scan_roots,
        recursive_paths=True,
    )
    assets = asset_registry.get_assets(ar_filter)
    unreal.log(f"[BlueprintGraphDocs] Scanning {scan_roots}")
    unreal.log(f"[BlueprintGraphDocs] Found {len(assets)} Blueprint asset(s).")

    written = 0
    skipped = 0

    for asset_data in assets:
        package_name = str(asset_data.package_name)
        asset_name = str(asset_data.asset_name)

        try:
            bp = editor_asset_subsystem.load_asset(package_name)
        except Exception as e:
            unreal.log_warning(f"[BlueprintGraphDocs] Failed to load {package_name}: {e}")
            skipped += 1
            continue

        if bp is None:
            unreal.log_warning(f"[BlueprintGraphDocs] Could not load {package_name}, skipping.")
            skipped += 1
            continue

        graph_texts = dict(unreal.BlueprintGraphExportLibrary.export_blueprint_graphs_to_text(bp))

        parent_class_name = ""
        try:
            parent_class = bp.get_editor_property("parent_class")
            parent_class_name = parent_class.get_name() if parent_class else ""
        except Exception:
            pass

        markdown = generate_blueprint_markdown(asset_name, package_name, parent_class_name, graph_texts)

        dir_segments, _ = _output_bucket(package_name)
        target_dir = os.path.join(output_dir, *dir_segments)
        os.makedirs(target_dir, exist_ok=True)

        out_path = os.path.join(target_dir, f"{asset_name}.md")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(markdown)

        unreal.log(f"[BlueprintGraphDocs] Wrote {out_path}")
        written += 1

    unreal.log(f"[BlueprintGraphDocs] Done. Written: {written}  Skipped: {skipped}")
    return written, skipped
