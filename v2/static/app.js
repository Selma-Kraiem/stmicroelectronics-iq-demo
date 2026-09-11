"use strict";

const DEFAULT_TASK_OBJECTIVE =
  "Assess the current automotive SiC power-module incident for synthetic lot CAT-26-0813-A, identify live external signals and operational exposure, then produce a cited response brief.";

function surfaceFromPath() {
  return window.location.pathname.endsWith("/tasks") ? "tasks" : "chat";
}

const state = {
  activeTab: surfaceFromPath(),
  status: {
    data: null,
    error: "",
    loading: true
  },
  chat: {
    loading: false,
    error: "",
    result: null
  },
  tasks: {
    history: [],
    historyLoading: true,
    historyError: "",
    activeRunId: "",
    detailLoading: false,
    detailError: "",
    run: null,
    result: null,
    teamsResponse: null,
    streamStatus: "Idle",
    stream: null
  }
};

const elements = {};

document.addEventListener("DOMContentLoaded", init);

function init() {
  captureElements();
  bindEvents();
  renderApp();
  void loadStatus();
  if (state.activeTab === "tasks") {
    void loadTaskHistory();
  }
}

function captureElements() {
  elements.statusNotice = document.getElementById("status-notice");
  elements.adapterStatuses = document.getElementById("adapter-statuses");
  elements.chatPanel = document.getElementById("panel-chat");
  elements.tasksPanel = document.getElementById("panel-tasks");
  elements.chatForm = document.getElementById("chat-form");
  elements.chatMessage = document.getElementById("chat-message");
  elements.chatSubmit = document.getElementById("chat-submit");
  elements.chatSubmitLabel = elements.chatSubmit.querySelector("span");
  elements.chatStatus = document.getElementById("chat-status");
  elements.chatResult = document.getElementById("chat-result");
  elements.taskForm = document.getElementById("task-form");
  elements.taskObjective = document.getElementById("task-objective");
  elements.taskSubmit = document.getElementById("task-submit");
  elements.taskDetail = document.getElementById("task-detail");
  elements.taskHistory = document.getElementById("task-history");
  elements.historyRefresh = document.getElementById("history-refresh");
  elements.taskStreamStatus = document.getElementById("task-stream-status");
  elements.announcer = document.getElementById("app-announcer");
  elements.tabs = Array.from(document.querySelectorAll("[data-tab]"));
}

function bindEvents() {
  document.addEventListener("click", handleFillButtonClick);
  elements.chatForm.addEventListener("submit", handleChatSubmit);
  elements.taskForm.addEventListener("submit", handleTaskSubmit);
  elements.historyRefresh.addEventListener("click", () => {
    void loadTaskHistory(true);
  });
  elements.taskHistory.addEventListener("click", handleHistorySelection);
  elements.taskDetail.addEventListener("click", handleTaskDetailClick);
}

function handleFillButtonClick(event) {
  const button = event.target.closest("[data-fill-target]");
  if (!button) {
    return;
  }

  const targetId = button.dataset.fillTarget;
  const value = button.dataset.fillValue || "";
  const target = document.getElementById(targetId);
  if (!target) {
    return;
  }

  target.value = value;
  target.focus();
}

function setActiveTab(tabName) {
  state.activeTab = tabName === "tasks" ? "tasks" : "chat";
  renderTabs();
}

async function handleChatSubmit(event) {
  event.preventDefault();
  const message = elements.chatMessage.value.trim();
  if (!message) {
    state.chat.error = "Enter a question before asking Commander.";
    renderChat();
    return;
  }

  state.chat.loading = true;
  state.chat.error = "";
  renderChat();

  try {
    const payload = await apiJson("/api/v2/chat", {
      method: "POST",
      body: JSON.stringify({ message })
    });
    state.chat.result = payload;
    announce("Commander returned a chat response.");
  } catch (error) {
    state.chat.error = describeError(error);
  } finally {
    state.chat.loading = false;
    renderChat();
  }
}

async function handleTaskSubmit(event) {
  event.preventDefault();
  const objective = elements.taskObjective.value.trim() || DEFAULT_TASK_OBJECTIVE;

  state.tasks.detailLoading = true;
  state.tasks.detailError = "";
  state.tasks.result = null;
  state.tasks.teamsResponse = null;
  state.tasks.streamStatus = "Starting assessment...";
  closeTaskStream();
  renderTasks();

  try {
    const summary = await apiJson("/api/v2/tasks", {
      method: "POST",
      body: JSON.stringify({ objective })
    });
    state.tasks.activeRunId = summary.id;
    state.tasks.run = { ...summary, events: [] };
    upsertHistory(summary);
    announce("Commander assessment started.");
    renderTasks();
    openTaskStream(summary.id);
    void loadTaskHistory();
  } catch (error) {
    state.tasks.detailError = describeError(error);
    state.tasks.streamStatus = "Stream unavailable";
  } finally {
    state.tasks.detailLoading = false;
    renderTasks();
  }
}

function handleHistorySelection(event) {
  const button = event.target.closest("[data-run-id]");
  if (!button) {
    return;
  }

  const runId = button.dataset.runId || "";
  if (!runId) {
    return;
  }

  void selectRun(runId);
}

function handleTaskDetailClick(event) {
  const previewButton = event.target.closest("[data-action='preview-teams']");
  if (!previewButton) {
    return;
  }

  const runId = previewButton.dataset.runId || state.tasks.activeRunId;
  const checkbox = document.getElementById("teams-opt-in");
  const explicitOptIn = checkbox ? checkbox.checked : false;
  void requestTeamsPreview(runId, explicitOptIn);
}

async function loadStatus() {
  state.status.loading = true;
  state.status.error = "";
  renderStatus();

  try {
    state.status.data = await apiJson("/api/v2/status");
  } catch (error) {
    state.status.error = describeError(error);
  } finally {
    state.status.loading = false;
    renderStatus();
  }
}

async function loadTaskHistory(keepSelection) {
  state.tasks.historyLoading = true;
  state.tasks.historyError = "";
  renderTasks();

  try {
    const payload = await apiJson("/api/v2/tasks");
    state.tasks.history = Array.isArray(payload.items) ? payload.items : [];

    if (!keepSelection && !state.tasks.activeRunId && state.tasks.history.length > 0) {
      await selectRun(state.tasks.history[0].id, { keepTab: true });
      return;
    }
  } catch (error) {
    state.tasks.historyError = describeError(error);
  } finally {
    state.tasks.historyLoading = false;
    renderTasks();
  }
}

async function selectRun(runId, options = {}) {
  const keepTab = options.keepTab !== false;
  closeTaskStream();
  state.tasks.activeRunId = runId;
  state.tasks.detailLoading = true;
  state.tasks.detailError = "";
  state.tasks.teamsResponse = null;
  state.tasks.result = null;
  if (!keepTab) {
    setActiveTab("tasks");
  }
  renderTasks();

  try {
    const run = await apiJson(`/api/v2/tasks/${encodeURIComponent(runId)}`);
    state.tasks.run = run;
    upsertHistory(run);

    if (run.status === "running") {
      state.tasks.streamStatus = "Streaming live events...";
      openTaskStream(runId);
    } else {
      state.tasks.streamStatus = "Run complete";
      closeTaskStream();
      await loadTaskResult(runId);
    }
    announce(`Loaded task ${runId}.`);
  } catch (error) {
    state.tasks.detailError = describeError(error);
    state.tasks.streamStatus = "Run unavailable";
    closeTaskStream();
  } finally {
    state.tasks.detailLoading = false;
    renderTasks();
  }
}

async function loadTaskResult(runId) {
  try {
    const payload = await apiJson(`/api/v2/tasks/${encodeURIComponent(runId)}/result`);
    if (state.tasks.activeRunId === runId) {
      state.tasks.result = payload;
    }
  } catch (error) {
    if (error && error.status === 409) {
      return;
    }
    if (state.tasks.activeRunId === runId) {
      state.tasks.detailError = describeError(error);
    }
  }
}

async function requestTeamsPreview(runId, explicitOptIn) {
  if (!runId) {
    return;
  }

  state.tasks.streamStatus = "Checking Teams handoff status...";
  renderTasks();

  try {
    state.tasks.teamsResponse = await apiJson(
      `/api/v2/tasks/${encodeURIComponent(runId)}/teams`,
      {
        method: "POST",
        body: JSON.stringify({ explicit_opt_in: explicitOptIn })
      }
    );
    announce("Teams handoff status checked.");
  } catch (error) {
    state.tasks.detailError = describeError(error);
  } finally {
    state.tasks.streamStatus = state.tasks.run && state.tasks.run.status === "running"
      ? "Streaming live events..."
      : "Run complete";
    renderTasks();
  }
}

function openTaskStream(runId) {
  closeTaskStream();

  if (!window.EventSource) {
    state.tasks.streamStatus = "Live events are not supported in this browser.";
    renderTasks();
    return;
  }

  const stream = new EventSource(`/api/v2/tasks/${encodeURIComponent(runId)}/events`);
  state.tasks.stream = stream;
  state.tasks.streamStatus = "Streaming live events...";
  renderTasks();

  stream.onmessage = (event) => {
    const payload = parseJson(event.data);
    if (!payload) {
      return;
    }
    if (state.tasks.activeRunId !== runId) {
      return;
    }
    mergeEventIntoRun(payload);
    announce(`${payload.agent} update: ${payload.stage}`);
    renderTasks();
  };

  stream.addEventListener("done", async (event) => {
    const payload = parseJson(event.data);
    if (state.tasks.activeRunId !== runId) {
      return;
    }
    if (payload) {
      state.tasks.run = {
        ...(state.tasks.run || {}),
        ...payload,
        events: state.tasks.run && Array.isArray(state.tasks.run.events) ? state.tasks.run.events : []
      };
      upsertHistory(payload);
    }
    state.tasks.streamStatus = "Run complete";
    closeTaskStream();
    await Promise.all([loadTaskResult(runId), loadTaskHistory(true)]);
    renderTasks();
  });

  stream.onerror = () => {
    if (state.tasks.activeRunId !== runId) {
      return;
    }
    state.tasks.streamStatus = state.tasks.run && state.tasks.run.status === "running"
      ? "Live stream interrupted. Showing the last received event."
      : "Run complete";
    closeTaskStream();
    void refreshSelectedRun(runId);
  };
}

async function refreshSelectedRun(runId) {
  try {
    const run = await apiJson(`/api/v2/tasks/${encodeURIComponent(runId)}`);
    if (state.tasks.activeRunId !== runId) {
      return;
    }
    state.tasks.run = run;
    upsertHistory(run);
    if (run.status !== "running") {
      await loadTaskResult(runId);
      state.tasks.streamStatus = "Run complete";
    }
    renderTasks();
  } catch (error) {
    if (state.tasks.activeRunId === runId) {
      state.tasks.detailError = describeError(error);
      renderTasks();
    }
  }
}

function closeTaskStream() {
  if (state.tasks.stream) {
    state.tasks.stream.close();
    state.tasks.stream = null;
  }
}

function mergeEventIntoRun(eventPayload) {
  const currentRun = state.tasks.run || {
    id: eventPayload.run_id,
    incident_id: eventPayload.incident_id,
    objective: "",
    status: eventPayload.state === "running" ? "running" : eventPayload.state,
    progress: eventPayload.progress,
    stage: eventPayload.stage,
    events: []
  };

  const events = Array.isArray(currentRun.events) ? currentRun.events.slice() : [];
  const newKey = eventKey(eventPayload);
  const exists = events.some((item) => eventKey(item) === newKey);
  if (!exists) {
    events.push(eventPayload);
  }

  state.tasks.run = {
    ...currentRun,
    id: currentRun.id || eventPayload.run_id,
    incident_id: currentRun.incident_id || eventPayload.incident_id,
    status:
      eventPayload.state === "running"
        ? currentRun.status || "running"
        : eventPayload.state || currentRun.status,
    progress: eventPayload.progress,
    stage: eventPayload.stage,
    events
  };
}

function eventKey(item) {
  return [
    item.run_id || "",
    item.agent || "",
    item.state || "",
    item.progress || "",
    item.stage || "",
    item.task_id || "",
    item.timestamp || ""
  ].join("|");
}

function upsertHistory(summary) {
  if (!summary || !summary.id) {
    return;
  }
  const next = state.tasks.history.filter((item) => item.id !== summary.id);
  next.unshift({
    id: summary.id,
    incident_id: summary.incident_id,
    objective: summary.objective,
    status: summary.status,
    progress: summary.progress,
    stage: summary.stage,
    created_at: summary.created_at
  });
  state.tasks.history = next;
}

async function apiJson(url, options = {}) {
  const requestOptions = {
    method: options.method || "GET",
    headers: {
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {})
    },
    body: options.body
  };

  const response = await fetch(url, requestOptions);
  const text = await response.text();
  const payload = parseJson(text) || {};

  if (!response.ok) {
    const message =
      payload.detail ||
      payload.reason ||
      payload.message ||
      `Request failed with status ${response.status}.`;
    const error = new Error(message);
    error.status = response.status;
    error.data = payload;
    throw error;
  }

  return payload;
}

function renderApp() {
  renderTabs();
  renderStatus();
  renderChat();
  renderTasks();
}

function renderTabs() {
  elements.tabs.forEach((button) => {
    const isActive = button.dataset.tab === state.activeTab;
    button.classList.toggle("is-active", isActive);
    if (isActive) {
      button.setAttribute("aria-current", "page");
    } else {
      button.removeAttribute("aria-current");
    }
  });
  elements.chatPanel.hidden = state.activeTab !== "chat";
  elements.tasksPanel.hidden = state.activeTab !== "tasks";
}

function renderStatus() {
  if (state.status.loading) {
    elements.statusNotice.textContent = "Loading adapter status...";
    elements.adapterStatuses.innerHTML = renderEmptyState(
      "Loading status",
      "Checking the current V2 adapter contracts."
    );
    return;
  }

  if (state.status.error) {
    elements.statusNotice.textContent = "Adapter status could not be loaded.";
    elements.adapterStatuses.innerHTML = renderErrorCard(state.status.error);
    return;
  }

  const data = state.status.data || { adapters: [], notice: "" };
  elements.statusNotice.textContent =
    data.notice || "Adapter status is available for the isolated V2 presenter.";
  elements.adapterStatuses.innerHTML = (data.adapters || [])
    .map((adapter) => {
      return `
        <article class="meta-card">
          <div class="card-row">
            <h3>${escapeHtml(adapter.name || "Adapter")}</h3>
            <span class="badge ${statusClass(adapter.state)}">${escapeHtml(
              titleCase(adapter.state || "unknown")
            )}</span>
          </div>
          <p class="card-copy">${escapeHtml(adapter.reason || "No reason provided.")}</p>
          <div class="meta-badges">
            <span class="badge badge-soft">Mode: ${escapeHtml(adapter.mode || "unknown")}</span>
          </div>
        </article>
      `;
    })
    .join("");
}

function renderChat() {
  elements.chatSubmit.disabled = state.chat.loading;
  elements.chatSubmitLabel.textContent = state.chat.loading ? "Working..." : "Send";
  elements.chatStatus.textContent = state.chat.loading
    ? "Commander is routing the question."
    : state.chat.error;

  if (state.chat.loading && !state.chat.result) {
    elements.chatResult.innerHTML = `
      <article class="chat-message assistant-message is-loading">
        <span class="assistant-avatar" aria-hidden="true">AI</span>
        <div class="message-body">
          <strong>Commander</strong>
          <p>Routing to the right specialist and gathering cited evidence...</p>
          <span class="typing-indicator" aria-hidden="true"><i></i><i></i><i></i></span>
        </div>
      </article>
    `;
    return;
  }

  if (state.chat.error) {
    elements.chatResult.innerHTML = renderErrorCard(state.chat.error);
    return;
  }

  if (!state.chat.result) {
    elements.chatResult.innerHTML = "";
    return;
  }

  const result = state.chat.result;
  const routeBadges = (result.route || [])
    .map((agent) => renderRouteBadge(agent))
    .join("");

  elements.chatResult.innerHTML = `
    <article class="chat-message assistant-message">
      <span class="assistant-avatar" aria-hidden="true">AI</span>
      <div class="message-body">
        <div class="message-heading">
          <strong>Commander</strong>
          <span class="badge ${statusClass(result.complete ? "completed" : "partial")}">
            ${result.complete ? "Evidence complete" : "Partial evidence"}
          </span>
        </div>
        <p class="chat-answer">${escapeHtml(result.answer || "No answer returned.")}</p>
        <div class="route-badges">
          ${routeBadges || '<span class="badge badge-soft">Route unavailable</span>'}
        </div>
        <div class="message-meta">
          <span>Run ${escapeHtml(result.run_id || "N/A")}</span>
          <span>${escapeHtml(result.incident_id || "N/A")}</span>
        </div>
      </div>
    </article>
    <div class="chat-evidence">
      ${renderCitationSection(result.citations || [])}
      <details class="agent-details">
        <summary>View agent activity and detailed evidence</summary>
        ${renderSpecialistSection(result.specialists || [], { includeStructured: true })}
      </details>
    </div>
  `;
}

function renderTasks() {
  elements.taskSubmit.disabled = state.tasks.detailLoading;
  elements.taskSubmit.textContent = state.tasks.detailLoading
    ? "Starting..."
    : "Start assessment";
  elements.taskStreamStatus.textContent = state.tasks.streamStatus;
  renderTaskHistory();
  renderTaskDetail();
}

function renderTaskHistory() {
  if (state.tasks.historyLoading && state.tasks.history.length === 0) {
    elements.taskHistory.innerHTML = renderEmptyState(
      "Loading history",
      "Checking existing Commander assessments."
    );
    return;
  }

  if (state.tasks.historyError && state.tasks.history.length === 0) {
    elements.taskHistory.innerHTML = renderErrorCard(state.tasks.historyError);
    return;
  }

  if (state.tasks.history.length === 0) {
    elements.taskHistory.innerHTML = renderEmptyState(
      "No assessments yet",
      "Start a task to stream fan-out events and see the final cited brief here."
    );
    return;
  }

  elements.taskHistory.innerHTML = `
    ${state.tasks.historyError ? renderInlineNote(state.tasks.historyError, "warning") : ""}
    <div class="history-list">
      ${state.tasks.history
        .map((item) => {
          const selected = item.id === state.tasks.activeRunId;
          return `
            <button
              class="history-item ${selected ? "is-selected" : ""}"
              type="button"
              data-run-id="${escapeHtml(item.id)}"
            >
              <div class="history-row">
                <h3>${escapeHtml(item.objective || "Untitled assessment")}</h3>
                <span class="badge ${statusClass(item.status)}">${escapeHtml(
                  titleCase(item.status || "unknown")
                )}</span>
              </div>
              <p class="card-copy">${escapeHtml(item.stage || "No stage yet.")}</p>
              <div class="meta-badges">
                <span class="badge badge-soft">Run: ${escapeHtml(item.id || "N/A")}</span>
                <span class="badge badge-soft">Incident: ${escapeHtml(
                  item.incident_id || "N/A"
                )}</span>
                <span class="badge badge-soft">${escapeHtml(
                  `${Number(item.progress || 0)}% progress`
                )}</span>
              </div>
              <p class="fine-print">Created ${escapeHtml(formatDateTime(item.created_at))}</p>
            </button>
          `;
        })
        .join("")}
    </div>
  `;
}

function renderTaskDetail() {
  if (state.tasks.detailLoading && !state.tasks.run) {
    elements.taskDetail.innerHTML = renderEmptyState(
      "Starting assessment",
      "Commander is preparing the run."
    );
    return;
  }

  if (state.tasks.detailError && !state.tasks.run) {
    elements.taskDetail.innerHTML = renderErrorCard(state.tasks.detailError);
    return;
  }

  if (!state.tasks.run) {
    elements.taskDetail.innerHTML = renderEmptyState(
      "No run selected",
      "Start a new assessment or open a recent run from the history panel."
    );
    return;
  }

  const run = state.tasks.run;
  const result = state.tasks.result;
  const flow = deriveFlowState(run, result);
  const events = Array.isArray(run.events) ? run.events.slice() : [];
  const detailError = state.tasks.detailError ? renderInlineNote(state.tasks.detailError, "warning") : "";

  elements.taskDetail.innerHTML = `
    ${detailError}
    <div class="task-detail-grid">
      <div class="task-primary">
        <article class="run-overview">
          <div class="run-title-row">
            <div>
              <p class="eyebrow">Commander task</p>
              <h3>${escapeHtml(run.objective || "No objective provided.")}</h3>
            </div>
            <span class="badge ${statusClass(run.status)}">${escapeHtml(
              titleCase(run.status || "unknown")
            )}</span>
          </div>
          <div class="progress-track" aria-label="${escapeHtml(`${Number(run.progress || 0)}% complete`)}">
            <span style="width: ${Math.min(100, Math.max(0, Number(run.progress || 0)))}%"></span>
          </div>
          <div class="run-meta">
            <span>${escapeHtml(run.stage || "Unknown stage")}</span>
            <span>${escapeHtml(`${Number(run.progress || 0)}%`)}</span>
            <span class="mono">${escapeHtml(run.id || "N/A")}</span>
          </div>
        </article>

        <section class="tasks-flow">
          <div class="section-header">
            <p class="eyebrow">Orchestration</p>
            <h3>Commander fan-out and fan-in</h3>
          </div>
          <div class="flow-grid">
            ${renderFlowNode(flow.commander)}
            <div class="branch-column">
              ${renderFlowNode(flow.market)}
              ${renderFlowNode(flow.quality)}
            </div>
            ${renderFlowNode(flow.synthesis)}
          </div>
        </section>

        ${result ? renderTaskResult(result) : renderPendingResult(run)}
      </div>

      <aside class="task-activity">
        <div class="activity-heading">
          <div>
            <p class="eyebrow">Live execution</p>
            <h3>Agents and tools</h3>
          </div>
          <span class="activity-count">${deriveExecutionActivities(run, result, events).length}</span>
        </div>
        ${renderExecutionTimeline(run, result, events)}
      </aside>
    </div>
  `;
}

function renderTaskResult(result) {
  return `
    <section>
      <div class="section-header">
        <p class="section-kicker">Cited fan-in brief</p>
        <h3>Assessment output</h3>
      </div>
      <article class="summary-card">
        <div class="card-row">
          <h3>Commander synthesis</h3>
          <span class="badge ${statusClass(result.complete ? "completed" : "partial")}">
            ${result.complete ? "Complete" : "Partial"}
          </span>
        </div>
        <dl class="data-pairs">
          <div>
            <dt>Run ID</dt>
            <dd>${escapeHtml(result.run_id || "N/A")}</dd>
          </div>
          <div>
            <dt>Incident ID</dt>
            <dd>${escapeHtml(result.incident_id || "N/A")}</dd>
          </div>
          <div>
            <dt>Result status</dt>
            <dd>${escapeHtml(titleCase(result.status || "unknown"))}</dd>
          </div>
          <div>
            <dt>Data notice</dt>
            <dd>${escapeHtml(result.data_notice || "No data notice.")}</dd>
          </div>
        </dl>
      </article>
      <div class="cards-grid three-up">
        ${renderChecklist("Facts", result.facts, "No facts were returned.")}
        ${renderChecklist("Hypotheses", result.hypotheses, "No hypotheses were returned.")}
        ${renderChecklist(
          "Missing information",
          result.missing_information,
          "No missing information was returned."
        )}
      </div>
    </section>

    ${renderExposureSection(result.customer_impact || {})}
    ${renderActionsSection(result.recommended_actions || [])}
    ${renderCitationSection(result.citations || [])}
    ${renderSpecialistSection(result.specialists || [], { includeStructured: true })}
    ${renderTeamsSection(result.teams_update || {})}
  `;
}

function renderPendingResult(run) {
  if (run.status === "running") {
    return renderEmptyState(
      "Awaiting synthesis",
      "Commander will display the cited brief after both specialists return and fan-in synthesis is complete."
    );
  }

  return renderEmptyState(
    "Result not available",
    "The selected run does not have a completed result yet."
  );
}

function renderFlowNode(node) {
  return `
    <article class="flow-node ${escapeHtml(node.kind)}">
      <div>
        <div class="card-row">
          <h3>${escapeHtml(node.title)}</h3>
          <span class="badge ${statusClass(node.status)}">${escapeHtml(
            titleCase(node.status)
          )}</span>
        </div>
        <p class="card-copy">${escapeHtml(node.description)}</p>
      </div>
      <div class="meta-badges">
        ${node.badges.map((badge) => `<span class="badge badge-soft">${escapeHtml(badge)}</span>`).join("")}
      </div>
    </article>
  `;
}

function renderExecutionTimeline(run, result, events) {
    const activities = deriveExecutionActivities(run, result, events);
    const toolCount = activities.filter((item) => item.type === "TOOL").length;
    const a2aCount = activities.filter((item) => item.type === "A2A").length;

    return `
      <div class="execution-summary">
        <span><strong>${activities.length}</strong> execution steps</span>
        <span><strong>${toolCount}</strong> tool calls</span>
        <span><strong>${a2aCount}</strong> A2A delegations</span>
      </div>
      <div class="execution-timeline">
        ${activities
          .map((item) => {
            return `
              <article class="execution-item ${escapeHtml(item.kind)}">
                <span class="execution-dot ${statusClass(item.status)}" aria-hidden="true"></span>
                <div class="execution-content">
                  <div class="execution-row">
                    <div>
                      <strong>${escapeHtml(item.title)}</strong>
                      <p>${escapeHtml(item.description)}</p>
                    </div>
                    <div class="execution-state">
                      <span class="execution-type">${escapeHtml(item.type)}</span>
                      <span class="badge ${statusClass(item.status)}">${escapeHtml(
                        titleCase(item.status)
                      )}</span>
                    </div>
                  </div>
                  <div class="meta-badges">
                    <span class="badge ${routeClass(item.agent)}">${escapeHtml(
                      titleCase(item.agent)
                    )}</span>
                    ${item.source ? `<span class="badge badge-soft">${escapeHtml(item.source)}</span>` : ""}
                    ${item.taskId ? `<span class="badge badge-soft">Task: ${escapeHtml(item.taskId)}</span>` : ""}
                    ${item.timestamp ? `<span class="timeline-meta">${escapeHtml(
                      formatDateTime(item.timestamp)
                    )}</span>` : ""}
                  </div>
                </div>
              </article>
            `;
          })
          .join("")}
      </div>
    `;
}

function deriveExecutionActivities(run, result, events) {
    const progress = Number(run.progress || 0);
    const adapters = Array.isArray(state.status.data && state.status.data.adapters)
      ? state.status.data.adapters
      : [];
    const adapterMode = (name) => {
      const adapter = adapters.find((item) => item.name === name);
      return adapter ? adapter.mode : "";
    };
    const specialists = Array.isArray(result && result.specialists) ? result.specialists : [];
    const market = specialists.find((item) => item.agent === "market");
    const quality = specialists.find((item) => item.agent === "quality");
    const marketMode = market && market.structured_data ? market.structured_data.mode : "";
    const qualityData = quality && quality.structured_data ? quality.structured_data : {};
    const qualityMode = qualityData.mode || "";
    const toolSequence = Array.isArray(qualityData.tool_sequence) ? qualityData.tool_sequence : [];
    const marketCitations = Array.isArray(market && market.citations) ? market.citations : [];
    const qualityCitations = Array.isArray(quality && quality.citations) ? quality.citations : [];
    const firstEvent = events[0] || {};
    const lastEvent = events[events.length - 1] || {};
    const specialistStatus = (specialist) => {
      if (specialist) {
        return specialist.status || "failed";
      }
      return progress >= 22 ? "running" : "queued";
    };
    const evidenceStatus = (specialist, predicate) => {
      if (!specialist) {
        return progress >= 22 ? "running" : "queued";
      }
      if (specialist.status !== "completed") {
        return specialist.status || "failed";
      }
      return predicate ? "completed" : "partial";
    };
    const marketWebUsed = marketCitations.some((item) =>
      String(item.source_type || "").includes("Web Knowledge Source")
    );
    const foundryIqUsed = qualityCitations.some((item) =>
      String(item.source_type || "").toLowerCase().includes("foundry iq")
    );
    const telemetryUsed =
      toolSequence.includes("Manufacturing Telemetry API") ||
      qualityCitations.some((item) => item.source_type === "Manufacturing Telemetry API");
    const exposureUsed =
      toolSequence.includes("Customer Exposure API") ||
      qualityCitations.some((item) => item.source_type === "Customer Exposure API");
    const marketIsLive =
      adapterMode("Market A2A agent") === "live-web-knowledge-source" ||
      marketMode === "live-web-knowledge-source" ||
      marketWebUsed;
    const qualityIsLive =
      adapterMode("Quality A2A agent") === "live-foundry-iq-and-tool-search" ||
      qualityMode === "live-foundry-iq-and-structured-apis" ||
      foundryIqUsed ||
      telemetryUsed ||
      exposureUsed;
    const a2aTask = (specialist) => (specialist && specialist.task_id ? specialist.task_id : "");

    return [
      {
        title: "Commander accepted the assessment",
        description: "Created the shared incident context and owns correlation, timeouts, and synthesis.",
        type: "AGENT",
        kind: "commander",
        agent: "commander",
        status: progress >= 2 ? "completed" : "running",
        source: run.incident_id || "",
        timestamp: firstEvent.timestamp || run.created_at || ""
      },
      {
        title: "run_parallel_assessment",
        description: "Commander initiated concurrent fan-out to both specialist agents.",
        type: "TOOL",
        kind: "commander",
        agent: "commander",
        status: progress >= 22 ? "completed" : progress >= 12 ? "running" : "queued",
        source: "Concurrent fan-out"
      },
      {
        title: "A2A → Market Agent",
        description: "Delegated sanitized public market, regulatory, weather, logistics, and supply research.",
        type: "A2A",
        kind: "market",
        agent: "market",
        status: specialistStatus(market),
        source: "Foundry A2A v1.0",
        taskId: a2aTask(market)
      },
      {
        title: marketIsLive
          ? "Web Knowledge Source (Web IQ fallback)"
          : "Cached public-market adapter",
        description: marketIsLive
          ? "Retrieved current public evidence with dated URLs and sanitized queries."
          : "Used clearly labelled cached public demo context; no live web call is claimed.",
        type: marketIsLive ? "TOOL" : "ADAPTER",
        kind: "market",
        agent: "market",
        status: evidenceStatus(market, marketIsLive ? marketWebUsed : Boolean(market)),
        source: marketIsLive ? "knowledge_base_retrieve" : "Demo fallback"
      },
      {
        title: "A2A → Quality Agent",
        description: "Delegated procedure, manufacturing telemetry, lot, inventory, and customer exposure analysis.",
        type: "A2A",
        kind: "quality",
        agent: "quality",
        status: specialistStatus(quality),
        source: "Foundry A2A v1.0",
        taskId: a2aTask(quality)
      },
      {
        title: qualityIsLive ? "Foundry IQ knowledge" : "Synthetic procedure adapter",
        description: qualityIsLive
          ? "Retrieved public ST documents and synthetic containment procedures as native knowledge."
          : "Resolved the deterministic local containment procedure without claiming live Foundry IQ.",
        type: qualityIsLive ? "TOOL" : "ADAPTER",
        kind: "quality",
        agent: "quality",
        status: evidenceStatus(quality, qualityIsLive ? foundryIqUsed : Boolean(quality)),
        source: qualityIsLive ? "knowledge_base_retrieve" : "Demo fallback"
      },
      {
        title: qualityIsLive ? "Tool Search → Manufacturing Telemetry API" : "Manufacturing Telemetry API",
        description: "Retrieved synthetic measurements, equipment, anomaly thresholds, and affected-lot evidence.",
        type: qualityIsLive ? "TOOL" : "ADAPTER",
        kind: "quality",
        agent: "quality",
        status: evidenceStatus(quality, telemetryUsed),
        source: qualityIsLive ? "tool_search · call_tool · getLotTelemetry" : "Local structured API"
      },
      {
        title: qualityIsLive ? "Tool Search → Customer Exposure API" : "Customer Exposure API",
        description: "Retrieved fictional orders, customers, inventory, coverage gap, and reallocation evidence.",
        type: qualityIsLive ? "TOOL" : "ADAPTER",
        kind: "quality",
        agent: "quality",
        status: evidenceStatus(quality, exposureUsed),
        source: qualityIsLive ? "tool_search · call_tool · getLotExposure" : "Local structured API"
      },
      {
        title: "Commander cited fan-in synthesis",
        description: "Separated facts, hypotheses, and missing evidence before generating the customer-impact brief.",
        type: "AGENT",
        kind: "commander",
        agent: "commander",
        status: run.status === "running" ? (progress >= 82 ? "running" : "queued") : run.status,
        source: "No Teams side effect",
        timestamp: lastEvent.timestamp || ""
      }
    ];
}

function renderSpecialistSection(specialists, options = {}) {
  if (!Array.isArray(specialists) || specialists.length === 0) {
    return renderEmptyState(
      "No specialist details",
      "Specialist evidence will appear once Commander has routed the request."
    );
  }

  return `
    <section>
      <div class="section-header">
        <p class="section-kicker">Specialist evidence</p>
        <h3>Market and Quality detail</h3>
      </div>
      <div class="specialist-grid">
        ${specialists.map((item) => renderSpecialistCard(item, options)).join("")}
      </div>
    </section>
  `;
}

function renderSpecialistCard(item, options) {
  const structuredSections = options.includeStructured
    ? renderStructuredDetails(item.structured_data || {})
    : "";

  return `
    <article class="specialist-card ${escapeHtml(item.agent || "specialist")}">
      <div class="card-row">
        <h3>${escapeHtml(titleCase(item.agent || "specialist"))}</h3>
        <span class="badge ${statusClass(item.status)}">${escapeHtml(
          titleCase(item.status || "unknown")
        )}</span>
      </div>
      <div class="specialist-body">
        <p>${escapeHtml(item.summary || "No summary returned.")}</p>
        <div class="meta-badges">
          <span class="badge ${routeClass(item.agent)}">${escapeHtml(
            titleCase(item.agent || "specialist")
          )}</span>
          <span class="badge badge-soft">Task: ${escapeHtml(item.task_id || "N/A")}</span>
        </div>
        ${renderChecklist("Facts", item.facts, "No facts returned.")}
        ${renderChecklist("Hypotheses", item.hypotheses, "No hypotheses returned.")}
        ${renderChecklist(
          "Missing information",
          item.missing_information,
          "No missing information returned."
        )}
        ${structuredSections}
        ${renderCompactCitationList(item.citations || [])}
        ${item.error ? `<p class="fine-print">Error: ${escapeHtml(item.error)}</p>` : ""}
      </div>
    </article>
  `;
}

function renderStructuredDetails(data) {
  if (!data || typeof data !== "object") {
    return "";
  }

  const metrics = [];
  if (data.mode) {
    metrics.push(["Mode", data.mode]);
  }
  if (data.lot_id) {
    metrics.push(["Lot", data.lot_id]);
  }
  if (data.telemetry && typeof data.telemetry === "object") {
    metrics.push(["Anomalies", data.telemetry.anomaly_count]);
    metrics.push(["Classification", data.telemetry.data_classification]);
  }
  if (data.exposure && typeof data.exposure === "object") {
    metrics.push(["Affected units", data.exposure.affected_units]);
    metrics.push(["Customers", data.exposure.affected_customer_count]);
    metrics.push(["Reallocation", data.exposure.available_reallocation]);
  }

  if (metrics.length === 0) {
    return "";
  }

  return `
    <section class="meta-card">
      <h3>Structured detail</h3>
      <dl class="data-pairs">
        ${metrics
          .map(([label, value]) => {
            return `
              <div>
                <dt>${escapeHtml(String(label))}</dt>
                <dd>${escapeHtml(String(value))}</dd>
              </div>
            `;
          })
          .join("")}
      </dl>
    </section>
  `;
}

function renderCompactCitationList(citations) {
  if (!Array.isArray(citations) || citations.length === 0) {
    return renderInlineNote("No citations returned.", "warning");
  }

  return `
    <section class="meta-card">
      <h3>Citations</h3>
      <div class="citation-grid">
        ${citations.map((citation) => renderCitationCard(citation)).join("")}
      </div>
    </section>
  `;
}

function renderCitationSection(citations) {
  if (!Array.isArray(citations) || citations.length === 0) {
    return renderEmptyState(
      "No citations",
      "Citations will appear when evidence is returned by the backend."
    );
  }

  return `
    <section>
      <div class="section-header">
        <p class="section-kicker">Evidence trail</p>
        <h3>Citations and source badges</h3>
      </div>
      <div class="citation-grid">
        ${citations.map((citation) => renderCitationCard(citation)).join("")}
      </div>
    </section>
  `;
}

function renderCitationCard(citation) {
  const url = citation.url && /^https?:\/\//i.test(citation.url)
    ? `<a href="${escapeHtml(citation.url)}" target="_blank" rel="noreferrer">Open source</a>`
    : "";

  return `
    <article class="citation-card">
      <div class="card-row">
        <h3>${escapeHtml(citation.title || "Citation")}</h3>
        <div class="stack-inline">
          <span class="badge ${citation.synthetic ? "badge-synthetic" : "badge-public"}">
            ${escapeHtml(citation.badge || "Source")}
          </span>
        </div>
      </div>
      <p>${escapeHtml(citation.excerpt || "No excerpt returned.")}</p>
      <div class="meta-badges">
        <span class="badge badge-soft">ID: ${escapeHtml(citation.id || "N/A")}</span>
        <span class="badge badge-soft">${escapeHtml(citation.source_type || "Unknown source")}</span>
      </div>
      ${url ? `<p class="fine-print">${url}</p>` : ""}
    </article>
  `;
}

function renderExposureSection(exposure) {
  const lot = exposure.lot || {};
  const orders = Array.isArray(exposure.affected_orders) ? exposure.affected_orders : [];
  const inventory = Array.isArray(exposure.inventory) ? exposure.inventory : [];

  return `
    <section>
      <div class="section-header">
        <p class="section-kicker">Customer exposure</p>
        <h3>Operational impact</h3>
      </div>
      <div class="metric-grid">
        <article class="meta-card">
          <h3>Affected units</h3>
          <p>${escapeHtml(String(exposure.affected_units ?? "0"))}</p>
        </article>
        <article class="meta-card">
          <h3>Affected customers</h3>
          <p>${escapeHtml(String(exposure.affected_customer_count ?? "0"))}</p>
        </article>
        <article class="meta-card">
          <h3>Available reallocation</h3>
          <p>${escapeHtml(String(exposure.available_reallocation ?? "0"))}</p>
        </article>
      </div>

      <div class="detail-grid">
        <article class="meta-card">
          <h3>Lot snapshot</h3>
          <dl class="data-pairs">
            <div>
              <dt>Lot ID</dt>
              <dd>${escapeHtml(lot.id || "N/A")}</dd>
            </div>
            <div>
              <dt>Status</dt>
              <dd>${escapeHtml(lot.status || "N/A")}</dd>
            </div>
            <div>
              <dt>Product ID</dt>
              <dd>${escapeHtml(lot.product_id || "N/A")}</dd>
            </div>
            <div>
              <dt>Coverage gap</dt>
              <dd>${escapeHtml(String(exposure.coverage_gap ?? "0"))}</dd>
            </div>
          </dl>
        </article>
        <article class="meta-card">
          <h3>Knowledge path</h3>
          <ul class="plain-list">
            ${(exposure.knowledge_path || [])
              .map((item) => `<li>${escapeHtml(item)}</li>`)
              .join("") || "<li>No knowledge path returned.</li>"}
          </ul>
          <p class="fine-print">
            Classification: ${escapeHtml(exposure.data_classification || "N/A")} | Seed:
            ${escapeHtml(String(exposure.seed ?? "N/A"))}
          </p>
        </article>
      </div>

      <div class="orders-grid">
        <div class="table-wrap">
          <table>
            <caption class="sr-only">Affected orders</caption>
            <thead>
              <tr>
                <th scope="col">Order</th>
                <th scope="col">Customer</th>
                <th scope="col">Quantity</th>
                <th scope="col">Lot</th>
              </tr>
            </thead>
            <tbody>
              ${
                orders.length
                  ? orders
                      .map((order) => {
                        return `
                          <tr>
                            <td>${escapeHtml(order.id || "N/A")}</td>
                            <td>${escapeHtml(order.customer || order.customer_id || "N/A")}</td>
                            <td>${escapeHtml(String(order.quantity ?? "0"))}</td>
                            <td>${escapeHtml(order.lot_id || "N/A")}</td>
                          </tr>
                        `;
                      })
                      .join("")
                  : `
                    <tr>
                      <td colspan="4">No affected orders returned.</td>
                    </tr>
                  `
              }
            </tbody>
          </table>
        </div>

        <div class="table-wrap">
          <table>
            <caption class="sr-only">Inventory overview</caption>
            <thead>
              <tr>
                <th scope="col">Site</th>
                <th scope="col">Product</th>
                <th scope="col">Available</th>
                <th scope="col">Allocated</th>
              </tr>
            </thead>
            <tbody>
              ${
                inventory.length
                  ? inventory
                      .map((item) => {
                        return `
                          <tr>
                            <td>${escapeHtml(item.site || "N/A")}</td>
                            <td>${escapeHtml(item.product_id || "N/A")}</td>
                            <td>${escapeHtml(String(item.available ?? "0"))}</td>
                            <td>${escapeHtml(String(item.allocated ?? "0"))}</td>
                          </tr>
                        `;
                      })
                      .join("")
                  : `
                    <tr>
                      <td colspan="4">No inventory data returned.</td>
                    </tr>
                  `
              }
            </tbody>
          </table>
        </div>
      </div>
    </section>
  `;
}

function renderActionsSection(actions) {
  return `
    <section>
      <div class="section-header">
        <p class="section-kicker">Recommended actions</p>
        <h3>Owner-aligned next steps</h3>
      </div>
      <div class="cards-grid three-up">
        ${
          Array.isArray(actions) && actions.length
            ? actions
                .map((item) => {
                  return `
                    <article class="meta-card">
                      <h3>${escapeHtml(item.owner || "Owner")}</h3>
                      <p>${escapeHtml(item.action || "No action returned.")}</p>
                    </article>
                  `;
                })
                .join("")
            : renderEmptyState("No actions", "No recommended actions were returned.")
        }
      </div>
    </section>
  `;
}

function renderTeamsSection(teamsUpdate) {
  const response = state.tasks.teamsResponse;
  return `
    <section>
      <div class="section-header">
        <p class="section-kicker">Dry-run handoff</p>
        <h3>Work IQ Teams preview</h3>
      </div>
      <article class="callout callout-warning">
        <div class="card-row">
          <h3>Teams delivery disabled</h3>
          <span class="badge ${statusClass(teamsUpdate.delivery || "blocked")}">
            ${escapeHtml(titleCase(teamsUpdate.delivery || "disabled"))}
          </span>
        </div>
        <p>
          ${escapeHtml(
            teamsUpdate.reason ||
              "The backend did not return a Teams delivery reason."
          )}
        </p>
        <div class="meta-badges">
          <span class="badge badge-soft">Send allowed: ${escapeHtml(
            String(Boolean(teamsUpdate.send_allowed))
          )}</span>
        </div>
      </article>
      <article class="summary-card">
        <h3>Dry-run preview</h3>
        <p class="chat-answer">${escapeHtml(
          teamsUpdate.text || "No preview text returned."
        )}</p>
        <div class="form-row">
          <label class="stack-inline" for="teams-opt-in">
            <input id="teams-opt-in" type="checkbox">
            <span>Pass explicit opt-in to the disabled preview endpoint</span>
          </label>
          <button
            class="secondary-button"
            type="button"
            data-action="preview-teams"
            data-run-id="${escapeHtml(state.tasks.activeRunId || "")}"
          >
            Check disabled handoff
          </button>
        </div>
        <p class="fine-print">
          Preview only. This presenter never claims that a Teams send occurred.
        </p>
      </article>
      ${
        response
          ? `
            <article class="meta-card">
              <div class="card-row">
                <h3>Endpoint response</h3>
                <span class="badge ${statusClass(response.mode || "blocked")}">${escapeHtml(
                  titleCase(response.mode || "disabled")
                )}</span>
              </div>
              <dl class="data-pairs">
                <div>
                  <dt>Sent</dt>
                  <dd>${escapeHtml(String(Boolean(response.sent)))}</dd>
                </div>
                <div>
                  <dt>Explicit opt-in</dt>
                  <dd>${escapeHtml(String(Boolean(response.explicit_opt_in)))}</dd>
                </div>
              </dl>
              <p class="fine-print">${escapeHtml(response.reason || "No reason returned.")}</p>
            </article>
          `
          : ""
      }
    </section>
  `;
}

function renderChecklist(title, items, emptyText) {
  const values = Array.isArray(items) ? items : [];
  return `
    <article class="checklist">
      <h3>${escapeHtml(title)}</h3>
      ${
        values.length
          ? `<ul>${values.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
          : `<p class="fine-print">${escapeHtml(emptyText)}</p>`
      }
    </article>
  `;
}

function renderEmptyState(title, description) {
  return `
    <article class="empty-state">
      <h3>${escapeHtml(title)}</h3>
      <p>${escapeHtml(description)}</p>
    </article>
  `;
}

function renderErrorCard(message) {
  return `
    <article class="callout callout-warning">
      <h3>Unable to load</h3>
      <p>${escapeHtml(message)}</p>
    </article>
  `;
}

function renderInlineNote(message) {
  return `
    <article class="callout callout-warning notice-block">
      <p>${escapeHtml(message)}</p>
    </article>
  `;
}

function renderRouteBadge(agent) {
  return `<span class="badge ${routeClass(agent)}">Route: ${escapeHtml(titleCase(agent))}</span>`;
}

function deriveFlowState(run, result) {
  const specialists = Array.isArray(result && result.specialists) ? result.specialists : [];
  const market = specialists.find((item) => item.agent === "market");
  const quality = specialists.find((item) => item.agent === "quality");
  const events = Array.isArray(run.events) ? run.events : [];

  const marketEvent = latestEventForAgent(events, "market");
  const qualityEvent = latestEventForAgent(events, "quality");
  const synthesisStarted = events.some((item) => {
    return item.agent === "commander" && /fan-in synthesis/i.test(item.stage || "");
  });

  return {
    commander: {
      kind: "commander",
      title: "Commander",
      status: normalizeStatus(run.status || "running", run.status === "running" ? "running" : "completed"),
      description: run.stage || "Commander has not started yet.",
      badges: [
        `Run ${run.id || "N/A"}`,
        `Incident ${run.incident_id || "N/A"}`,
        `${Number(run.progress || 0)}% progress`
      ]
    },
    market: {
      kind: "market",
      title: "Market",
      status: pickNodeStatus(market, marketEvent),
      description:
        (market && market.summary) ||
        (marketEvent && marketEvent.stage) ||
        "Waiting for Market evidence.",
      badges: [
        market && market.task_id ? `Task ${market.task_id}` : "Task pending",
        market && market.structured_data && market.structured_data.mode
          ? `Mode ${market.structured_data.mode}`
          : "No mode yet"
      ]
    },
    quality: {
      kind: "quality",
      title: "Quality",
      status: pickNodeStatus(quality, qualityEvent),
      description:
        (quality && quality.summary) ||
        (qualityEvent && qualityEvent.stage) ||
        "Waiting for Quality evidence.",
      badges: [
        quality && quality.task_id ? `Task ${quality.task_id}` : "Task pending",
        quality && quality.structured_data && quality.structured_data.mode
          ? `Mode ${quality.structured_data.mode}`
          : "No mode yet"
      ]
    },
    synthesis: {
      kind: "commander",
      title: "Fan-in brief",
      status: result
        ? normalizeStatus(result.status || "completed", "completed")
        : synthesisStarted
          ? "running"
          : "partial",
      description: result
        ? "Commander synthesized the cited response brief."
        : synthesisStarted
          ? "Commander is combining specialist evidence."
          : "Fan-in begins after specialist evidence returns.",
      badges: [
        result ? `${Array.isArray(result.citations) ? result.citations.length : 0} citations` : "Citations pending",
        result ? `Complete ${String(Boolean(result.complete))}` : "Result pending"
      ]
    }
  };
}

function latestEventForAgent(events, agent) {
  const filtered = events.filter((item) => item.agent === agent);
  return filtered.length ? filtered[filtered.length - 1] : null;
}

function pickNodeStatus(result, event) {
  if (result && result.status) {
    return normalizeStatus(result.status, "completed");
  }
  if (event && event.state) {
    return normalizeStatus(event.state, "running");
  }
  return "partial";
}

function normalizeStatus(value, fallback) {
  if (value === "disabled") {
    return "blocked";
  }
  const known = ["available", "blocked", "completed", "degraded", "failed", "partial", "running", "timeout"];
  return known.includes(value) ? value : fallback;
}

function routeClass(agent) {
  if (agent === "market") {
    return "route-market";
  }
  if (agent === "quality") {
    return "route-quality";
  }
  return "badge-brand";
}

function statusClass(status) {
  return `status-${normalizeStatus(status || "partial", "partial")}`;
}

function titleCase(value) {
  return String(value || "")
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatDateTime(value) {
  if (!value) {
    return "Unknown time";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return String(value);
  }
  return parsed.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function parseJson(value) {
  if (!value) {
    return null;
  }
  try {
    return JSON.parse(value);
  } catch (_error) {
    return null;
  }
}

function describeError(error) {
  if (!error) {
    return "Unknown error.";
  }
  return error.message || String(error);
}

function announce(message) {
  if (!elements.announcer) {
    return;
  }
  elements.announcer.textContent = "";
  window.setTimeout(() => {
    elements.announcer.textContent = message;
  }, 30);
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
