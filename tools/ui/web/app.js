"use strict";

/* Weekend Warrior Dev Tools UI - talks to server.py's JSON API. No build step, no framework. */

const state = {
  manifest: null,
  selectedId: null,
  selectedEntryFunction: null,
  activeCategories: new Set(), // empty = all
  searchText: "",
  currentRun: null, // { id, source }
};

const el = (id) => document.getElementById(id);

const KIND_META = {
  "powershell": { icon: "⚡", label: "PowerShell" },
  "python-cli": { icon: "🐍", label: "Python CLI" },
  "python-editor": { icon: "🎮", label: "Editor Python" },
};

// -----------------------------------------------------------------------------------
// Data loading
// -----------------------------------------------------------------------------------

async function loadTools(forceRescan) {
  setScanStatus(forceRescan ? "Scanning…" : "Loading…");
  try {
    const res = await fetch(forceRescan ? "/api/scan" : "/api/tools", {
      method: forceRescan ? "POST" : "GET",
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const manifest = await res.json();
    state.manifest = manifest;
    renderCategoryBar();
    renderGrid();
    // Don't rebuild the detail pane out from under an in-flight run (Rescan can be clicked
    // while a tool is still streaming output) - only refresh it when nothing is running.
    if (state.selectedId && !state.currentRun) {
      const still = findTool(state.selectedId);
      if (still) renderDetail(still); else clearDetail();
    }
    const when = new Date(manifest.generatedAt || Date.now());
    setScanStatus(
      `${manifest.toolCount} tool${manifest.toolCount === 1 ? "" : "s"}` +
      (manifest.errors && manifest.errors.length ? ` · ${manifest.errors.length} scan error(s)` : "") +
      ` · scanned ${when.toLocaleTimeString()}`
    );
    el("toolCount").textContent = `${manifest.toolCount} tools`;
  } catch (err) {
    setScanStatus(`Scan failed: ${err.message}`);
  }
}

function setScanStatus(text) {
  el("scanStatus").textContent = text;
}

function findTool(id) {
  return (state.manifest?.tools || []).find((t) => t.id === id) || null;
}

// -----------------------------------------------------------------------------------
// Category bar
// -----------------------------------------------------------------------------------

function renderCategoryBar() {
  const bar = el("categoryBar");
  bar.innerHTML = "";
  const counts = new Map();
  for (const t of state.manifest.tools) {
    counts.set(t.category, (counts.get(t.category) || 0) + 1);
  }
  const categories = [...counts.keys()].sort();

  const allChip = makeChip("All", state.activeCategories.size === 0, state.manifest.tools.length, () => {
    state.activeCategories.clear();
    renderCategoryBar();
    renderGrid();
  });
  bar.appendChild(allChip);

  for (const cat of categories) {
    const chip = makeChip(cat, state.activeCategories.has(cat), counts.get(cat), () => {
      if (state.activeCategories.has(cat)) state.activeCategories.delete(cat);
      else state.activeCategories.add(cat);
      renderCategoryBar();
      renderGrid();
    });
    bar.appendChild(chip);
  }
}

function makeChip(label, active, count, onClick) {
  const btn = document.createElement("button");
  btn.className = "chip" + (active ? " active" : "");
  btn.innerHTML = `${escapeHtml(label)}<span class="n">${count}</span>`;
  btn.addEventListener("click", onClick);
  return btn;
}

// -----------------------------------------------------------------------------------
// Grid
// -----------------------------------------------------------------------------------

function filteredTools() {
  const q = state.searchText.trim().toLowerCase();
  return state.manifest.tools.filter((t) => {
    if (state.activeCategories.size && !state.activeCategories.has(t.category)) return false;
    if (!q) return true;
    const hay = `${t.displayName} ${t.name} ${t.summary} ${t.category} ${t.subCategory}`.toLowerCase();
    return hay.includes(q);
  });
}

function renderGrid() {
  const grid = el("grid");
  grid.innerHTML = "";
  const tools = filteredTools();
  el("emptyState").hidden = tools.length !== 0;

  for (const tool of tools) {
    grid.appendChild(buildTile(tool));
  }
}

function buildTile(tool) {
  const kindMeta = KIND_META[tool.kind] || { icon: "?", label: tool.kind };
  const tile = document.createElement("button");
  tile.type = "button";
  tile.className = "tile" + (tool.id === state.selectedId ? " selected" : "");
  tile.setAttribute("data-id", tool.id);

  const tags = [tool.category];
  if (tool.subCategory) tags.push(tool.subCategory);

  tile.innerHTML = `
    <div class="tile-top">
      <div class="tile-icon kind-${tool.kind}">${kindMeta.icon}</div>
      <div class="tile-badge">${escapeHtml(kindMeta.label)}</div>
    </div>
    <div class="tile-name">${escapeHtml(tool.displayName)}</div>
    <div class="tile-summary">${escapeHtml(tool.summary)}</div>
    <div class="tile-foot">${tags.map((t) => `<span class="tile-tag">${escapeHtml(t)}</span>`).join("")}</div>
  `;
  tile.addEventListener("click", () => selectTool(tool.id));
  return tile;
}

function selectTool(id) {
  if (id === state.selectedId) return;
  detachCurrentRun(); // the detail pane's console/status elements are shared singletons - a
                       // still-streaming run from the previous tool must stop touching them
                       // before we switch (the tool process itself keeps running server-side;
                       // this only stops the UI from listening to it)
  state.selectedId = id;
  state.selectedEntryFunction = null;
  document.querySelectorAll(".tile").forEach((t) => {
    t.classList.toggle("selected", t.getAttribute("data-id") === id);
  });
  const tool = findTool(id);
  if (tool) renderDetail(tool);
}

// -----------------------------------------------------------------------------------
// Detail pane
// -----------------------------------------------------------------------------------

function clearDetail() {
  state.selectedId = null;
  el("detailEmpty").hidden = false;
  el("detailContent").hidden = true;
}

function currentEntryFunction(tool) {
  if (tool.kind !== "python-editor") return null;
  const fns = tool.entryFunctions || [];
  if (!fns.length) return null;
  if (state.selectedEntryFunction) {
    const match = fns.find((f) => f.name === state.selectedEntryFunction);
    if (match) return match;
  }
  return fns.find((f) => f.isPrimary) || fns[0];
}

function renderDetail(tool) {
  el("detailEmpty").hidden = true;
  el("detailContent").hidden = false;

  const kindMeta = KIND_META[tool.kind] || { icon: "?", label: tool.kind };
  el("detailKind").textContent = `${kindMeta.icon} ${kindMeta.label}`;
  el("detailTitle").textContent = tool.displayName;
  el("detailPath").textContent = tool.relPath;
  el("detailSummary").textContent = tool.summary;

  el("detailRequiresEditor").hidden = !tool.requiresEditor;

  const notesBox = el("detailNotes");
  notesBox.innerHTML = "";
  for (const note of tool.notes || []) {
    const div = document.createElement("div");
    div.className = "callout callout-info";
    div.textContent = note;
    notesBox.appendChild(div);
  }

  el("detailDescription").textContent = tool.description || "";
  const usageBox = el("detailUsage");
  usageBox.innerHTML = "";
  if (tool.usage && tool.usage.length) {
    const pre = document.createElement("pre");
    pre.textContent = tool.usage.join("\n");
    usageBox.appendChild(pre);
  }
  el("descriptionBlock").open = false;

  renderEntryFunctionSelector(tool);
  renderParamForm(tool);
  renderConstants(tool);

  resetRunUi();
}

function renderEntryFunctionSelector(tool) {
  const row = el("entryFunctionRow");
  const select = el("entryFunctionSelect");
  if (tool.kind !== "python-editor" || !(tool.entryFunctions || []).length) {
    row.hidden = true;
    return;
  }
  const fns = tool.entryFunctions;
  if (fns.length === 1) {
    row.hidden = true;
    state.selectedEntryFunction = fns[0].name;
    return;
  }
  row.hidden = false;
  select.innerHTML = fns
    .map((f) => `<option value="${escapeHtml(f.name)}">${escapeHtml(f.name)}${f.isPrimary ? "  (suggested)" : ""}</option>`)
    .join("");
  const current = currentEntryFunction(tool);
  select.value = current.name;
  state.selectedEntryFunction = current.name;
  select.onchange = () => {
    state.selectedEntryFunction = select.value;
    renderParamForm(tool);
  };
}

function paramsForTool(tool) {
  if (tool.kind === "python-editor") {
    const fn = currentEntryFunction(tool);
    return fn ? fn.params : [];
  }
  return tool.params || [];
}

function renderParamForm(tool) {
  const form = el("paramForm");
  form.innerHTML = "";

  const groups = tool.groups || [];
  const groupedNames = new Set();
  for (const g of groups) for (const m of g.members) groupedNames.add(m);

  // Positionals (python-cli) shown first, since they're usually the "what to act on" input.
  for (const spec of tool.positionals || []) {
    form.appendChild(buildField(spec));
  }

  for (const g of groups) {
    const members = (tool.params || []).filter((p) => g.members.includes(p.name));
    form.appendChild(buildMutexGroup(g, members));
  }

  for (const spec of paramsForTool(tool)) {
    if (groupedNames.has(spec.name)) continue;
    form.appendChild(buildField(spec));
  }
}

function buildMutexGroup(group, members) {
  // Members aren't necessarily plain boolean flags - e.g. ue_remote_exec.py's group mixes
  // --ping (a flag) with --file/--stmt/--eval (each taking a value), so a value-typed member
  // gets its own inline input, enabled only while its radio is selected.
  const wrap = document.createElement("div");
  wrap.className = "pfield";
  wrap.setAttribute("data-mutex-group", group.id);
  const label = document.createElement("div");
  label.className = "pfield-label-row";
  label.innerHTML = `<span class="pfield-label">Choose one</span><span class="pfield-type">mutually exclusive</span>`;
  wrap.appendChild(label);

  const radios = document.createElement("div");
  radios.className = "pfield-radio-group";

  const allValueInputs = [];
  members.forEach((spec) => {
    const radioId = `mutex-${group.id}-${spec.name}`;
    const row = document.createElement("div");
    row.className = "pfield-radio";

    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = `mutex-${group.id}`;
    radio.value = spec.name;
    radio.id = radioId;

    const radioLabel = document.createElement("label");
    radioLabel.setAttribute("for", radioId);
    radioLabel.textContent = spec.label || spec.name;

    row.appendChild(radio);
    row.appendChild(radioLabel);

    if (spec.type !== "bool") {
      const valueInput = document.createElement("input");
      valueInput.type = "text";
      valueInput.placeholder = spec.help || spec.name;
      valueInput.disabled = true;
      valueInput.setAttribute("data-mutex-value", spec.name);
      row.appendChild(valueInput);
      allValueInputs.push(valueInput);
      radio.addEventListener("change", () => {
        allValueInputs.forEach((inp) => { inp.disabled = true; });
        valueInput.disabled = false;
        valueInput.focus();
      });
    } else {
      radio.addEventListener("change", () => {
        allValueInputs.forEach((inp) => { inp.disabled = true; });
      });
    }
    radios.appendChild(row);
  });
  wrap.appendChild(radios);

  const helpTexts = members.map((m) => m.help).filter(Boolean);
  if (helpTexts.length) {
    const help = document.createElement("div");
    help.className = "pfield-help";
    help.textContent = helpTexts.join(" · ");
    wrap.appendChild(help);
  }
  return wrap;
}

function buildField(spec) {
  const wrap = document.createElement("div");
  wrap.className = "pfield";
  wrap.setAttribute("data-field", spec.name);
  wrap.setAttribute("data-type", spec.type);

  const labelRow = document.createElement("div");
  labelRow.className = "pfield-label-row";
  labelRow.innerHTML = `
    <span class="pfield-label">${escapeHtml(spec.label || spec.name)}${spec.required ? '<span class="pfield-required">*</span>' : ""}</span>
    <span class="pfield-type">${escapeHtml(spec.type)}</span>
  `;
  wrap.appendChild(labelRow);

  let input;
  if (spec.type === "bool") {
    const row = document.createElement("label");
    row.className = "pfield-checkbox";
    input = document.createElement("input");
    input.type = "checkbox";
    input.checked = !!spec.default;
    row.appendChild(input);
    row.appendChild(document.createTextNode(spec.default ? "Enabled by default" : "Disabled by default"));
    wrap.appendChild(row);
  } else if (spec.type === "choice") {
    input = document.createElement("select");
    (spec.choices || []).forEach((c) => {
      const opt = document.createElement("option");
      opt.value = c;
      opt.textContent = c;
      if (spec.default === c) opt.selected = true;
      input.appendChild(opt);
    });
    wrap.appendChild(input);
  } else if (spec.type === "string[]" || spec.type === "json") {
    input = document.createElement("textarea");
    if (spec.type === "string[]") {
      input.placeholder = "one value per line";
      if (Array.isArray(spec.default)) input.value = spec.default.join("\n");
    } else {
      input.placeholder = spec.defaultRaw ? `e.g. ${spec.defaultRaw}` : "JSON value";
      if (spec.defaultIsLiteral && spec.default !== null && spec.default !== undefined) {
        input.value = JSON.stringify(spec.default);
      }
    }
    wrap.appendChild(input);
  } else if (spec.type === "int" || spec.type === "float") {
    input = document.createElement("input");
    input.type = "number";
    if (spec.type === "float") input.step = "any";
    if (spec.defaultIsLiteral && spec.default !== null && spec.default !== undefined) {
      input.value = spec.default;
      input.placeholder = String(spec.default);
    }
    wrap.appendChild(input);
  } else {
    input = document.createElement("input");
    input.type = "text";
    if (spec.defaultIsLiteral && spec.default !== null && spec.default !== undefined && spec.default !== "") {
      input.value = spec.default;
    } else if (spec.defaultRaw) {
      input.placeholder = `default: ${spec.defaultRaw}`;
    }
    wrap.appendChild(input);
  }
  input.setAttribute("data-input", "1");

  if (spec.help) {
    const help = document.createElement("div");
    help.className = "pfield-help";
    help.textContent = spec.help;
    wrap.appendChild(help);
  }
  if (spec.defaultSource === "example") {
    const ex = document.createElement("div");
    ex.className = "pfield-example";
    ex.textContent = "pre-filled from the script's own example";
    wrap.appendChild(ex);
  }
  return wrap;
}

function renderConstants(tool) {
  const block = el("constantsBlock");
  const list = el("constantsList");
  const constants = tool.scriptConstants || [];
  if (!constants.length) {
    block.hidden = true;
    return;
  }
  block.hidden = false;
  list.innerHTML = constants
    .map((c) => `<div class="constant-row"><span class="constant-name">${escapeHtml(c.name)}</span><span class="constant-value">${escapeHtml(c.value)}</span></div>`)
    .join("");
}

// -----------------------------------------------------------------------------------
// Collecting form values -> params object
// -----------------------------------------------------------------------------------

function collectParams(tool) {
  const form = el("paramForm");
  const params = {};

  for (const wrap of form.querySelectorAll("[data-field]")) {
    const name = wrap.getAttribute("data-field");
    const type = wrap.getAttribute("data-type");
    const input = wrap.querySelector("[data-input]");
    if (type === "bool") {
      params[name] = input.checked;
    } else if (type === "string[]") {
      const lines = input.value.split("\n").map((s) => s.trim()).filter(Boolean);
      if (lines.length) params[name] = lines;
    } else if (type === "json") {
      const raw = input.value.trim();
      if (raw) {
        try {
          params[name] = JSON.parse(raw);
        } catch {
          params[name] = raw; // let the server-side repr() treat it as a plain string
        }
      }
    } else if (type === "int") {
      if (input.value !== "") params[name] = parseInt(input.value, 10);
    } else if (type === "float") {
      if (input.value !== "") params[name] = parseFloat(input.value);
    } else {
      if (input.value !== "") params[name] = input.value;
    }
  }

  for (const wrap of form.querySelectorAll("[data-mutex-group]")) {
    const checked = wrap.querySelector("input[type=radio]:checked");
    if (!checked) continue; // nothing picked -> omit the whole group; the tool's own argparse
                             // will raise a clear "one of the arguments ... is required" error
    const name = checked.value;
    const valueInput = wrap.querySelector(`[data-mutex-value="${CSS.escape(name)}"]`);
    if (valueInput) {
      if (valueInput.value !== "") params[name] = valueInput.value;
    } else {
      params[name] = true;
    }
  }

  return params;
}

// -----------------------------------------------------------------------------------
// Running tools
// -----------------------------------------------------------------------------------

function detachCurrentRun() {
  if (state.currentRun && state.currentRun.source) {
    state.currentRun.source.close();
  }
  state.currentRun = null;
}

function resetRunUi() {
  el("runBtn").hidden = false;
  el("runBtn").disabled = false;
  el("cancelBtn").hidden = true;
  el("statusPill").hidden = true;
  el("commandPreview").hidden = true;
  el("consoleWrap").hidden = true;
  el("consoleOutput").textContent = "";
}

function setStatusPill(text, cls) {
  const pill = el("statusPill");
  pill.hidden = false;
  pill.textContent = text;
  pill.className = "status-pill" + (cls ? ` ${cls}` : "");
}

async function runSelectedTool() {
  const tool = findTool(state.selectedId);
  if (!tool) return;

  const params = collectParams(tool);
  const allSpecs = [...(tool.positionals || []), ...paramsForTool(tool)];
  const missing = allSpecs
    .filter((p) => p.required && (params[p.name] === undefined || params[p.name] === ""))
    .map((p) => p.label || p.name);
  if (missing.length) {
    alert(`Missing required parameter(s): ${missing.join(", ")}`);
    return;
  }

  el("runBtn").disabled = true;
  el("cancelBtn").hidden = false;
  el("consoleWrap").hidden = false;
  el("consoleOutput").textContent = "";
  setStatusPill("running…", "running");

  const body = { id: tool.id, params };
  if (tool.kind === "python-editor") {
    const fn = currentEntryFunction(tool);
    if (fn) body.entryFunction = fn.name;
  }

  try {
    const res = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    streamRun(data.runId);
  } catch (err) {
    appendConsoleLine(`error: ${err.message}`, true);
    finishRun(false, true);
  }
}

function streamRun(runId) {
  state.currentRun = { id: runId };
  const source = new EventSource(`/api/stream/${runId}`);
  state.currentRun.source = source;

  source.addEventListener("cmd", (ev) => {
    const data = JSON.parse(ev.data);
    el("commandPreview").hidden = false;
    el("commandText").textContent = data.command;
  });
  source.addEventListener("line", (ev) => {
    const data = JSON.parse(ev.data);
    appendConsoleLine(data.text);
  });
  source.addEventListener("done", (ev) => {
    const data = JSON.parse(ev.data);
    finishRun(data.exitCode === 0, false, data.exitCode);
    source.close();
  });
  source.onerror = () => {
    // connection dropped without a "done" event (server restarted, network blip)
    if (state.currentRun && state.currentRun.id === runId) {
      finishRun(false, true);
      source.close();
    }
  };
}

function appendConsoleLine(text, isError) {
  const out = el("consoleOutput");
  const line = document.createElement("div");
  if (isError) line.className = "console-line-err";
  line.textContent = text;
  out.appendChild(line);
  out.scrollTop = out.scrollHeight;
}

function finishRun(success, aborted, exitCode) {
  el("runBtn").disabled = false;
  el("cancelBtn").hidden = true;
  if (aborted) {
    setStatusPill("connection lost", "failed");
  } else if (success) {
    setStatusPill("done (exit 0)", "success");
  } else {
    setStatusPill(`failed (exit ${exitCode})`, "failed");
  }
  state.currentRun = null;
}

async function cancelCurrentRun() {
  if (!state.currentRun) return;
  await fetch(`/api/cancel/${state.currentRun.id}`, { method: "POST" });
  appendConsoleLine("[dev-tools-ui] cancel requested…", false);
  setStatusPill("cancelling…", "cancelled");
}

// -----------------------------------------------------------------------------------
// Ping (editor connectivity test) - runs ue_remote_exec.py --ping via the same run pipeline
// -----------------------------------------------------------------------------------

async function testEditorConnection() {
  const resultEl = el("pingResult");
  resultEl.textContent = "checking…";
  const pingTool = (state.manifest.tools || []).find((t) => t.relPath.endsWith("ue_remote_exec.py"));
  if (!pingTool) {
    resultEl.textContent = "ue_remote_exec.py not found in manifest";
    return;
  }
  try {
    const res = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: pingTool.id, params: { ping: true } }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    const lines = [];
    const source = new EventSource(`/api/stream/${data.runId}`);
    source.addEventListener("line", (ev) => lines.push(JSON.parse(ev.data).text));
    source.addEventListener("done", (ev) => {
      const exitCode = JSON.parse(ev.data).exitCode;
      resultEl.textContent = exitCode === 0
        ? `connected: ${lines.join(" ") || "editor found"}`
        : `no editor found (exit ${exitCode})`;
      source.close();
    });
  } catch (err) {
    resultEl.textContent = `error: ${err.message}`;
  }
}

// -----------------------------------------------------------------------------------
// Wire up
// -----------------------------------------------------------------------------------

function init() {
  el("rescanBtn").addEventListener("click", () => loadTools(true));
  el("searchInput").addEventListener("input", (e) => {
    state.searchText = e.target.value;
    renderGrid();
  });
  el("runBtn").addEventListener("click", runSelectedTool);
  el("cancelBtn").addEventListener("click", cancelCurrentRun);
  el("clearConsoleBtn").addEventListener("click", () => { el("consoleOutput").textContent = ""; });
  el("pingBtn").addEventListener("click", testEditorConnection);

  loadTools(true); // "scans on load"
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

document.addEventListener("DOMContentLoaded", init);
