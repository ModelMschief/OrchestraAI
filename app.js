const TOKEN_KEY = "orchestraai_token";

const state = {
  token: localStorage.getItem(TOKEN_KEY),
  currentUser: null,
  bootstrap: null,
  workspace: null,
  selectedAgentId: null,
};

const dom = {
  authShell: document.getElementById("auth-shell"),
  pageShell: document.getElementById("page-shell"),
  authBanner: document.getElementById("auth-banner"),
  signupForm: document.getElementById("signup-form"),
  loginForm: document.getElementById("login-form"),
  userName: document.getElementById("user-name"),
  userEmail: document.getElementById("user-email"),
  userApiKey: document.getElementById("user-api-key"),
  logoutButton: document.getElementById("logout-button"),
  navItems: [...document.querySelectorAll(".nav-item")],
  panels: [...document.querySelectorAll(".tab-panel")],
  quickTargets: [...document.querySelectorAll("[data-tab-target]")],
  banner: document.getElementById("system-banner"),
  providerGrid: document.getElementById("provider-grid"),
  providerForm: document.getElementById("provider-form"),
  providerStatus: document.getElementById("provider-status"),
  agentForm: document.getElementById("agent-form"),
  agentStatusNote: document.getElementById("agent-status-note"),
  agentList: document.getElementById("agent-list"),
  overviewAgentList: document.getElementById("overview-agent-list"),
  selectedAgentPill: document.getElementById("selected-agent-pill"),
  agentName: document.getElementById("agent-name"),
  agentStatus: document.getElementById("agent-status"),
  agentTagline: document.getElementById("agent-tagline"),
  agentIdDisplay: document.getElementById("agent-id-display"),
  agentProviders: document.getElementById("agent-providers"),
  agentKnowledge: document.getElementById("agent-knowledge"),
  agentOptimization: document.getElementById("agent-optimization"),
  agentUsage: document.getElementById("agent-usage"),
  agentContract: document.getElementById("agent-contract"),
  agentTools: document.getElementById("agent-tools"),
  agentGuardrails: document.getElementById("agent-guardrails"),
  documentForm: document.getElementById("document-form"),
  documentStatus: document.getElementById("document-status"),
  agentDocumentList: document.getElementById("agent-document-list"),
  chatForm: document.getElementById("chat-form"),
  chatStatus: document.getElementById("chat-status"),
  chatThread: document.getElementById("chat-thread"),
  knowledgeDocList: document.getElementById("knowledge-doc-list"),
  knowledgeAgentLabel: document.getElementById("knowledge-agent-label"),
  knowledgeGraphLabel: document.getElementById("knowledge-graph-label"),
  knowledgeUploadForm: document.getElementById("knowledge-upload-form"),
  knowledgeFileInput: document.getElementById("knowledge-file-input"),
  knowledgeDropZone: document.getElementById("knowledge-drop-zone"),
  knowledgeSelectButton: document.getElementById("knowledge-select-button"),
  knowledgeUploadStatus: document.getElementById("knowledge-upload-status"),
  graphMap: document.getElementById("graph-map"),
  relationshipList: document.getElementById("relationship-list"),
  runtimeQuestion: document.getElementById("runtime-question"),
  runtimeStrategy: document.getElementById("runtime-strategy"),
  runtimeAnswerPreview: document.getElementById("runtime-answer-preview"),
  runtimeMatrix: document.getElementById("runtime-matrix"),
  runtimeGates: document.getElementById("runtime-gates"),
  runtimeTraceId: document.getElementById("runtime-trace-id"),
  overviewRuntimeFlow: document.getElementById("overview-runtime-flow"),
  fleetNote: document.getElementById("fleet-note"),
  usageLeaderboard: document.getElementById("usage-leaderboard"),
  providerSpend: document.getElementById("provider-spend"),
  heroProviders: document.getElementById("hero-providers"),
  heroSummary: document.getElementById("hero-summary"),
  heroDocuments: document.getElementById("hero-documents"),
  heroEntities: document.getElementById("hero-entities"),
  heroAgents: document.getElementById("hero-agents"),
  heroMessages: document.getElementById("hero-messages"),
  overviewProviders: document.getElementById("overview-providers"),
  overviewAgents: document.getElementById("overview-agents"),
  overviewChunks: document.getElementById("overview-chunks"),
  overviewEntities: document.getElementById("overview-entities"),
  metricTokenSavings: document.getElementById("metric-token-savings"),
  metricLatency: document.getElementById("metric-latency"),
  metricCachedHits: document.getElementById("metric-cached-hits"),
  metricWebRuns: document.getElementById("metric-web-runs"),
  overviewStatus: document.getElementById("overview-status"),
};

function authHeaders(extra = {}) {
  const headers = { ...extra };
  if (state.token) {
    headers.Authorization = `Bearer ${state.token}`;
  }
  return headers;
}

async function apiRequest(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: authHeaders(options.headers || {}),
  });

  if (response.status === 401) {
    clearSession();
    showAuthShell("Your session expired. Please log in again.", true);
    throw new Error("Authentication required.");
  }

  if (!response.ok) {
    throw new Error(await readError(response));
  }
  return response;
}

async function apiGet(path) {
  return (await apiRequest(path)).json();
}

async function apiPostJSON(path, payload, includeAuth = true) {
  const response = await fetch(path, {
    method: "POST",
    headers: includeAuth
      ? authHeaders({ "Content-Type": "application/json" })
      : { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (includeAuth && response.status === 401) {
    clearSession();
    showAuthShell("Your session expired. Please log in again.", true);
    throw new Error("Authentication required.");
  }

  if (!response.ok) {
    throw new Error(await readError(response));
  }
  return response.json();
}

async function apiPostForm(path, formData) {
  return (await apiRequest(path, { method: "POST", body: formData })).json();
}

async function apiDelete(path) {
  return (await apiRequest(path, { method: "DELETE" })).json();
}

window.deleteDocument = async function(documentId) {
  if (!confirm("Are you sure you want to delete this document?")) return;
  try {
    await apiDelete(`/api/agents/${state.selectedAgentId}/documents/${documentId}`);
    setBanner("Document deleted successfully.");
    await loadBootstrap(true);
    await loadWorkspace(state.selectedAgentId);
  } catch (error) {
    setBanner(`Failed to delete document: ${error.message}`, true);
  }
};

async function readError(response) {
  try {
    const payload = await response.json();
    return payload.detail || JSON.stringify(payload);
  } catch {
    return response.statusText;
  }
}

function setBanner(message, isError = false) {
  dom.banner.textContent = message;
  dom.banner.classList.toggle("is-error", isError);
}

function setAuthBanner(message, isError = false) {
  dom.authBanner.textContent = message;
  dom.authBanner.classList.toggle("is-error", isError);
}

function showAuthShell(message, isError = false) {
  dom.authShell.classList.remove("hidden");
  dom.pageShell.classList.add("hidden");
  if (message) {
    setAuthBanner(message, isError);
  }
}

function showAppShell() {
  dom.authShell.classList.add("hidden");
  dom.pageShell.classList.remove("hidden");
}

function setSession(token, user) {
  state.token = token;
  state.currentUser = user;
  localStorage.setItem(TOKEN_KEY, token);
}

function clearSession() {
  state.token = null;
  state.currentUser = null;
  state.bootstrap = null;
  state.workspace = null;
  state.selectedAgentId = null;
  localStorage.removeItem(TOKEN_KEY);
}

function applyUser() {
  dom.userName.textContent = state.currentUser?.name || "Not signed in";
  dom.userEmail.textContent = state.currentUser?.email || "Authenticate to load your workspace.";
  if (dom.userApiKey) {
    dom.userApiKey.textContent = state.currentUser?.api_key || "Not generated yet";
  }
}

function setActiveTab(tabId) {
  dom.navItems.forEach((item) => item.classList.toggle("is-active", item.dataset.tab === tabId));
  dom.panels.forEach((panel) => panel.classList.toggle("is-active", panel.id === tabId));
}

function renderEmpty(container, message) {
  container.innerHTML = `<div class="empty-state">${message}</div>`;
}

async function loadBootstrap(preserveSelection = true) {
  const data = await apiGet("/api/bootstrap");
  state.bootstrap = data;
  state.currentUser = data.user;
  applyUser();
  const agents = data.agents || [];
  if (!preserveSelection || !state.selectedAgentId || !agents.some((agent) => agent.id === state.selectedAgentId)) {
    state.selectedAgentId = agents[0]?.id ?? null;
  }
  renderOverview(data);
  renderProviders(data.providers || []);
  renderAgentLists(agents);
  renderUsage(data.usage || {});
  renderRuntime(data.usage?.latest_runtime || null);
  if (state.selectedAgentId) {
    await loadWorkspace(state.selectedAgentId);
  } else {
    clearWorkspace();
  }
}

async function loadWorkspace(agentId) {
  state.workspace = await apiGet(`/api/agents/${agentId}/workspace`);
  renderWorkspace();
}

function renderOverview(data) {
  const overview = data.overview || {};
  const providerCount = (data.providers || []).filter((provider) => provider.status === "validated").length;
  dom.heroProviders.textContent = `${providerCount} providers online`;
  dom.heroSummary.textContent = providerCount
    ? `${state.currentUser?.name || "Developer"}, your providers are validated and ready for routing.`
    : "Add an OpenAI, Gemini, or Groq key to unlock validation, graph extraction, and live chat generation.";
  dom.heroDocuments.textContent = overview.documents || 0;
  dom.heroEntities.textContent = overview.entities || 0;
  dom.heroAgents.textContent = overview.agents || 0;
  dom.heroMessages.textContent = overview.messages || 0;
  dom.overviewProviders.textContent = providerCount;
  dom.overviewAgents.textContent = overview.agents || 0;
  dom.overviewChunks.textContent = overview.chunks || 0;
  dom.overviewEntities.textContent = overview.entities || 0;
  dom.overviewStatus.textContent = providerCount ? "System healthy" : "Needs provider setup";
}

function renderProviders(providers) {
  if (!providers.length) {
    renderEmpty(dom.providerGrid, "No providers added yet. Validate an OpenAI, Gemini, or Groq key to activate your runtime.");
    return;
  }
  dom.providerGrid.innerHTML = providers
    .map((provider) => {
      const capabilityChips = (provider.capabilities || []).map((cap) => `<span>${cap}</span>`).join("");
      const modelLabel = provider.default_model || provider.models?.[0] || "Auto-select at runtime";
      return `
        <article class="provider-card">
          <div class="provider-topline">
            <div>
              <h3>${capitalize(provider.provider_type)}</h3>
              <p>${provider.masked_key}</p>
            </div>
            <span class="status-pill ${provider.status === "validated" ? "success" : "warning"}">${provider.status}</span>
          </div>
          <div class="provider-meta">
            <div><span>Default model</span><strong>${escapeHtml(modelLabel)}</strong></div>
            <div><span>Available models</span><strong>${provider.models?.length || 0}</strong></div>
            <div><span>Last validation</span><strong>${formatDate(provider.last_validated_at)}</strong></div>
          </div>
          <div class="chip-row">${capabilityChips || "<span>No capabilities recorded</span>"}</div>
          ${provider.last_error ? `<p class="inline-note error-note">${escapeHtml(provider.last_error)}</p>` : ""}
        </article>
      `;
    })
    .join("");
}

function renderAgentLists(agents) {
  if (!agents.length) {
    renderEmpty(dom.agentList, "No agents yet. Create one to start your runtime.");
    renderEmpty(dom.overviewAgentList, "No agent fleet yet.");
    dom.fleetNote.textContent = "No agents created";
    return;
  }
  dom.fleetNote.textContent = `${agents.length} agents in your runtime`;
  const cardMarkup = (agent, compact = false) => `
    <article class="agent-item ${state.selectedAgentId === agent.id && !compact ? "is-selected" : ""}" data-agent-id="${agent.id}">
      <div class="agent-topline">
        <div>
          <strong>${escapeHtml(agent.name)}</strong>
          <p>${escapeHtml(agent.tagline || "No tagline yet")}</p>
        </div>
        <span class="status-pill ${agent.status === "Active" ? "success" : "warning"}">${escapeHtml(agent.status)}</span>
      </div>
    </article>
  `;
  dom.agentList.innerHTML = agents.map((agent) => cardMarkup(agent, false)).join("");
  dom.overviewAgentList.innerHTML = agents.map((agent) => cardMarkup(agent, true)).join("");
}

function clearWorkspace() {
  dom.selectedAgentPill.textContent = "No agent selected";
  dom.agentName.textContent = "Select an agent";
  dom.agentStatus.textContent = "Idle";
  dom.agentTagline.textContent = "Create or select an agent to load its isolated workspace.";
  if (dom.agentIdDisplay) dom.agentIdDisplay.textContent = "None";
  dom.agentProviders.textContent = "No providers yet";
  dom.agentKnowledge.textContent = "0 documents / 0 chunks";
  dom.agentOptimization.textContent = "Balanced";
  dom.agentUsage.textContent = "0 messages";
  dom.agentContract.textContent = "The runtime instructions will appear here.";
  dom.agentTools.innerHTML = "<span>Knowledge lookup</span><span>Web search</span><span>Provider routing</span>";
  dom.agentGuardrails.innerHTML = "<span>No cross-agent knowledge</span><span>Prompt packing</span>";
  renderEmpty(dom.agentDocumentList, "Upload a document to start the agent learning pipeline.");
  renderEmpty(dom.chatThread, "No chat messages yet. Ask a question after selecting an agent.");
  renderEmpty(dom.knowledgeDocList, "No documents ingested yet.");
  dom.graphMap.innerHTML = '<div class="empty-state graph-empty">Graph nodes will appear after document processing.</div>';
  renderEmpty(dom.relationshipList, "No relationships extracted yet.");
  dom.knowledgeAgentLabel.textContent = "No agent selected";
  dom.knowledgeGraphLabel.textContent = "graph idle";
  dom.knowledgeUploadStatus.textContent = "Select an agent first, then upload knowledge directly from this tab.";
}

function renderWorkspace() {
  const workspace = state.workspace;
  if (!workspace?.agent) {
    clearWorkspace();
    return;
  }
  const agent = workspace.agent;
  const providers = (state.bootstrap?.providers || []).filter((provider) => provider.status === "validated");
  const documents = workspace.documents || [];
  const messages = workspace.messages || [];
  const graph = workspace.graph || { entities: [], relationships: [] };

  dom.selectedAgentPill.textContent = agent.name;
  dom.agentName.textContent = agent.name;
  dom.agentStatus.textContent = agent.status;
  dom.agentStatus.className = `status-pill ${agent.status === "Active" ? "success" : "warning"}`;
  dom.agentTagline.textContent = agent.tagline || "No tagline set for this agent yet.";
  if (dom.agentIdDisplay) dom.agentIdDisplay.textContent = agent.id;
  dom.agentProviders.textContent = providers.length
    ? providers.map((provider) => capitalize(provider.provider_type)).join(", ")
    : "No validated providers";
  dom.agentKnowledge.textContent = `${documents.length} documents / ${documents.reduce((sum, doc) => sum + (doc.chunk_count || 0), 0)} chunks`;
  dom.agentOptimization.textContent = agent.optimization_mode || "balanced";
  dom.agentUsage.textContent = `${messages.length} messages logged`;
  dom.agentContract.textContent = agent.system_prompt || "No system prompt set yet.";
  dom.agentTools.innerHTML = [
    "Knowledge lookup",
    "Local embeddings",
    agent.allow_web_search ? "Web search" : "Web disabled",
    "Provider routing",
  ].map((item) => `<span>${item}</span>`).join("");
  dom.agentGuardrails.innerHTML = [
    "No cross-agent memory",
    "Prompt budget packing",
    "Grounded sources",
    agent.allow_web_search ? "Freshness fallback on" : "Freshness fallback off",
  ].map((item) => `<span>${item}</span>`).join("");

  if (!documents.length) {
    renderEmpty(dom.agentDocumentList, "No documents yet. Upload PDF, DOCX, TXT, or Markdown to teach this agent.");
    renderEmpty(dom.knowledgeDocList, "No documents ingested yet.");
  } else {
    const docMarkup = documents
      .map((doc) => `
        <div class="doc-row">
          <div>
            <strong>${escapeHtml(doc.filename)}</strong>
            <p>${escapeHtml(doc.summary || "Processed document")}</p>
          </div>
          <span class="usage-tag">${doc.chunk_count} chunks</span>
          <button class="secondary-action slim" onclick="deleteDocument(${doc.id})">Delete</button>
        </div>
      `)
      .join("");
    dom.agentDocumentList.innerHTML = docMarkup;
    dom.knowledgeDocList.innerHTML = documents
      .map((doc) => `
        <li>
          <span>${escapeHtml(doc.filename)}</span>
          <strong>${doc.status} / ${doc.entity_count} entities</strong>
          <button class="secondary-action slim delete-btn" onclick="deleteDocument(${doc.id})" style="margin-left: 10px;">Delete</button>
        </li>
      `)
      .join("");
  }

  renderMessages(messages);
  renderGraph(graph, agent.name);
  dom.knowledgeAgentLabel.textContent = agent.name;
  dom.knowledgeGraphLabel.textContent = `${graph.entities?.length || 0} entities / ${graph.relationships?.length || 0} relationships`;
  dom.knowledgeUploadStatus.textContent = `Ready to upload knowledge into ${agent.name}.`;
}

function renderMessages(messages) {
  if (!messages.length) {
    renderEmpty(dom.chatThread, "No chat messages yet. Ask a question after selecting an agent.");
    return;
  }
  dom.chatThread.innerHTML = messages
    .map((message) => {
      const sources = (message.sources || [])
        .map((source) => source.url
          ? `<a href="${source.url}" target="_blank" rel="noreferrer">${escapeHtml(source.label)}</a>`
          : `<span>${escapeHtml(source.label)}</span>`)
        .join("");
      return `
        <article class="chat-message ${message.role}">
          <div class="chat-meta">
            <strong>${message.role === "assistant" ? "Runtime answer" : "User prompt"}</strong>
            <span>${formatDate(message.created_at)}</span>
          </div>
          <p>${escapeHtml(message.content)}</p>
          ${sources ? `<div class="source-list">${sources}</div>` : ""}
        </article>
      `;
    })
    .join("");
}

function renderGraph(graph, agentName) {
  const entities = graph.entities || [];
  const relationships = graph.relationships || [];
  if (!entities.length) {
    dom.graphMap.innerHTML = '<div class="empty-state graph-empty">Upload a document or connect a provider for richer graph extraction.</div>';
    renderEmpty(dom.relationshipList, "No graph relationships yet.");
    return;
  }
  const positions = ["core", "branch a", "branch b", "branch c", "branch d", "leaf e", "leaf f", "leaf g", "leaf h"];
  dom.graphMap.innerHTML = entities
    .slice(0, positions.length)
    .map((entity, index) => `<span class="node ${positions[index]}">${escapeHtml(entity.name)}</span>`)
    .join("");
  dom.relationshipList.innerHTML = relationships.length
    ? relationships.slice(0, 8).map((relation) => `
        <div class="leaderboard-row">
          <div>
            <strong>${escapeHtml(relation.source_entity)} -> ${escapeHtml(relation.target_entity)}</strong>
            <p>${escapeHtml(relation.relation)}</p>
          </div>
          <span class="usage-tag">${escapeHtml(agentName)}</span>
        </div>
      `).join("")
    : '<div class="empty-state">Entities were found, but no relationships were extracted yet.</div>';
}

function renderRuntime(runtime) {
  if (!runtime) {
    dom.runtimeQuestion.textContent = "No runtime request yet.";
    dom.runtimeStrategy.textContent = "Local retrieval, optional web grounding, provider routing, and final synthesis will appear here.";
    dom.runtimeAnswerPreview.textContent = "Run a chat request to inspect the runtime trace.";
    dom.runtimeTraceId.textContent = "No request yet";
    dom.runtimeMatrix.innerHTML = '<div><span>Routing</span><strong>Waiting for first response</strong></div>';
    dom.overviewRuntimeFlow.innerHTML = `
      <li>
        <strong>Waiting for first request</strong>
        <p>Create an agent, upload documents, and chat to generate a live runtime trace.</p>
      </li>
    `;
    return;
  }
  dom.runtimeQuestion.textContent = runtime.query || "No captured question.";
  dom.runtimeStrategy.textContent = [
    `Local chunks: ${runtime.local_chunk_count || 0}`,
    `Web search used: ${runtime.used_web_search ? "yes" : "no"}`,
    `Provider: ${runtime.selected_provider || "fallback"}`,
    `Model: ${runtime.selected_model || "fallback synthesis"}`,
  ].join(" / ");
  dom.runtimeAnswerPreview.textContent = runtime.answer_preview || "Latest answer preview unavailable.";
  dom.runtimeTraceId.textContent = runtime.selected_model || "runtime trace";
  const providerRows = [
    ["Local retrieval", `${runtime.local_chunk_count || 0} chunks`],
    ["Web search", runtime.used_web_search ? `${runtime.web_result_count || 0} pages` : "Skipped"],
    ["Provider", runtime.selected_provider || "Fallback"],
    ["Model", runtime.selected_model || "No live model"],
  ];
  dom.runtimeMatrix.innerHTML = providerRows
    .map(([label, value]) => `<div><span>${label}</span><strong>${escapeHtml(String(value))}</strong></div>`)
    .join("");
  const steps = [
    { title: "Intent classified", detail: "Runtime captured the request and prepared the orchestration path." },
    { title: "Knowledge retrieval", detail: `${runtime.local_chunk_count || 0} local chunks were retrieved from the selected agent's vector index.` },
    {
      title: "Freshness decision",
      detail: runtime.used_web_search
        ? `${runtime.web_result_count || 0} web pages were collected because freshness or confidence required it.`
        : "Web search was skipped because local knowledge looked sufficient.",
    },
    {
      title: "Model routing",
      detail: `${runtime.selected_provider || "Fallback"} handled final synthesis${runtime.selected_model ? ` using ${runtime.selected_model}` : ""}.`,
    },
  ];
  dom.overviewRuntimeFlow.innerHTML = steps
    .map((step) => `<li><strong>${step.title}</strong><p>${escapeHtml(step.detail)}</p></li>`)
    .join("");
  const notes = runtime.optimization_notes || [];
  if (notes.length) {
    dom.runtimeGates.innerHTML = notes
      .map((note, index) => `<div><strong>Optimization ${index + 1}</strong><p>${escapeHtml(note)}</p></div>`)
      .join("");
  }
}

function renderUsage(usage) {
  const providerMix = usage.provider_mix || [];
  const leaderboard = usage.leaderboard || [];
  const metrics = usage.metrics || {};
  dom.providerSpend.innerHTML = providerMix.length
    ? providerMix.map((entry) => `
        <div>
          <span>${escapeHtml(capitalize(entry.provider))}</span>
          <em style="width: ${Math.max(entry.percentage || 0, 4)}%"></em>
          <strong>${entry.percentage}%</strong>
        </div>
      `).join("")
    : '<div class="empty-state">No assistant responses yet. Usage bars will appear after chatting.</div>';
  dom.usageLeaderboard.innerHTML = leaderboard.length
    ? leaderboard.map((row) => `
        <div class="leaderboard-row">
          <div>
            <strong>${escapeHtml(row.name)}</strong>
            <p>${escapeHtml(row.detail)}</p>
          </div>
          <span class="usage-tag">${escapeHtml(row.usage)}</span>
        </div>
      `).join("")
    : '<div class="empty-state">No agent usage yet.</div>';
  dom.metricTokenSavings.textContent = `${metrics.token_savings || 0}%`;
  dom.metricLatency.textContent = `${metrics.latency_reduction || 0}%`;
  dom.metricCachedHits.textContent = metrics.cached_hits || 0;
  dom.metricWebRuns.textContent = metrics.web_assisted_runs || 0;
}

function capitalize(value) {
  const labels = { openai: "OpenAI", gemini: "Gemini", groq: "Groq", fallback: "Fallback" };
  return labels[value] || (value ? value.charAt(0).toUpperCase() + value.slice(1) : value);
}

function formatDate(value) {
  if (!value) return "Not yet";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function uploadKnowledgeFile(file, statusElement) {
  if (!state.selectedAgentId) {
    setBanner("Select an agent before uploading documents.", true);
    statusElement.textContent = "Select an agent before uploading.";
    return;
  }
  if (!file) {
    setBanner("Choose a file before uploading.", true);
    statusElement.textContent = "Choose a file before uploading.";
    return;
  }
  const formData = new FormData();
  formData.append("file", file);
  statusElement.textContent = `Processing ${file.name} through the learning pipeline...`;
  try {
    await apiPostForm(`/api/agents/${state.selectedAgentId}/documents`, formData);
    statusElement.textContent = `${file.name} learned successfully.`;
    dom.documentStatus.textContent = "Document learned successfully.";
    setBanner("Document processed and indexed.");
    await loadBootstrap(true);
    setActiveTab("knowledge");
  } catch (error) {
    statusElement.textContent = error.message;
    setBanner(`Document processing failed: ${error.message}`, true);
  }
}

async function handleAuthSuccess(payload, successMessage) {
  setSession(payload.token, payload.user);
  applyUser();
  showAppShell();
  await loadBootstrap(false);
  setBanner(successMessage);
}

dom.signupForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(dom.signupForm);
  setAuthBanner("Creating your developer workspace...");
  try {
    const payload = await apiPostJSON("/api/auth/signup", {
      name: formData.get("name"),
      email: formData.get("email"),
      password: formData.get("password"),
    }, false);
    dom.signupForm.reset();
    await handleAuthSuccess(payload, "Account created. Your OrchestraAI workspace is ready.");
  } catch (error) {
    setAuthBanner(error.message, true);
  }
});

dom.loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(dom.loginForm);
  setAuthBanner("Signing you in...");
  try {
    const payload = await apiPostJSON("/api/auth/login", {
      email: formData.get("email"),
      password: formData.get("password"),
    }, false);
    dom.loginForm.reset();
    await handleAuthSuccess(payload, "Welcome back. Your OrchestraAI workspace is loaded.");
  } catch (error) {
    setAuthBanner(error.message, true);
  }
});

dom.logoutButton.addEventListener("click", async () => {
  try {
    if (state.token) {
      await apiPostJSON("/api/auth/logout", {});
    }
  } catch {
    // Ignore logout network errors; local cleanup still matters.
  } finally {
    clearSession();
    showAuthShell("You have been logged out.");
  }
});

dom.navItems.forEach((item) => item.addEventListener("click", () => setActiveTab(item.dataset.tab)));
dom.quickTargets.forEach((button) => button.addEventListener("click", () => setActiveTab(button.dataset.tabTarget)));

dom.agentList.addEventListener("click", async (event) => {
  const item = event.target.closest("[data-agent-id]");
  if (!item) return;
  state.selectedAgentId = Number(item.dataset.agentId);
  await loadWorkspace(state.selectedAgentId);
  renderAgentLists(state.bootstrap?.agents || []);
});

dom.providerForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(dom.providerForm);
  dom.providerStatus.textContent = "Validating provider key...";
  try {
    const result = await apiPostJSON("/api/providers", {
      provider_type: formData.get("provider_type"),
      default_model: formData.get("default_model") || null,
      api_key: formData.get("api_key"),
    });
    await loadBootstrap(true);
    if (result.status === "invalid") {
      dom.providerStatus.textContent = result.last_error || "Invalid API key";
      setBanner(`Provider validation failed: ${result.last_error || "Invalid API key"}`, true);
    } else {
      dom.providerForm.reset();
      dom.providerStatus.textContent = "Provider validated and stored.";
      setBanner("Provider validated successfully.");
    }
  } catch (error) {
    dom.providerStatus.textContent = error.message;
    setBanner(`Provider validation failed: ${error.message}`, true);
  }
});

dom.agentForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(dom.agentForm);
  dom.agentStatusNote.textContent = "Creating agent...";
  try {
    const created = await apiPostJSON("/api/agents", {
      name: formData.get("name"),
      tagline: formData.get("tagline") || "",
      system_prompt: formData.get("system_prompt") || "",
      optimization_mode: formData.get("optimization_mode"),
      allow_web_search: formData.get("allow_web_search") === "on",
    });
    dom.agentForm.reset();
    dom.agentStatusNote.textContent = "Agent created successfully.";
    state.selectedAgentId = created.id;
    setBanner(`Agent "${created.name}" created.`);
    await loadBootstrap(true);
    setActiveTab("agents");
  } catch (error) {
    dom.agentStatusNote.textContent = error.message;
    setBanner(`Agent creation failed: ${error.message}`, true);
  }
});

dom.documentForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(dom.documentForm);
  await uploadKnowledgeFile(formData.get("file"), dom.documentStatus);
  dom.documentForm.reset();
});

dom.knowledgeSelectButton.addEventListener("click", () => dom.knowledgeFileInput.click());
dom.knowledgeDropZone.addEventListener("click", () => dom.knowledgeFileInput.click());
dom.knowledgeDropZone.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    dom.knowledgeFileInput.click();
  }
});

["dragenter", "dragover"].forEach((eventName) => {
  dom.knowledgeDropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dom.knowledgeDropZone.classList.add("is-dragging");
  });
});
["dragleave", "dragend", "drop"].forEach((eventName) => {
  dom.knowledgeDropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dom.knowledgeDropZone.classList.remove("is-dragging");
  });
});
dom.knowledgeDropZone.addEventListener("drop", async (event) => {
  const file = event.dataTransfer?.files?.[0];
  if (!file) return;
  const transfer = new DataTransfer();
  transfer.items.add(file);
  dom.knowledgeFileInput.files = transfer.files;
  await uploadKnowledgeFile(file, dom.knowledgeUploadStatus);
});
dom.knowledgeFileInput.addEventListener("change", () => {
  const file = dom.knowledgeFileInput.files?.[0];
  dom.knowledgeUploadStatus.textContent = file
    ? `${file.name} selected. Click upload to run the learning pipeline.`
    : "Select an agent first, then upload knowledge directly from this tab.";
});
dom.knowledgeUploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = dom.knowledgeFileInput.files?.[0];
  await uploadKnowledgeFile(file, dom.knowledgeUploadStatus);
  dom.knowledgeUploadForm.reset();
});

dom.chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.selectedAgentId) {
    setBanner("Select an agent before chatting.", true);
    return;
  }
  const formData = new FormData(dom.chatForm);
  const message = String(formData.get("message") || "").trim();
  if (!message) {
    setBanner("Enter a message before running the chat pipeline.", true);
    return;
  }
  dom.chatStatus.textContent = "Running runtime pipeline...";
  try {
    await apiPostJSON(`/api/agents/${state.selectedAgentId}/chat`, { message });
    dom.chatForm.reset();
    dom.chatStatus.textContent = "Runtime answer generated.";
    setBanner("Chat pipeline completed.");
    await loadBootstrap(true);
    setActiveTab("runtime");
  } catch (error) {
    dom.chatStatus.textContent = error.message;
    setBanner(`Chat pipeline failed: ${error.message}`, true);
  }
});

(async function init() {
  if (!state.token) {
    showAuthShell("Create an account or log in to start building your own OrchestraAI workspace.");
    return;
  }
  try {
    await loadBootstrap(false);
    showAppShell();
    setBanner("Backend connected. Runtime state loaded.");
  } catch (error) {
    clearSession();
    showAuthShell(error.message === "Authentication required." ? "Please log in again." : error.message, true);
  }
})();
