#!/usr/bin/env python3
"""Scan tools/ for .ps1 and .py scripts and emit a JSON manifest describing each one.

This is the tool discovery engine behind the Dev Tools UI (tools/ui/). It is deliberately a
*static* scanner - it never imports or executes a discovered script, only reads and parses its
source - so scanning is safe to run against tools that mutate the project (asset moves, cleanup,
cook) or that only work inside a running Unreal Editor.

Three script "kinds" come out of this, matching the README's execution-context table:

  powershell     any .ps1 file. Parameters come from its top-level ``param(...)`` block.
  python-cli     a .py file that builds an ``argparse.ArgumentParser`` - a real CLI, runnable
                 with plain ``python file.py ...`` (tools/analysis/uasset_inspect.py,
                 tools/python/editor/ue_remote_exec.py).
  python-editor  a .py file that ``import unreal``s - an editor-console module, not a CLI. It
                 has no argv parsing; it is meant to be imported and have one of its functions
                 called by hand. Detecting *which* function is the "entry point" is the
                 interesting part - see ``_find_entry_functions``.

Usage
-----
    python scan_tools.py                          # scan ./.. (tools/) next to this file, print JSON
    python scan_tools.py --out manifest.json       # write to a file instead of stdout
    python scan_tools.py --tools-root C:\\Proj\\WeekendWarriorDevTools\\tools

As a module (this is what tools/ui/server.py does, so a scan never pays for a subprocess):
    from scan_tools import build_manifest
    manifest = build_manifest(tools_root)
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import time
from pathlib import Path

# Directories under tools/ that are never scanned for tools: the UI's own code, and any
# bytecode caches left behind by running the editor scripts directly.
EXCLUDED_DIR_NAMES = {"ui", "__pycache__", ".git", "lib"}

# A handful of tokens that Title-Case mangles. Extend as new tools show up.
ACRONYMS = {
    "ue5": "UE5", "orm": "ORM", "pdf": "PDF", "html": "HTML", "json": "JSON",
    "cpp": "C++", "udn": "UDN", "uasset": "UAsset", "api": "API", "id": "ID",
    "url": "URL", "cd": "CD",
}


# --------------------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------------------

def _display_name(stem: str) -> str:
    words = re.split(r"[-_]+", stem)
    out = []
    for w in words:
        if not w:
            continue
        lw = w.lower()
        if lw in ACRONYMS:
            out.append(ACRONYMS[lw])
        elif w.isupper():
            out.append(w)
        else:
            out.append(w[:1].upper() + w[1:])
    return " ".join(out) if out else stem


def _rel_parts(path: Path, tools_root: Path) -> tuple[str, str, str]:
    rel = path.relative_to(tools_root)
    parts = rel.parts[:-1]
    category = parts[0] if parts else "misc"
    sub_category = "/".join(parts[1:]) if len(parts) > 1 else ""
    return rel.as_posix(), category, sub_category


def _tool_id(rel_posix: str) -> str:
    return rel_posix.rsplit(".", 1)[0]


# --------------------------------------------------------------------------------------
# PowerShell parsing
# --------------------------------------------------------------------------------------

_PS_TYPE_MAP = {
    "switch": "bool",
    "bool": "bool", "boolean": "bool",
    "int": "int", "int32": "int", "int64": "int", "long": "int", "uint32": "int",
    "double": "float", "float": "float", "single": "float", "decimal": "float",
    "string": "string",
}


def _split_top_level(text: str, sep: str = ",") -> list[str]:
    """Split ``text`` on ``sep`` but only at bracket/quote depth 0."""
    parts: list[str] = []
    depth = 0
    quote = None
    buf = []
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            buf.append(ch)
            if ch == quote:
                # doubled quote is an escaped quote in PowerShell ('' inside '...', "" inside "...")
                if i + 1 < len(text) and text[i + 1] == quote:
                    buf.append(text[i + 1])
                    i += 1
                else:
                    quote = None
        elif ch in "'\"":
            quote = ch
            buf.append(ch)
        elif ch in "([{":
            depth += 1
            buf.append(ch)
        elif ch in ")]}":
            depth -= 1
            buf.append(ch)
        elif ch == sep and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    if buf or parts:
        parts.append("".join(buf))
    return [p for p in (s.strip() for s in parts) if p]


def _extract_balanced_parens(text: str, open_at: int) -> tuple[str, int]:
    """Given index of an opening '(' at ``open_at``, return (inner_text, index_after_close)."""
    assert text[open_at] == "("
    depth = 0
    quote = None
    i = open_at
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == quote and not (i + 1 < len(text) and text[i + 1] == quote):
                quote = None
            elif ch == quote:
                i += 1  # skip escaped quote
        elif ch in "'\"":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[open_at + 1:i], i + 1
        i += 1
    return text[open_at + 1:], len(text)


_PS_DIRECTIVE_RE = re.compile(r"^#(requires|region|endregion)\b", re.IGNORECASE)


def _leading_comment_block(lines: list[str]) -> tuple[str, int]:
    """Return (description_text, index_of_first_non_comment_line).

    Skips #Requires/#region-style directive lines before looking for the actual doc comment -
    otherwise a leading ``#Requires -Version 5.1`` gets mistaken for (and stands in as the whole
    of) the script's description.
    """
    i = 0
    n = len(lines)
    while i < n and (lines[i].strip() == "" or _PS_DIRECTIVE_RE.match(lines[i].strip())):
        i += 1
    if i < n and lines[i].lstrip().startswith("<#"):
        start = i
        buf = []
        first = lines[i].lstrip()
        after_open = first[first.index("<#") + 2:]
        buf.append(after_open)
        i += 1
        while i < n and "#>" not in lines[i]:
            buf.append(lines[i])
            i += 1
        if i < n:
            buf.append(lines[i][: lines[i].index("#>")])
            i += 1
        text = "\n".join(buf)
        return _dedent_comment(text), i
    # run of line comments
    buf = []
    while i < n and (lines[i].strip() == "" or lines[i].lstrip().startswith("#")):
        if lines[i].lstrip().startswith("#"):
            buf.append(lines[i].lstrip()[1:].lstrip(" "))
        elif buf:
            buf.append("")
        i += 1
    return "\n".join(buf).strip(), i


def _dedent_comment(text: str) -> str:
    lines = text.splitlines()
    indents = [len(l) - len(l.lstrip()) for l in lines if l.strip()]
    pad = min(indents) if indents else 0
    return "\n".join(l[pad:] if len(l) >= pad else l.strip() for l in lines).strip()


_PS_HELP_TAG_RE = re.compile(r"^\.(SYNOPSIS|DESCRIPTION|PARAMETER|EXAMPLE|NOTES|INPUTS|OUTPUTS|LINK|COMPONENT|ROLE|FUNCTIONALITY)\b\s*(.*)$", re.IGNORECASE)


def _parse_comment_help(text: str) -> dict | None:
    """Parse PowerShell formal comment-based help (.SYNOPSIS/.DESCRIPTION/.PARAMETER/.EXAMPLE)
    out of a doc comment block, if it uses that convention. Returns None for a plain free-text
    block (find-large-assets.ps1's style), so the caller can fall back to using the raw text."""
    sections: dict[str, list[str]] = {}
    param_help: dict[str, str] = {}
    current_key = None
    current_param = None
    found_tag = False

    for line in text.splitlines():
        m = _PS_HELP_TAG_RE.match(line.strip())
        if m:
            found_tag = True
            tag = m.group(1).upper()
            rest = m.group(2).strip()
            if tag == "PARAMETER":
                current_param = rest.strip()
                current_key = None
                param_help[current_param] = ""
            else:
                current_key = tag
                current_param = None
                sections.setdefault(tag, [])
                if rest:
                    sections[tag].append(rest)
            continue
        if current_param is not None:
            param_help[current_param] = (param_help[current_param] + "\n" + line).strip()
        elif current_key is not None:
            sections.setdefault(current_key, []).append(line)

    if not found_tag:
        return None

    description = "\n".join(sections.get("DESCRIPTION", [])).strip()
    synopsis = "\n".join(sections.get("SYNOPSIS", [])).strip()
    examples = [e.strip() for e in sections.get("EXAMPLE", []) if e.strip()]
    return {
        "description": description or synopsis,
        "examples": examples,
        "paramHelp": {k: v.strip() for k, v in param_help.items() if v.strip()},
    }


def _split_description_usage(text: str) -> tuple[str, list[str]]:
    """Pull fenced-looking usage lines (actual command invocations) out of a free-text block."""
    usage: list[str] = []
    desc_lines: list[str] = []
    in_usage = False
    for line in text.splitlines():
        stripped = line.strip()
        if re.match(r"^usage\s*:?\s*$", stripped, re.IGNORECASE):
            in_usage = True
            continue
        if in_usage:
            if stripped == "" and usage:
                in_usage = False
                continue
            if stripped:
                usage.append(stripped)
                continue
        if re.match(r"^(powershell|python)\b", stripped, re.IGNORECASE) and (
            "-File" in line or ".py" in line or ".ps1" in line
        ):
            usage.append(stripped)
            continue
        desc_lines.append(line)
    desc = "\n".join(desc_lines).strip()
    desc = re.sub(r"\n{3,}", "\n\n", desc)
    return desc, usage


def _ps_literal_kind(raw: str) -> dict:
    raw = raw.strip()
    if raw in ("$true", "$True"):
        return {"value": True, "isLiteral": True}
    if raw in ("$false", "$False"):
        return {"value": False, "isLiteral": True}
    if raw in ("$null", "$Null"):
        return {"value": None, "isLiteral": True}
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "'\"":
        return {"value": raw[1:-1].replace(raw[0] * 2, raw[0]), "isLiteral": True}
    if re.fullmatch(r"-?\d+", raw):
        return {"value": int(raw), "isLiteral": True}
    if re.fullmatch(r"-?\d+\.\d+", raw):
        return {"value": float(raw), "isLiteral": True}
    m = re.fullmatch(r"@\((.*)\)", raw, re.DOTALL)
    if m:
        items = _split_top_level(m.group(1))
        values = []
        ok = True
        for it in items:
            lit = _ps_literal_kind(it)
            if not lit["isLiteral"]:
                ok = False
                break
            values.append(lit["value"])
        if ok:
            return {"value": values, "isLiteral": True}
    return {"value": raw, "isLiteral": False}


def parse_powershell(path: Path, tools_root: Path) -> dict:
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    lines = raw.splitlines()

    desc_block, after_idx = _leading_comment_block(lines)
    help_sections = _parse_comment_help(desc_block)
    if help_sections:
        # Formal comment-based help (.SYNOPSIS/.DESCRIPTION/.PARAMETER/.EXAMPLE) - use its
        # .DESCRIPTION (falling back to .SYNOPSIS) verbatim rather than the whole raw block,
        # which would otherwise dump every section header inline as plain text.
        description = help_sections["description"]
        usage = help_sections["examples"]
        param_help = help_sections["paramHelp"]
    else:
        description, usage = _split_description_usage(desc_block)
        param_help = {}

    # Look for the script's own top-level param(...) block: it must appear before the first
    # real statement (skipping [CmdletBinding()]/attribute lines and blank/comment lines),
    # otherwise what we're seeing is a helper function's param() block, not the script's own.
    idx = after_idx
    while idx < len(lines):
        s = lines[idx].strip()
        if s == "" or s.startswith("#") or re.match(r"^\[CmdletBinding", s, re.IGNORECASE) or \
           re.match(r"^\[OutputType", s, re.IGNORECASE):
            idx += 1
            continue
        break

    params: list[dict] = []
    if idx < len(lines) and re.match(r"^param\s*\(", lines[idx].strip(), re.IGNORECASE):
        rest_text = "\n".join(lines[idx:])
        open_at = rest_text.index("(")
        inner, _ = _extract_balanced_parens(rest_text, open_at)
        for decl in _split_top_level(inner):
            spec = _parse_ps_param_decl(decl)
            # .PARAMETER name lookups are case-insensitive, same as PowerShell itself.
            spec["help"] = next(
                (v for k, v in param_help.items() if k.lower() == spec["name"].lower()), ""
            )
            params.append(spec)

    rel_posix, category, sub_category = _rel_parts(path, tools_root)
    stat = path.stat()
    return {
        "id": _tool_id(rel_posix),
        "name": path.stem,
        "displayName": _display_name(path.stem),
        "relPath": rel_posix,
        "category": category,
        "subCategory": sub_category,
        "kind": "powershell",
        "requiresEditor": False,
        "summary": (description.splitlines()[0].strip() if description else f"Runs {path.name}."),
        "description": description or f"Runs {path.name}. No description comment found in the script.",
        "usage": usage,
        "params": params,
        "sourceMTime": stat.st_mtime,
        "sourceSize": stat.st_size,
    }


def _parse_ps_param_decl(decl: str) -> dict:
    # Pull off leading [Attribute(...)] blocks (Parameter/ValidateSet/Alias/...); the LAST
    # bracket group before the $Name is the actual type.
    bracket_groups = []
    i = 0
    while i < len(decl) and decl[i].isspace():
        i += 1
    while i < len(decl) and decl[i] == "[":
        inner, after = _extract_bracket(decl, i)
        bracket_groups.append(inner)
        i = after
        while i < len(decl) and decl[i].isspace():
            i += 1

    remainder = decl[i:]
    m = re.match(r"\$(?P<name>\w+)\s*(=\s*(?P<default>.*))?$", remainder.strip(), re.DOTALL)
    name = m.group("name") if m else remainder.strip().lstrip("$") or "param"
    default_raw = m.group("default").strip() if m and m.group("default") else None

    required = False
    choices = None
    type_token = None
    for grp in bracket_groups:
        g = grp.strip()
        gl = g.lower()
        if gl.startswith("parameter"):
            if re.search(r"mandatory\s*=\s*\$true", g, re.IGNORECASE):
                required = True
            continue
        if gl.startswith("validateset"):
            inner_m = re.match(r"validateset\((.*)\)", g, re.IGNORECASE | re.DOTALL)
            if inner_m:
                choices = []
                for item in _split_top_level(inner_m.group(1)):
                    lit = _ps_literal_kind(item)
                    if lit["isLiteral"]:
                        choices.append(lit["value"])
            continue
        if gl.startswith("alias") or gl.startswith("validatenotnull") or gl.startswith("validaterange"):
            continue
        # a plain type token, e.g. string, int, switch, string[]
        type_token = g

    ps_type = (type_token or "string").strip()
    is_array = ps_type.endswith("[]")
    base_type = ps_type[:-2] if is_array else ps_type
    ui_type = _PS_TYPE_MAP.get(base_type.lower(), "string")
    if is_array:
        ui_type = "string[]"

    default_info = {"value": None, "isLiteral": True}
    if default_raw is not None:
        default_info = _ps_literal_kind(default_raw)
    elif ui_type == "bool":
        default_info = {"value": False, "isLiteral": True}

    return {
        "name": name,
        "label": name,
        "type": ui_type,
        "required": required,
        "choices": choices,
        "default": default_info["value"],
        "defaultIsLiteral": default_info["isLiteral"],
        "defaultRaw": default_raw,
        "help": "",
    }


def _extract_bracket(text: str, open_at: int) -> tuple[str, int]:
    assert text[open_at] == "["
    depth = 0
    quote = None
    i = open_at
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return text[open_at + 1:i], i + 1
        i += 1
    return text[open_at + 1:], len(text)


# --------------------------------------------------------------------------------------
# Python parsing
# --------------------------------------------------------------------------------------

def _py_type_from_annotation(ann: str | None, default_val=None, has_default: bool = False) -> tuple[str, list | None]:
    if ann:
        a = ann.lower().strip()
        # Container types first: "Tuple[float, float, float]" contains the substring "float"
        # too, so checking scalar types before container types would misclassify it.
        if re.match(r"^(tuple|list|dict|sequence|set|frozenset)\b", a):
            return "json", None
        if "bool" in a:
            return "bool", None
        if "float" in a:
            return "float", None
        if re.search(r"\bint\b", a):
            return "int", None
        if "str" in a:
            return "string", None
    if has_default:
        if isinstance(default_val, bool):
            return "bool", None
        if isinstance(default_val, int):
            return "int", None
        if isinstance(default_val, float):
            return "float", None
        if isinstance(default_val, (list, tuple, dict)):
            return "json", None
    return "string", None


def _build_module_constants(tree: ast.Module) -> dict[str, ast.AST]:
    """Map NAME -> its assigned expression, for simple module-level ``NAME = <expr>`` constants.

    These scripts often define connection/config constants once near the top (``DEFAULT_HOST =
    "127.0.0.1"``) and then reference them in argparse defaults or function signatures
    (``default=DEFAULT_HOST``). ``ast.literal_eval`` can't see through a bare name reference, so
    defaults like that would otherwise show up as unusable raw source text instead of the real
    value. Only the first assignment to a name is kept, and only simple ``Name = <expr>`` forms -
    good enough for config constants, and deliberately not clever enough to misread real logic.
    """
    consts: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name not in consts:
                consts[name] = node.value
    return consts


class _ConstInliner(ast.NodeTransformer):
    def __init__(self, consts: dict[str, ast.AST], max_depth: int = 4):
        self.consts = consts
        self.max_depth = max_depth

    def visit_Name(self, node: ast.Name):
        return self._inline(node.id, 0) or node

    def _inline(self, name: str, depth: int):
        if depth >= self.max_depth or name not in self.consts:
            return None
        sub = ast.copy_location(_ConstInliner(self.consts, self.max_depth - depth - 1).visit(
            ast.parse(ast.unparse(self.consts[name]), mode="eval").body
        ), self.consts[name])
        return sub


def _fold_subscript(node: ast.AST):
    """Evaluate ``<literal container>[<literal index>]`` - the one non-literal-eval shape common
    enough here (``DEFAULT_ENDPOINT[1]``) to be worth the extra few lines, without resorting to
    ``eval()`` on untrusted source."""
    if not isinstance(node, ast.Subscript):
        raise ValueError("not a subscript")
    container = ast.literal_eval(node.value)
    index_node = node.slice
    index = ast.literal_eval(index_node)
    return container[index]


def _literal_or_raw(node: ast.AST, const_map: dict[str, ast.AST] | None = None) -> tuple[object, bool, str]:
    try:
        return ast.literal_eval(node), True, ast.unparse(node)
    except Exception:
        pass
    if const_map:
        try:
            resolved = _ConstInliner(const_map).visit(ast.parse(ast.unparse(node), mode="eval").body)
            try:
                return ast.literal_eval(resolved), True, ast.unparse(node)
            except Exception:
                return _fold_subscript(resolved), True, ast.unparse(node)
        except Exception:
            pass
    try:
        return None, False, ast.unparse(node)
    except Exception:
        return None, False, "<?>"


def _func_params(fn: ast.FunctionDef, examples: dict | None = None, const_map: dict | None = None) -> list[dict]:
    examples = examples or {}
    args = fn.args.args
    defaults = list(fn.args.defaults)
    n_no_default = len(args) - len(defaults)
    out = []
    for i, a in enumerate(args):
        if a.arg in ("self", "cls"):
            continue
        ann = ast.unparse(a.annotation) if a.annotation else None
        has_default = i >= n_no_default
        default_val, is_literal, default_raw = (None, True, None)
        if has_default:
            default_val, is_literal, default_raw = _literal_or_raw(defaults[i - n_no_default], const_map)
        example_source = None
        if not has_default and a.arg in examples:
            default_val, is_literal, default_raw = examples[a.arg]
            example_source = "example"
            has_default = True
        ui_type, choices = _py_type_from_annotation(ann, default_val, has_default and is_literal)
        out.append({
            "name": a.arg,
            "label": a.arg,
            "type": ui_type,
            "annotation": ann,
            "required": not has_default,
            "choices": choices,
            "default": default_val if is_literal else None,
            "defaultIsLiteral": is_literal,
            "defaultRaw": default_raw,
            "defaultSource": example_source or ("signature" if has_default else None),
            "help": "",
        })
    return out


def _find_main_call_example(tree: ast.Module, func_names: set[str], const_map: dict | None = None) -> tuple[str | None, dict]:
    """Look for ``if __name__ == "__main__": <call>`` and return (function_name, {arg: (val, is_lit, raw)})."""
    for node in tree.body:
        if isinstance(node, ast.If):
            try:
                test_src = ast.unparse(node.test)
            except Exception:
                continue
            if "__name__" in test_src and "__main__" in test_src:
                for stmt in node.body:
                    if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)):
                        continue
                    call = stmt.value
                    if isinstance(call.func, ast.Name) and call.func.id in func_names:
                        fn_name = call.func.id
                        examples = {}
                        # positional examples get matched up by caller against the fn signature later
                        examples["__positional__"] = [_literal_or_raw(a, const_map) for a in call.args]
                        for kw in call.keywords:
                            if kw.arg:
                                examples[kw.arg] = _literal_or_raw(kw.value, const_map)
                        return fn_name, examples
    return None, {}


def _docstring_mentioned_functions(doc: str, func_names: list[str]) -> list[str]:
    mentioned = re.findall(r"[.\s]([A-Za-z_][A-Za-z0-9_]*)\s*\(", doc or "")
    seen = []
    name_set = set(func_names)
    for m in mentioned:
        if m in name_set and m not in seen:
            seen.append(m)
    return seen


def _find_entry_functions(tree: ast.Module, doc: str, const_map: dict | None = None) -> tuple[list[dict], list[str]]:
    """Returns (entryFunctions, note_list). First entry in the list is the suggested default."""
    top_funcs = {
        n.name: n for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.name.startswith("_")
    }
    if not top_funcs:
        return [], []

    notes: list[str] = []
    order: list[str] = []
    main_name, main_examples = _find_main_call_example(tree, set(top_funcs), const_map)

    if "main" in top_funcs and len(top_funcs["main"].args.args) == 0:
        order = ["main"]
        notes.append(
            "This script exposes a zero-argument main() that runs a built-in preview/apply "
            "flow. Check the script's module-level constants (shown below) before running - "
            "flipping something like APPLY from False to True happens by editing the file, "
            "not from this UI."
        )
    elif main_name:
        order = [main_name]
    else:
        mentioned = _docstring_mentioned_functions(doc, list(top_funcs))
        if mentioned:
            order = mentioned
        else:
            # last resort: fewest required params first, then most total params
            def score(name):
                fn = top_funcs[name]
                n_req = len(fn.args.args) - len(fn.args.defaults)
                return (n_req, -len(fn.args.args))
            order = sorted(top_funcs, key=score)
            notes.append(
                "Could not tell which function is the intended entry point from the "
                "docstring or a __main__ block - guessed from its signature. Pick the "
                "right one from the dropdown if this looks wrong."
            )

    # append any remaining public functions as extra selectable options, in definition order
    for name in top_funcs:
        if name not in order:
            order.append(name)

    entry_functions = []
    for idx, name in enumerate(order):
        fn = top_funcs[name]
        per_fn_examples = {}
        # only apply the captured __main__-call examples to the function they actually belong to
        if name == main_name:
            positional = main_examples.get("__positional__", [])
            arg_names = [a.arg for a in fn.args.args if a.arg not in ("self", "cls")]
            for pos_idx, val in enumerate(positional):
                if pos_idx < len(arg_names):
                    per_fn_examples[arg_names[pos_idx]] = val
            for k, v in main_examples.items():
                if k != "__positional__":
                    per_fn_examples[k] = v
        entry_functions.append({
            "name": name,
            "isPrimary": idx == 0,
            "docSummary": (ast.get_docstring(fn) or "").splitlines()[0].strip() if ast.get_docstring(fn) else "",
            "params": _func_params(fn, per_fn_examples, const_map),
        })
    return entry_functions, notes


def _script_constants(tree: ast.Module) -> list[dict]:
    """Module-level ALL_CAPS literal constants - the "edit the file to change this" knobs.

    Deliberately excludes leading-underscore names (private implementation detail by Python
    convention, e.g. ``_TITLE_PROPERTIES``) and anything that isn't a plain literal (e.g.
    ``EAL = unreal.EditorAssetLibrary`` module aliases) - those aren't configuration a user would
    ever want to flip, they're just code, and listing them would bury the constants that matter.
    """
    out = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name.isupper() and not name.startswith("_"):
                val, is_literal, raw = _literal_or_raw(node.value)
                if not is_literal:
                    continue
                text = repr(val)
                if len(text) > 300:
                    text = text[:300] + "…"
                out.append({"name": name, "value": text})
    return out


def _argparse_entries(tree: ast.Module, source: str, const_map: dict | None = None) -> dict:
    """Best-effort static extraction of an argparse CLI's positionals/flags/groups."""
    parser_vars: set[str] = set()
    group_vars: dict[str, dict] = {}  # var name -> {"mutex": bool, "id": str}
    group_counter = 0

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            call = node.value
            fname = None
            if isinstance(call.func, ast.Attribute):
                fname = call.func.attr
            elif isinstance(call.func, ast.Name):
                fname = call.func.id
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if fname == "ArgumentParser":
                parser_vars.update(targets)
            elif fname in ("add_mutually_exclusive_group", "add_argument_group"):
                base = call.func.value.id if isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name) else None
                if base in parser_vars or base in group_vars:
                    group_counter += 1
                    gid = f"group{group_counter}"
                    for t in targets:
                        group_vars[t] = {"mutex": fname == "add_mutually_exclusive_group", "id": gid}

    all_holders = parser_vars | set(group_vars)
    params: list[dict] = []
    positionals: list[dict] = []
    groups: dict[str, dict] = {}

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument"):
            continue
        if not (isinstance(node.func.value, ast.Name) and node.func.value.id in all_holders):
            continue
        holder = node.func.value.id
        flag_strs = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        if not flag_strs:
            continue

        kwargs = {}
        kwarg_literal = {}
        for kw in node.keywords:
            if kw.arg:
                val, is_lit, raw = _literal_or_raw(kw.value, const_map)
                kwargs[kw.arg] = val if is_lit else raw
                kwarg_literal[kw.arg] = is_lit

        is_positional = not flag_strs[0].startswith("-")
        long_flags = [f for f in flag_strs if f.startswith("--")]
        display_flag = long_flags[0] if long_flags else flag_strs[0]
        dest = kwargs.get("dest")
        if not dest:
            dest = flag_strs[0] if is_positional else display_flag.lstrip("-").replace("-", "_")

        action = kwargs.get("action", "store")
        choices = kwargs.get("choices") if isinstance(kwargs.get("choices"), list) else None
        py_type = kwargs.get("type")
        nargs = kwargs.get("nargs")

        if action in ("store_true", "store_false"):
            ui_type = "bool"
        elif choices:
            ui_type = "choice"
        elif nargs in ("+", "*") or is_positional and nargs:
            ui_type = "string[]"
        elif py_type == "int":
            ui_type = "int"
        elif py_type == "float":
            ui_type = "float"
        else:
            ui_type = "string"

        is_bool_action = action in ("store_true", "store_false")
        default_literal = True if is_bool_action else kwarg_literal.get("default", True)
        default_value = (action == "store_false") if is_bool_action else kwargs.get("default")
        entry = {
            "name": dest,
            "label": flag_strs[0] if is_positional else display_flag,
            "flags": flag_strs,
            "type": ui_type,
            "required": bool(kwargs.get("required")) or (is_positional and nargs not in ("*", "?")),
            "choices": choices,
            "default": default_value if default_literal else None,
            "defaultIsLiteral": default_literal,
            "defaultRaw": None if default_literal else kwargs.get("default"),
            "help": kwargs.get("help") if isinstance(kwargs.get("help"), str) else "",
            "positional": is_positional,
            "nargs": nargs,
            "group": group_vars.get(holder, {}).get("id"),
        }

        if holder in group_vars:
            gid = group_vars[holder]["id"]
            groups.setdefault(gid, {"id": gid, "mutex": group_vars[holder]["mutex"], "members": []})
            groups[gid]["members"].append(dest)

        if is_positional:
            positionals.append(entry)
        else:
            params.append(entry)

    return {"params": params, "positionals": positionals, "groups": list(groups.values())}


def parse_python(path: Path, tools_root: Path) -> dict:
    source = path.read_text(encoding="utf-8-sig", errors="replace")
    tree = ast.parse(source, filename=str(path))
    doc = ast.get_docstring(tree) or ""
    description, usage = _split_description_usage(doc)

    has_argparse = bool(re.search(r"\bArgumentParser\s*\(", source))
    imports_unreal = any(
        isinstance(n, ast.Import) and any(alias.name == "unreal" for alias in n.names)
        for n in ast.walk(tree)
    )
    const_map = _build_module_constants(tree)

    rel_posix, category, sub_category = _rel_parts(path, tools_root)
    stat = path.stat()
    base = {
        "id": _tool_id(rel_posix),
        "name": path.stem,
        "displayName": _display_name(path.stem),
        "relPath": rel_posix,
        "category": category,
        "subCategory": sub_category,
        "summary": (description.splitlines()[0].strip() if description else f"Runs {path.name}."),
        "description": description or f"Runs {path.name}. No module docstring found in the script.",
        "usage": usage,
        "sourceMTime": stat.st_mtime,
        "sourceSize": stat.st_size,
    }

    if has_argparse:
        parsed = _argparse_entries(tree, source, const_map)
        base.update({
            "kind": "python-cli",
            "requiresEditor": False,
            "params": parsed["params"],
            "positionals": parsed["positionals"],
            "groups": parsed["groups"],
        })
        return base

    if imports_unreal:
        entry_functions, notes = _find_entry_functions(tree, doc, const_map)
        base.update({
            "kind": "python-editor",
            "requiresEditor": True,
            "entryFunctions": entry_functions,
            "scriptConstants": _script_constants(tree),
            "notes": notes,
            "params": entry_functions[0]["params"] if entry_functions else [],
        })
        return base

    base.update({"kind": "python-cli", "requiresEditor": False, "params": [], "positionals": [], "groups": []})
    return base


# --------------------------------------------------------------------------------------
# Top-level scan
# --------------------------------------------------------------------------------------

def discover_tool_files(tools_root: Path) -> list[Path]:
    found = []
    for path in tools_root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in (".ps1", ".py"):
            continue
        rel_parts = path.relative_to(tools_root).parts
        if any(part in EXCLUDED_DIR_NAMES for part in rel_parts[:-1]):
            continue
        if "__pycache__" in rel_parts:
            continue
        found.append(path)
    return sorted(found)


def build_manifest(tools_root: str | Path) -> dict:
    tools_root = Path(tools_root).resolve()
    tools: list[dict] = []
    errors: list[dict] = []

    for path in discover_tool_files(tools_root):
        try:
            if path.suffix.lower() == ".ps1":
                tools.append(parse_powershell(path, tools_root))
            else:
                tools.append(parse_python(path, tools_root))
        except Exception as exc:  # keep scanning even if one file is malformed
            errors.append({
                "relPath": path.relative_to(tools_root).as_posix(),
                "error": f"{type(exc).__name__}: {exc}",
            })

    tools.sort(key=lambda t: (t["category"], t["subCategory"], t["name"]))
    return {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "toolsRoot": str(tools_root),
        "toolCount": len(tools),
        "tools": tools,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tools-root", default=str(Path(__file__).resolve().parent.parent),
                         help="tools/ directory to scan (default: parent of this script's ui/ folder)")
    parser.add_argument("--out", default=None, help="write JSON here instead of stdout")
    parser.add_argument("--pretty", action="store_true", help="pretty-print the JSON")
    args = parser.parse_args(argv)

    manifest = build_manifest(args.tools_root)
    text = json.dumps(manifest, indent=2 if args.pretty else None)

    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"Scanned {manifest['toolCount']} tool(s), {len(manifest['errors'])} error(s). "
              f"Wrote {args.out}")
    else:
        print(text)
    return 0 if not manifest["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
