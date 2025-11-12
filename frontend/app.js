// ===== API base =====
const API_BASE = `${location.protocol}//${location.hostname}:8000`;

// ===== UI config =====
const ASSIGNEES = ["MURADN@rafael.co.il", "ROSF@rafael.co.il", "IDANBARD@rafael.co.il", "moranmos@rafael.co.il", "yotamma@rafael.co.il"];
const TEST_TEMPLATE = `*Preconditions:*\n\n\n\n*Expected Results:*\n\n\n\n*Test Type:*\nManual + Auto`;
const BUG_TEMPLATE  = `*Steps to Reproduce:*\n\n\n\n*Expected Results:*\n\n\n\n*Actual Results:*`;
const LABELS = ["Backend", "Frontend", "AUTO_TEST"];
const linkMap = {
  Test: "Link \"Relates\"",
  Bug: "Link \"Problem/Incident\""
};

// ===== DOM =====
const rowsEl    = document.getElementById("rows");
const addRowBtn = document.getElementById("addRowBtn");
const saveBtn   = document.getElementById("saveBtn");
const saveDbBtn = document.getElementById("saveDbBtn");
const loadDbBtn = document.getElementById("loadDbBtn");
const clearDbBtn= document.getElementById("clearDbBtn");
const clearBtn  = document.getElementById("clearBtn");
const statusEl  = document.getElementById("status");
const issueTypeValue = document.getElementById("issueType")

// Modal elements
const overlayEl  = document.getElementById("editorOverlay");
const modalTitle = document.getElementById("modalTitle");
const modalTA    = document.getElementById("modalTextarea");
const modalInput = document.getElementById("modalInput");
const modalSave  = document.getElementById("modalSaveBtn");
const modalClose = document.getElementById("modalCloseBtn");
const modalInsertTemplateBtn = document.getElementById("modalInsertTemplateBtn");

// ===== Modal state =====
let activeKind = null; // 'description' | 'summary'
let activeIssueTypeSelect = null;
let sourceEl = null;   // original field in the table

// ===== Helpers =====

function update_columns() {
  let selected_value = issueTypeValue.value
  const linkTitle = linkMap[selected_value];

  const table = rowsEl.closest("table");
  if (table) {
    const ths = table.querySelectorAll("thead th");
    if (ths[3]) ths[3].textContent = linkTitle;
  }

  for (const tr of rowsEl.querySelectorAll("tr")) {
    const tds = tr.querySelectorAll("td");

    const issueEl = tds[1]?.querySelector("input");
    if (issueEl) issueEl.value = issueTypeValue.value;

    const linkEl = tds[3]?.querySelector('input[type="text"]');
    if (linkEl) {
      linkEl.setAttribute("aria-label", linkTitle);
      linkEl.title = linkTitle;
    }
  }
}

function makeCell(inner) {
  const td = document.createElement("td");
  td.appendChild(inner);
  return td;
}
function makeSelect(options, placeholder = "") {
  const sel = document.createElement("select");
  if (placeholder) {
    const opt = document.createElement("option");
    opt.value = ""; opt.textContent = placeholder; opt.disabled = true; opt.selected = true;
    sel.appendChild(opt);
  }
  for (const val of options) {
    const opt = document.createElement("option");
    opt.value = val; opt.textContent = val;
    sel.appendChild(opt);
  }
  return sel;
}

function gatherRows() {
  const data = [];
  for (const tr of rowsEl.querySelectorAll("tr")) {
    const tds = tr.querySelectorAll("td");
    const summaryEl = tds[0].querySelector("input");
    const issueEl   = tds[1].querySelector("input");
    const descEl    = tds[2].querySelector("textarea");
    const linkEl    = tds[3].querySelector("input");
    const assignEl  = tds[4].querySelector("select");
    const labelEl   = tds[5].querySelector(".labels-hidden");
    const nsocEl    = tds[6].querySelector("input"); 

    const row = {
      summary: (summaryEl?.value || "").trim(),
      issue_type: (issueEl?.value || "").trim(),
      description: (descEl?.value || "").trim(),
      link_relates: (linkEl?.value || "").trim(),
      assignee: (assignEl?.value || "").trim(),
      labels: (labelEl?.value || "").trim(),
      nsoc_team: (nsocEl?.value || "").trim()
    };
    if (Object.values(row).some(v => v.length)) data.push(row);
  }
  return data;
}

function parseLabels(str) {
  if (!str) return [];
  return str.split(/[,\s]+/).filter(Boolean);
}

function createLabelsPicker(initialLabels = []) {
  const selected = new Set(initialLabels);

  const wrap = document.createElement("div");
  wrap.className = "labels-picker";

  const hidden = document.createElement("input");
  hidden.type = "hidden";
  hidden.className = "labels-hidden";

  function updateHidden() {
    hidden.value = Array.from(selected).join(" ");
  }

  function makePill(name) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "label-pill";
    btn.setAttribute("aria-pressed", selected.has(name) ? "true" : "false");
    btn.textContent = name;
    btn.addEventListener("click", () => {
      if (selected.has(name)) selected.delete(name);
      else selected.add(name);
      btn.setAttribute("aria-pressed", selected.has(name) ? "true" : "false");
      updateHidden();
    });
    return btn;
  }

  LABELS.forEach(lbl => wrap.appendChild(makePill(lbl)));
  updateHidden();
  wrap.appendChild(hidden);

  return wrap; // cell will contain this
}

// ===== Modal controls =====
function openModal(kind, fromEl, issueTypeSelect) {
  activeKind = kind;
  sourceEl = fromEl;
  activeIssueTypeSelect = issueTypeSelect || null;

  if (kind === "summary") {
    modalTitle.textContent = "Edit Summary";
    modalInput.style.display = "";
    modalTA.style.display = "none";
    modalInput.value = fromEl.value || "";
    modalInsertTemplateBtn.style.display = "none";
    setTimeout(() => modalInput.focus(), 0);
  } else {
    modalTitle.textContent = "Edit Description";
    modalInput.style.display = "none";
    modalTA.style.display = "";
    modalTA.value = fromEl.value || "";
    modalInsertTemplateBtn.style.display = "";
    setTimeout(() => modalTA.focus(), 0);
  }

  document.body.classList.add("modal-open");
  overlayEl.classList.add("active");
}
function closeModal() {
  overlayEl.classList.remove("active");
  document.body.classList.remove("modal-open");
  activeKind = null; sourceEl = null; activeIssueTypeSelect = null;
}
function saveModal() {
  if (!sourceEl) return closeModal();
  if (activeKind === "summary") {
    sourceEl.value = modalInput.value;
  } else {
    sourceEl.value = modalTA.value;
  }
  sourceEl.dispatchEvent(new Event("input", { bubbles: true }));
  sourceEl.focus();
  closeModal();
}
function insertTemplate(targetTA, basedOn) {
  if (!basedOn || !basedOn.value) { alert("Select Issue Type!"); return; }
  const template = basedOn.value === "Test" ? TEST_TEMPLATE
                 : basedOn.value === "Bug"  ? BUG_TEMPLATE : "";
  const current = targetTA.value.trim();
  targetTA.value = current ? current + "\n\n" + template : template;
  targetTA.focus();
}

overlayEl.addEventListener("click", (e) => {
  if (e.target === overlayEl) saveModal();
});
modalClose.addEventListener("click", closeModal);
modalSave.addEventListener("click", saveModal);
modalInsertTemplateBtn.addEventListener("click", () => {
  if (activeKind !== "description") return;
  insertTemplate(modalTA, activeIssueTypeSelect);
});
window.addEventListener("keydown", (e) => {
  if (!overlayEl.classList.contains("active")) return;
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") { e.preventDefault(); saveModal(); }
  if (e.key === "Escape") { e.preventDefault(); closeModal(); }
});

// ===== Rows =====
function addRow(initial = {}) {
  const tr = document.createElement("tr");

  // Summary
  const summary = Object.assign(document.createElement("input"), {
    type: "text", placeholder: "Summary", value: initial.summary || ""
  });
  const summaryWrap = document.createElement("div");
  summaryWrap.style.display = "flex";
  summaryWrap.style.flexDirection = "column";
  const summaryBtns = document.createElement("div");
  summaryBtns.style.display = "flex"; summaryBtns.style.gap = "8px"; summaryBtns.style.marginTop = "6px";
  const summaryExpandBtn = Object.assign(document.createElement("button"), {
    className: "btn", type: "button", innerText: "🗖 Expand"
  });
  summaryExpandBtn.addEventListener("click", () => openModal("summary", summary));
  summaryWrap.appendChild(summary);
  summaryBtns.appendChild(summaryExpandBtn);
  summaryWrap.appendChild(summaryBtns);

  // Issue Type
  const issueType = Object.assign(document.createElement("input"), { type: "text", value: issueTypeValue.value, readOnly: true});

  // Description
  const descWrapper = document.createElement("div");
  descWrapper.style.display = "flex";
  descWrapper.style.flexDirection = "column";
  const desc = Object.assign(document.createElement("textarea"), { placeholder: "Description" });
  desc.value = initial.description || "";

  const rowButtons = document.createElement("div");
  rowButtons.style.display = "flex"; rowButtons.style.gap = "8px"; rowButtons.style.marginTop = "6px";

  const insertBtn = Object.assign(document.createElement("button"), {
    className: "btn", type: "button", innerText: "📋 Insert Template"
  });
  insertBtn.addEventListener("mousedown", e => e.preventDefault());
  insertBtn.addEventListener("click", () => { insertTemplate(desc, issueType); });

  const expandBtn = Object.assign(document.createElement("button"), {
    className: "btn", type: "button", innerText: "🗖 Expand"
  });
  expandBtn.addEventListener("click", () => openModal("description", desc, issueType));

  rowButtons.appendChild(insertBtn);
  rowButtons.appendChild(expandBtn);
  descWrapper.appendChild(desc);
  descWrapper.appendChild(rowButtons);

  // Link "Relates"
  const linkRel = Object.assign(document.createElement("input"), {
    type: "text", placeholder: "NSOC-12345", value: initial.link_relates || ""
  });

  // Assignee
  const assignee = makeSelect(ASSIGNEES, "Select assignee");
  if (initial.assignee && ASSIGNEES.includes(initial.assignee)) assignee.value = initial.assignee;

// Labels (multi-select)
  const labelsPicker = createLabelsPicker(parseLabels(initial.labels));

  // NSOC_Team
  const nsoc = Object.assign(document.createElement("input"), { type: "text", value: initial.nsoc_team || "CYMNG" });

  // Delete
  const delBtn = Object.assign(document.createElement("button"), {
    className: "btn", type: "button", innerText: "Delete"
  });
  delBtn.addEventListener("click", () => { tr.remove(); });

  

  // Build row
  tr.appendChild(makeCell(summaryWrap));
  tr.appendChild(makeCell(issueType));
  tr.appendChild(makeCell(descWrapper));
  tr.appendChild(makeCell(linkRel));
  tr.appendChild(makeCell(assignee));
  tr.appendChild(makeCell(labelsPicker));
  tr.appendChild(makeCell(nsoc));

  const actions = document.createElement("div");
  actions.className = "actions";
  actions.appendChild(delBtn);
  tr.appendChild(makeCell(actions));

  rowsEl.appendChild(tr);
  return tr;
}

// ===== CSV API =====
async function saveCSV() {
  statusEl.textContent = "Saving…";
  const rows = gatherRows();
  if (rows.length === 0) {
    statusEl.textContent = "Nothing to save (all rows empty).";
    return;
  }

  try {
    let selected_value = issueTypeValue.value
    const res = await fetch(`${API_BASE}/save-csv?issue_type=${selected_value}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rows }),
    });

    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    const json = await res.json();

    if (json && json.filename) {
      statusEl.textContent = "";

      const downloadBtn = Object.assign(document.createElement("button"), {
        className: "btn",
        type: "button",
        innerText: "⬇️ Download CSV",
      });

      // Make button actually download
      downloadBtn.addEventListener("click", () => {
        window.open(`${API_BASE}/download/${encodeURIComponent(json.filename)}`, "_blank");
      });

      statusEl.appendChild(downloadBtn);
    } else {
      statusEl.textContent = "Saved, but no filename returned.";
    }
  } catch (err) {
    console.error(err);
    statusEl.textContent = "Error saving CSV. See console.";
  }
}


// ===== DB API =====
async function saveDB() {
  const rows = gatherRows();
  if (rows.length === 0) {
    statusEl.textContent = "Nothing to save (all rows empty).";
    return;
  }
  statusEl.textContent = "Saving to DB…";
  try {
    let selected_value = issueTypeValue.value
    const res = await fetch(`${API_BASE}/save-db?issue_type=${selected_value}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rows })
    });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    const json = await res.json();
    statusEl.textContent = `Saved to DB.`;
  } catch (err) {
    console.error(err);
    statusEl.textContent = "Error saving to DB. See console.";
  }
}

async function loadFromDB() {
  try {
    let selected_value = issueTypeValue.value
    const res = await fetch(`${API_BASE}/cases?issue_type=${selected_value}`);
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    const json = await res.json();
    const rows = json.rows || [];
    rowsEl.innerHTML = "";
    if (rows.length === 0) addRow();
    rows.forEach(r => addRow(r));
  } catch (err) {
    console.error(err);
    statusEl.textContent = "Error loading from DB. See console.";
  }
}

async function clearDB() {
  if (!confirm("Delete ALL rows from the database?")) return;
  statusEl.textContent = "Clearing DB…";
  try {
    let selected_value = issueTypeValue.value
    const res = await fetch(`${API_BASE}/cases?issue_type=${selected_value}`, { method: "DELETE" });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    await res.json();
    statusEl.textContent = "DB cleared";
  } catch (err) {
    console.error(err);
    statusEl.textContent = "Error clearing DB. See console.";
  }
}

// ===== Clear All (UI only) =====
function clearAll() {
  if (!confirm("Clear all rows and reset the form?")) return;
  rowsEl.innerHTML = "";
  statusEl.textContent = "";
  addRow();
}

// ===== Wire up and start =====
issueTypeValue.addEventListener("click", () => {
  update_columns();
  loadFromDB();
});
addRowBtn.addEventListener("click", () => addRow());
saveBtn.addEventListener("click", saveCSV);
saveDbBtn.addEventListener("click", saveDB);
loadDbBtn.addEventListener("click", loadFromDB);
clearDbBtn.addEventListener("click", clearDB);
clearBtn.addEventListener("click", clearAll);
document.addEventListener('keydown', function (event) {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
    event.preventDefault(); // Prevent the browser's default Save dialog
    saveDB();
  }
});

// Start with one empty row
addRow();
loadFromDB()
