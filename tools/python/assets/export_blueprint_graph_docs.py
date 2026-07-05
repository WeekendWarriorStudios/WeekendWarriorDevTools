"""
Export authored Blueprint asset graphs and pin wiring to human-readable markdown.

Blueprint EventGraph/FunctionGraph/MacroGraph node and pin data isn't reachable through
generic Python reflection: UEdGraphPin stopped being a UObject around UE 4.24 (a compile-time
performance change), so its Direction/PinType/LinkedTo fields are invisible to
get_editor_property. This script instead calls
unreal.BlueprintGraphExportLibrary.export_blueprint_graphs_to_text() (a small C++ bridge in
Plugins/ColossusMCPTools) which wraps FEdGraphUtilities::ExportNodesToText — the same engine
facility that backs Blueprint node copy/paste — then parses that text into markdown here.

Run from the Unreal Editor Python console:
    import sys
    sys.path.insert(0, r"A:\\Projects\\ColossusRising\\WeekendWarriorDevTools\\tools\\python\\assets")
    import export_blueprint_graph_docs as ebgd
    ebgd.export_all_blueprint_docs()

Output layout (default):
    Documentation/generated-api/content/Project/<BlueprintName>.md
    Documentation/generated-api/content/Plugins/<PluginRoot>/<BlueprintName>.md

If two Blueprints in the same project/plugin bucket share the same asset name, the exporter
keeps the flat layout and appends the former package subpath to only those colliding filenames.

Asset coverage:
    - Blueprint
    - WidgetBlueprint
    - EditorUtilityWidgetBlueprint
    - AnimBlueprint
    - PCGGraph
    - VoxelHeightGraph
    - VoxelVolumeGraph
"""

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


def _safe_get_editor_property(obj, property_name, default=None):
    try:
        return obj.get_editor_property(property_name)
    except Exception:
        return default


def _generate_pcg_graph_markdown(asset_name, package_path, graph_obj):
    lines = [f"# {asset_name}", "", f"**Path:** `{package_path}`", "**Type:** `PCGGraph`", ""]

    node_paths = []
    try:
        node_paths = unreal.PCGExGraphMCPToolset.list_pcg_graph_nodes(package_path)
    except Exception:
        pass

    node_objects = []
    if not node_paths:
        try:
            node_objects = list(graph_obj.get_nodes())
        except Exception:
            node_objects = []

    if not node_paths and not node_objects:
        lines.append("_No PCG nodes were discovered for this graph._")
        return "\n".join(lines)

    node_count = len(node_paths) if node_paths else len(node_objects)
    lines.append(f"{node_count} node(s).")
    lines.append("")

    if node_paths:
        for node_path in node_paths:
            node_name = node_path.rsplit(".", 1)[-1]
            node_obj = None
            try:
                node_obj = unreal.load_object(None, node_path)
            except Exception:
                node_obj = None

            if not node_obj:
                continue

            lines.extend(_format_pcg_node_markdown(node_name, node_path, node_obj))
    else:
        for node_obj in node_objects:
            node_name = node_obj.get_name() if node_obj else "UnknownNode"
            node_path = node_obj.get_path_name() if node_obj else ""
            lines.extend(_format_pcg_node_markdown(node_name, node_path, node_obj))

    return "\n".join(lines)


def _extract_pcg_pin_labels(pins):
    labels = []
    for pin in pins or []:
        label = ""
        try:
            props = pin.get_editor_property("properties")
            if props:
                label_name = props.get_editor_property("label")
                label = str(label_name) if label_name else ""
        except Exception:
            label = ""

        if not label:
            try:
                label = pin.get_name()
            except Exception:
                label = ""

        labels.append(label or "(unnamed)")
    return labels


def _format_pcg_node_markdown(node_name, node_path, node_obj):
    lines = []

    node_class = node_obj.get_class().get_name() if node_obj else "UnknownNode"
    settings_obj = None
    try:
        settings_obj = node_obj.get_settings() if node_obj else None
    except Exception:
        settings_obj = None

    settings_class = settings_obj.get_class().get_name() if settings_obj else ""
    input_pins = []
    output_pins = []

    if node_path:
        try:
            input_pins = unreal.PCGExGraphMCPToolset.get_pcg_node_input_pin_labels(node_path)
        except Exception:
            input_pins = []
        try:
            output_pins = unreal.PCGExGraphMCPToolset.get_pcg_node_output_pin_labels(node_path)
        except Exception:
            output_pins = []

    if not input_pins:
        try:
            input_pins = _extract_pcg_pin_labels(node_obj.get_input_pins())
        except Exception:
            input_pins = []

    if not output_pins:
        try:
            output_pins = _extract_pcg_pin_labels(node_obj.get_output_pins())
        except Exception:
            output_pins = []

    lines.append(f"## Node: {node_name}")
    lines.append("")
    if node_path:
        lines.append(f"- **Path:** `{node_path}`")
    lines.append(f"- **Class:** `{node_class}`")
    if settings_class:
        lines.append(f"- **Settings Class:** `{settings_class}`")
    lines.append(f"- **Input Pins:** {', '.join(input_pins) if input_pins else '(none)'}")
    lines.append(f"- **Output Pins:** {', '.join(output_pins) if output_pins else '(none)'}")
    lines.append("")

    return lines


def _generate_voxel_graph_markdown(asset_name, package_path, graph_obj):
    class_name = graph_obj.get_class().get_name() if graph_obj else "VoxelGraph"
    lines = [
        f"# {asset_name}",
        "",
        f"**Path:** `{package_path}`",
        f"**Type:** `{class_name}`",
        "",
        "_Voxel graph node internals are owned by editor-private graph classes, so this export captures discoverable asset metadata._",
        "",
    ]

    base_graph = _safe_get_editor_property(graph_obj, "base_graph")
    if base_graph:
        try:
            lines.append(f"- **Base Graph:** `{base_graph.get_path_name()}`")
        except Exception:
            lines.append("- **Base Graph:** (unavailable)")

    graph_name = _safe_get_editor_property(graph_obj, "graph_name")
    if graph_name:
        lines.append(f"- **Graph Name:** `{graph_name}`")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Asset discovery + orchestration
# ---------------------------------------------------------------------------

# Unreal content roots that are not authored content/plugin mounts and should not be scanned.
_EXCLUDED_MOUNT_ROOTS = {
    "/Engine",
    "/Script",
    "/Memory",
    "/Temp",
    "/Config",
    "/Collections",
    "/Developers",
}

# Asset registry class names that represent authored Blueprint assets in practice.
# Plain Blueprint alone misses common subclasses such as UMG widgets and Anim BPs.
_BLUEPRINT_ASSET_CLASS_PATHS = [
    unreal.TopLevelAssetPath("/Script/Engine", "Blueprint"),
    unreal.TopLevelAssetPath("/Script/UMGEditor", "WidgetBlueprint"),
    unreal.TopLevelAssetPath("/Script/Blutility", "EditorUtilityWidgetBlueprint"),
    unreal.TopLevelAssetPath("/Script/AnimGraph", "AnimBlueprint"),
]

# Additional authored graph assets that should be scanned and converted to docs.
_ADDITIONAL_GRAPH_ASSET_CLASS_PATHS = [
    unreal.TopLevelAssetPath("/Script/PCG", "PCGGraph"),
    unreal.TopLevelAssetPath("/Script/Voxel", "VoxelHeightGraph"),
    unreal.TopLevelAssetPath("/Script/Voxel", "VoxelVolumeGraph"),
]


def _project_root():
    return unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir())


def _discover_mounted_scan_roots(asset_registry, exclude_plugins=None):
    """Discover mounted content/plugin roots that Unreal currently has active.

    This follows the editor's actual mounted package paths instead of guessing from the
    .uproject or the on-disk Plugins/ tree. /Game is always included so every project content
    folder is scanned; non-/Game roots correspond to mounted plugin content such as /Water,
    /CommonUI, /Voxel, etc.
    """
    exclude_plugins = {name.lower() for name in (exclude_plugins or [])}
    roots = set()

    for cached_path in asset_registry.get_all_cached_paths():
        package_path = str(cached_path)
        if not package_path.startswith("/"):
            continue

        root_name = package_path.strip("/").split("/", 1)[0]
        if not root_name:
            continue

        mount_root = f"/{root_name}"
        if mount_root in _EXCLUDED_MOUNT_ROOTS:
            continue

        if mount_root != "/Game" and root_name.lower() in exclude_plugins:
            continue

        roots.add(mount_root)

    if "/Game" not in roots:
        roots.add("/Game")

    return sorted(roots)


def _output_bucket(package_name):
    """Return (dir_segments, is_project) for a package like '/Game/Foo' or '/Combat/Foo'."""
    root = package_name.strip("/").split("/", 1)[0]
    if root == "Game":
        return ["Project"], True
    return ["Plugins", root], False


def _flattened_relative_package_parts(package_name):
    return [part for part in package_name.strip("/").split("/") if part][1:-1]


def _output_filename(package_name, asset_name, bucket_name, duplicate_counts):
    duplicate_key = (bucket_name, asset_name)
    if duplicate_counts.get(duplicate_key, 0) <= 1:
        return f"{asset_name}.md"

    relative_parts = _flattened_relative_package_parts(package_name)
    suffix = "__".join(relative_parts) if relative_parts else "Root"
    return f"{asset_name}__{suffix}.md"


def _output_path_parts(package_name, asset_name, duplicate_counts):
    """Flatten exports into project/plugin buckets, disambiguating only duplicate asset names."""
    dir_segments, is_project = _output_bucket(package_name)
    bucket_name = "Project" if is_project else dir_segments[1]
    filename = _output_filename(package_name, asset_name, bucket_name, duplicate_counts)
    return dir_segments, filename


def export_all_blueprint_docs(output_dir=None, scan_roots=None, exclude_plugins=None):
    """
    Find every authored Blueprint asset under scan_roots and export its graphs to markdown.

    scan_roots: list of content mount points to scan (e.g. ["/Game", "/Combat"]).
                Defaults to None, which scans every mounted project-content and active plugin
                content root currently visible to the Unreal asset registry.
    """
    if output_dir is None:
        output_dir = os.path.join(_project_root(), "Documentation", "generated-api", "content")

    asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()

    if scan_roots is None:
        scan_roots = _discover_mounted_scan_roots(asset_registry, exclude_plugins)

    editor_asset_subsystem = unreal.get_editor_subsystem(unreal.EditorAssetSubsystem)

    assets_by_package = {}
    for class_path in _BLUEPRINT_ASSET_CLASS_PATHS:
        ar_filter = unreal.ARFilter(
            class_paths=[class_path],
            recursive_classes=True,
            package_paths=scan_roots,
            recursive_paths=True,
        )
        for asset_data in asset_registry.get_assets(ar_filter):
            assets_by_package[str(asset_data.package_name)] = (asset_data, "Blueprint")

    for class_path in _ADDITIONAL_GRAPH_ASSET_CLASS_PATHS:
        ar_filter = unreal.ARFilter(
            class_paths=[class_path],
            recursive_classes=True,
            package_paths=scan_roots,
            recursive_paths=True,
        )
        for asset_data in asset_registry.get_assets(ar_filter):
            class_name = str(asset_data.asset_class_path.asset_name)
            asset_kind = "Graph"
            if class_name == "PCGGraph":
                asset_kind = "PCGGraph"
            elif class_name in ("VoxelHeightGraph", "VoxelVolumeGraph"):
                asset_kind = class_name
            assets_by_package[str(asset_data.package_name)] = (asset_data, asset_kind)

    assets = [assets_by_package[key] for key in sorted(assets_by_package.keys())]
    unreal.log(f"[BlueprintGraphDocs] Scanning {scan_roots}")
    blueprint_count = sum(1 for _, kind in assets if kind == "Blueprint")
    pcg_count = sum(1 for _, kind in assets if kind == "PCGGraph")
    voxel_count = sum(1 for _, kind in assets if kind in ("VoxelHeightGraph", "VoxelVolumeGraph"))
    unreal.log(
        f"[BlueprintGraphDocs] Found {len(assets)} total asset(s): "
        f"Blueprint={blueprint_count}, PCGGraph={pcg_count}, VoxelGraphs={voxel_count}."
    )

    duplicate_counts = {}
    for asset_data, _asset_kind in assets:
        package_name = str(asset_data.package_name)
        asset_name = str(asset_data.asset_name)
        dir_segments, is_project = _output_bucket(package_name)
        bucket_name = "Project" if is_project else dir_segments[1]
        duplicate_key = (bucket_name, asset_name)
        duplicate_counts[duplicate_key] = duplicate_counts.get(duplicate_key, 0) + 1

    written = 0
    skipped = 0

    for asset_data, asset_kind in assets:
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

        if asset_kind == "Blueprint":
            graph_texts = dict(unreal.BlueprintGraphExportLibrary.export_blueprint_graphs_to_text(bp))

            parent_class_name = ""
            try:
                parent_class = bp.get_editor_property("parent_class")
                parent_class_name = parent_class.get_name() if parent_class else ""
            except Exception:
                pass

            markdown = generate_blueprint_markdown(asset_name, package_name, parent_class_name, graph_texts)
        elif asset_kind == "PCGGraph":
            markdown = _generate_pcg_graph_markdown(asset_name, package_name, bp)
        else:
            markdown = _generate_voxel_graph_markdown(asset_name, package_name, bp)

        dir_segments, filename = _output_path_parts(package_name, asset_name, duplicate_counts)
        target_dir = os.path.join(output_dir, *dir_segments)
        os.makedirs(target_dir, exist_ok=True)

        out_path = os.path.join(target_dir, filename)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(markdown)

        unreal.log(f"[BlueprintGraphDocs] Wrote {out_path}")
        written += 1

    unreal.log(f"[BlueprintGraphDocs] Done. Written: {written}  Skipped: {skipped}")
    return written, skipped
