const API_BASE = `${location.protocol}//${location.hostname}:8000`;

// --- State ---
let BUG_LABELS = [];
let TEST_LABELS = [];
let ASSIGNEES = [];
let fetchedJiraUsers = [];

// DOM Elements
const tabBtns = document.querySelectorAll(".tab-btn");
const labelTypeSelect = document.getElementById("labelTypeSelect");
const newLabelInput = document.getElementById("newLabelInput");
const addLabelBtn = document.getElementById("addLabelBtn");
const labelsContainer = document.getElementById("labelsContainer");

const assigneesList = document.getElementById("assigneesList");
const refreshAssigneesBtn = document.getElementById("refreshAssigneesBtn");
const searchAssigneeInput = document.getElementById("searchAssigneeInput");

// --- Auto-Save Logic (Completely Silent) ---
async function autoSaveSettings() {
  try {
    await fetch(`${API_BASE}/settings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bug_labels: BUG_LABELS, test_labels: TEST_LABELS, assignees: ASSIGNEES })
    });
  } catch (err) {
    console.error("Failed to auto-save settings", err);
  }
}

// --- Initialization ---
async function initSettings() {
  try {
    const res = await fetch(`${API_BASE}/settings`);
    if (res.ok) {
      const data = await res.json();
      
      // Only overwrite the defaults if the DB actually has saved a real document
      if (!data.is_empty) {
        BUG_LABELS = data.bug_labels || [];
        TEST_LABELS = data.test_labels || [];
        ASSIGNEES = data.assignees || [];
      }
    }
  } catch (err) {
    console.error("Failed to load settings from DB", err);
  }

  await fetchJiraUsers();
  renderLabels();
  renderAssignees();
}

// --- Tab Logic ---
tabBtns.forEach(btn => {
  btn.addEventListener("click", (e) => {
    tabBtns.forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach(c => c.style.display = "none");
    e.target.classList.add("active");
    document.getElementById(e.target.dataset.tab).style.display = "block";
  });
});

// --- Labels Logic ---
labelTypeSelect.addEventListener("change", renderLabels);

function renderLabels() {
  labelsContainer.innerHTML = "";
  const currentType = labelTypeSelect.value;
  const targetArray = currentType === "Bug" ? BUG_LABELS : TEST_LABELS;

  targetArray.forEach(lbl => {
    const d = document.createElement("div"); 
    
    d.style.display = "flex";
    d.style.alignItems = "center";
    d.style.justifyContent = "space-between";
    d.style.background = "#252525";
    d.style.padding = "8px 12px";
    d.style.borderRadius = "6px";
    d.style.border = "1px solid var(--border)";
    
    d.innerHTML = `
      <span style="font-weight: 600; font-family: monospace; font-size: 14px;">${lbl}</span> 
      <button class="btn">Delete</button>
    `;
    
    // Delete and auto-save
    d.querySelector("button").onclick = () => { 
      if (currentType === "Bug") BUG_LABELS = BUG_LABELS.filter(x => x !== lbl);
      if (currentType === "Test") TEST_LABELS = TEST_LABELS.filter(x => x !== lbl);
      renderLabels(); 
      autoSaveSettings(); 
    };
    
    labelsContainer.appendChild(d);
  });
}

addLabelBtn.addEventListener("click", () => {
  const val = newLabelInput.value.trim().toUpperCase().replace(/\s+/g, '_');
  if (!val) return;

  const currentType = labelTypeSelect.value;
  
  let added = false;
  if (currentType === "Bug" && !BUG_LABELS.includes(val)) { BUG_LABELS.push(val); added = true; }
  else if (currentType === "Test" && !TEST_LABELS.includes(val)) { TEST_LABELS.push(val); added = true; }
  
  newLabelInput.value = "";
  renderLabels();
  
  if (added) autoSaveSettings(); 
});

newLabelInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") addLabelBtn.click();
});


// --- Assignees Logic ---
async function fetchJiraUsers() {
  try {
    const res = await fetch(`${API_BASE}/jira/project-users`);
    if (res.ok) {
      fetchedJiraUsers = await res.json();
      
      // GHOST USER FIX: 
      // Filter out any IDs in our DB that don't actually exist in the Jira fetched list
      const cleanAssignees = [];
      fetchedJiraUsers.forEach(user => {
        // We check against old email formats just in case, but store pure Account IDs
        if (ASSIGNEES.includes(user.accountId) || 
            ASSIGNEES.includes(user.emailAddress?.split('@')[0]) || 
            ASSIGNEES.includes(user.emailAddress)) {
          cleanAssignees.push(user.accountId);
        }
      });
      
      // If the arrays are different, it means we found and removed ghosts!
      if (ASSIGNEES.length !== cleanAssignees.length) {
        ASSIGNEES = cleanAssignees;
        autoSaveSettings(); // Silent update to clear out ghosts from DB immediately
      } else {
        ASSIGNEES = cleanAssignees;
      }
    }
  } catch (err) {
    console.error("Failed to fetch Jira users", err);
  }
}

refreshAssigneesBtn.addEventListener("click", async () => {
  refreshAssigneesBtn.textContent = "Fetching...";
  refreshAssigneesBtn.disabled = true;
  await fetchJiraUsers();
  renderAssignees();
  refreshAssigneesBtn.textContent = "🔄 Fetch from Jira API";
  refreshAssigneesBtn.disabled = false;
});

searchAssigneeInput.addEventListener("input", renderAssignees);

function renderAssignees() {
  assigneesList.innerHTML = "";

  if (fetchedJiraUsers.length === 0) {
    assigneesList.innerHTML = "<p class='small' style='color: #ff4d4d;'>No users found from Jira API.</p>";
    return;
  }

  // Filter based on search input
  const query = searchAssigneeInput.value.toLowerCase().trim();
  const filteredUsers = fetchedJiraUsers.filter(u => 
    (u.displayName || "").toLowerCase().includes(query)
  );

  // Sort alphabetically by display name
  const sortedUsers = [...filteredUsers].sort((a, b) => (a.displayName || "").localeCompare(b.displayName || ""));

  if (sortedUsers.length === 0) {
    assigneesList.innerHTML = "<p class='small'>No users match your search.</p>";
    return;
  }

  sortedUsers.forEach(user => {
    const accountId = user.accountId;
    if (!accountId) return;

    const isChecked = ASSIGNEES.includes(accountId);

    const div = document.createElement("div"); 
    div.className = "assignee-item";
    
    div.innerHTML = `
      <input type="checkbox" id="chk-${accountId}" value="${accountId}" ${isChecked ? "checked" : ""}>
      <label for="chk-${accountId}" style="cursor: pointer; width: 100%;">
        <strong>${user.displayName}</strong>
      </label>
    `;

    // Toggle and auto-save
    div.querySelector("input").addEventListener("change", (e) => {
      if (e.target.checked) {
        if (!ASSIGNEES.includes(accountId)) ASSIGNEES.push(accountId);
      } else {
        ASSIGNEES = ASSIGNEES.filter(a => a !== accountId);
      }
      autoSaveSettings(); 
    });

    assigneesList.appendChild(div);
  });
}

// Run on load
initSettings();