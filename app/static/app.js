let runId;
let teamsSendMode = "dry-run";
let teamsDeliveryReason = "Teams delivery is unavailable.";
const el = id => document.getElementById(id);

function make(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function safeHttpsUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}

async function jsonFetch(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let detail = "";
    try {
      detail = (await response.json()).detail || "";
    } catch {
      detail = "";
    }
    throw new Error(detail || `${url} returned HTTP ${response.status}`);
  }
  return response.json();
}

function setRoute(route) {
  document.querySelectorAll(".view").forEach(view => { view.hidden = true; });
  document.querySelectorAll("nav a").forEach(link => link.classList.remove("active"));
  el(`${route}-view`).hidden = false;
  document.querySelector(`nav a[data-route="${route}"]`).classList.add("active");
}

function routeFromPath() {
  const route = location.pathname.slice(1);
  return ["chat", "tasks", "history", "evaluation"].includes(route) ? route : "tasks";
}

async function loadStatus() {
  const status = await jsonFetch("/api/preflight");
  el("mode").textContent = status.mode === "demo" ? "DEMO MODE" : "LIVE CONFIGURED";
  el("mode").className = `pill ${status.mode === "demo" ? "demo" : ""}`;
  const summary = el("adapter-summary");
  summary.replaceChildren();
  const workIq = status.adapters.find(adapter => adapter.name === "Work IQ delegated context");
  const teams = status.adapters.find(adapter => adapter.name === "Teams delivery");
  const workIqOptIn = el("include-work-iq");
  workIqOptIn.disabled = workIq?.mode !== "live-toolbox";
  workIqOptIn.checked = false;
  workIqOptIn.title = workIq?.reason || "Work IQ is unavailable.";
  teamsSendMode = teams?.mode || "dry-run";
  teamsDeliveryReason = teams?.reason || "Teams delivery is unavailable.";
  const liveTeams = teamsSendMode === "live-work-iq" || teamsSendMode === "live";
  el("dry-run").textContent = liveTeams ? "Send on Teams" : "Validate dry run";
  el("dry-run").title = teamsDeliveryReason;
  el("teams-target").textContent = teamsDeliveryReason;
  el("teams-badge").textContent = teamsSendMode === "live-work-iq" ? "Work IQ · approval required" : "Dry run";
  for (const adapter of status.adapters) {
    const line = make("div", undefined, "adapter-line");
    const label = adapter.name.replace(" / Search", "").replace(" ontology", "");
    line.append(make("span", label), make("strong", adapter.mode, adapter.mode));
    summary.append(line);
  }
}

function recentRun(run) {
  const card = make("button", undefined, "recent-run");
  card.type = "button";
  card.append(
    make("strong", run.objective),
    make("small", `${run.status} · ${new Date(run.created_at).toLocaleString()}`),
  );
  card.addEventListener("click", () => showRun(run.id));
  return card;
}

async function loadHistory() {
  const history = await jsonFetch("/api/scenarios");
  el("history-count").textContent = String(history.items.length);
  const recent = el("recent-runs");
  const list = el("history-list");
  recent.replaceChildren();
  list.replaceChildren();
  if (!history.items.length) {
    recent.append(make("p", "No incidents yet.", "empty"));
    list.append(make("p", "Launch a task to create the first incident record.", "empty"));
    return;
  }
  history.items.slice(0, 3).forEach(run => recent.append(recentRun(run)));
  for (const run of history.items) {
    const card = make("article", undefined, "history-card");
    const copy = make("div");
    copy.append(
      make("span", run.status, "status"),
      make("h2", run.objective),
      make("p", `${run.progress}% · ${run.stage} · ${new Date(run.created_at).toLocaleString()}`),
    );
    const button = make("button", run.status === "completed" ? "View outcome" : "View task");
    button.type = "button";
    button.addEventListener("click", () => showRun(run.id));
    card.append(copy, button);
    list.append(card);
  }
}

function formatMetric(value) {
  return typeof value === "number" ? value.toLocaleString() : value ?? "—";
}

function parseStructuredAnswer(text) {
  if (typeof text !== "string" || !text.trim().startsWith("{")) return null;
  try {
    const value = JSON.parse(text);
    return value && typeof value === "object" && ((value.incident && value.brief) || value.route)
      ? value
      : null;
  } catch {
    return null;
  }
}

function responseSection(title, text) {
  const section = make("section", undefined, "chat-response-section");
  section.append(make("h4", title), make("p", text || "No verified finding returned."));
  return section;
}

function renderStructuredChat(result) {
  const response = make("div", undefined, "chat-response");
  if (result.route === "radar_only" || result.route === "fab_only") {
    const isRadar = result.route === "radar_only";
    const hero = make("section", undefined, "chat-incident-summary");
    hero.append(
      make("span", isRadar ? "Radar · Public web only" : "Fab Intelligence · Internal only", "eyebrow"),
      make("h3", isRadar ? "External market & regulatory intelligence" : "Manufacturing intelligence"),
      make(
        "p",
        isRadar
          ? "No Fabric, Foundry IQ internal knowledge, SharePoint, OneDrive, or Work IQ source was activated."
          : "No public web source or Radar agent was activated.",
        "chat-incident-meta",
      ),
    );
    response.append(hero, responseSection(isRadar ? "Current external context" : "Grounded finding", result.answer));
    const fab = result.result || {};
    if (!isRadar && fab.field_exposure > 0) {
      const metrics = make("section", undefined, "chat-kpis");
      [
        ["Units in field", formatMetric(fab.field_exposure)],
        ["Blockable stock", formatMetric(fab.blockable_stock)],
        ["Containment perimeter", `${formatMetric(fab.containment_perimeter_pct)}%`],
      ].forEach(([label, value]) => {
        const card = make("div", undefined, "chat-kpi");
        card.append(make("strong", value), make("span", label));
        metrics.append(card);
      });
      response.append(metrics);
    }
    return response;
  }
  const incident = result.incident || {};
  const brief = result.brief || {};
  const radar = result.agent_outputs?.radar || {};
  const impact = brief.field_impact || {};
  const hero = make("section", undefined, "chat-incident-summary");
  hero.append(
    make("span", `${incident.severity || "Incident"} · ${incident.id || "Assessment"}`, "eyebrow"),
    make("h3", incident.title || "Operational assessment"),
    make(
      "p",
      `Lot ${incident.affected_lot || "—"} · Product ${incident.product_ref || "—"}`,
      "chat-incident-meta",
    ),
  );
  response.append(hero);

  if (radar.normative_risk) {
    response.append(responseSection("Current external context", radar.normative_risk));
  }

  const metrics = make("section", undefined, "chat-kpis");
  [
    ["Units in field", formatMetric(impact.units_in_field ?? radar.field_exposure)],
    ["Blockable stock", formatMetric(impact.blockable_stock ?? radar.blockable_stock)],
    ["Containment perimeter", `${formatMetric(impact.containment_perimeter_pct ?? radar.containment_perimeter_pct)}%`],
  ].forEach(([label, value]) => {
    const card = make("div", undefined, "chat-kpi");
    card.append(make("strong", value), make("span", label));
    metrics.append(card);
  });
  response.append(metrics);

  if (brief.probable_root_cause) {
    response.append(responseSection("Probable root cause", brief.probable_root_cause));
  }

  const customers = impact.impacted_customers || radar.impacted_customers || [];
  if (customers.length) {
    const section = make("section", undefined, "chat-response-section");
    section.append(make("h4", "Customer impact"));
    const list = make("div", undefined, "chat-customers");
    customers.forEach(customer => {
      const row = make("div", undefined, "chat-customer");
      const identity = make("div");
      identity.append(make("strong", customer.name), make("small", `${customer.tier} · ${customer.application}`));
      row.append(identity, make("b", `${formatMetric(customer.units_in_field)} units`));
      list.append(row);
    });
    section.append(list);
    response.append(section);
  }

  if (brief.recommended_actions?.length) {
    const section = make("section", undefined, "chat-response-section");
    section.append(make("h4", "Recommended actions"));
    const list = make("ol", undefined, "chat-actions");
    brief.recommended_actions.forEach(action => list.append(make("li", action)));
    section.append(list);
    response.append(section);
  }

  return response;
}

function renderChatSources(sources) {
  const sourceList = make("div", undefined, "chat-sources");
  sourceList.append(make("strong", `Sources · ${sources.length}`));
  for (const source of sources) {
    const item = make("div", undefined, "chat-source");
    const heading = make("div", undefined, "chat-source-heading");
    heading.append(make("span", source.badge || source.source_type || "Source", "badge"));
    const url = safeHttpsUrl(source.url);
    if (url) {
      const link = make("a", source.title || "Open source");
      link.href = url;
      link.target = "_blank";
      link.rel = "noreferrer";
      heading.append(link);
    } else {
      heading.append(make("strong", source.title || "Source"));
    }
    item.append(heading);
    if (source.excerpt) item.append(make("p", source.excerpt));
    sourceList.append(item);
  }
  return sourceList;
}

function appendMessage(role, text, sources = [], trajectory = [], structuredResult = null) {
  const article = make("article", undefined, `${role}-message`);
  const body = make("div");
  body.append(make("strong", role === "assistant" ? "ST IQ Operations Assistant" : "You"));
  const structured = role === "assistant"
    ? structuredResult || parseStructuredAnswer(text)
    : null;
  body.append(structured ? renderStructuredChat(structured) : make("p", text));
  const displayedSources = structured?.sources?.length
    ? structured.sources
    : structured?.citations?.length
      ? structured.citations
      : sources;
  if (trajectory.length) {
    const trace = make("div", undefined, "chat-trajectory");
    trace.append(make("strong", "Agent trajectory"));
    for (const step of trajectory) {
      const item = make("div", undefined, "trajectory-step");
      item.append(
        make("span", "✓", "trajectory-check"),
        make("div", undefined),
      );
      item.lastChild.append(make("strong", step.agent), make("small", step.detail));
      trace.append(item);
    }
    body.append(trace);
  }
  if (displayedSources.length) body.append(renderChatSources(displayedSources));
  article.append(make("span", role === "assistant" ? "IQ" : "SK", "avatar"), body);
  el("conversation").append(article);
  article.scrollIntoView({ behavior: "smooth", block: "end" });
}

async function sendChat(message) {
  appendMessage("user", message);
  const pending = make("article", undefined, "assistant-message pending-workflow");
  const pendingBody = make("div");
  pendingBody.append(make("strong", "ST SiC Incident Command"), make("p", "Running the Foundry workflow…"));
  const pendingSteps = make("div", undefined, "pending-steps");
  [
    "Chief Orchestrator · classifying the request",
    "Activating only the required specialist evidence domain",
    "Applying source isolation and provenance checks",
  ].forEach((step, index) => {
    const item = make("span", step);
    if (index === 0) item.className = "active";
    pendingSteps.append(item);
  });
  pendingBody.append(pendingSteps);
  pending.append(make("span", "IQ", "avatar"), pendingBody);
  el("conversation").append(pending);
  try {
    const result = await jsonFetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    pending.remove();
    appendMessage("assistant", result.answer, result.sources, result.trajectory, result.structured);
  } catch (error) {
    pending.remove();
    appendMessage("assistant", `Request failed: ${error.message}`);
  }
}

function renderCandidate(candidate) {
  const row = make("article", undefined, "candidate-row");
  const identity = make("div");
  const nameLine = make("div", undefined, "candidate-name");
  nameLine.append(make("i", undefined, candidate.best ? "best-dot" : ""));
  nameLine.append(make("strong", candidate.name));
  if (candidate.best) nameLine.append(make("span", "Best verified", "best-label"));
  identity.append(nameLine, make("small", `Agent version ${candidate.agent_version} · ${candidate.strategy}`));
  const score = make("div", undefined, "candidate-score");
  const bar = make("span");
  bar.style.width = `${Math.round(candidate.score * 100)}%`;
  score.append(bar);
  row.append(
    identity,
    score,
    make("strong", candidate.score.toFixed(3)),
    make("span", `${candidate.passed}/${candidate.passed + candidate.failed}`, "candidate-pass"),
  );
  return row;
}

async function loadEvaluation() {
  const loading = el("evaluation-loading");
  const content = el("evaluation-content");
  try {
    const evaluation = await jsonFetch("/api/evaluation");
    const best = [...evaluation.candidates].sort((a, b) => b.score - a.score)[0];
    el("evaluation-score").textContent = `${Math.round(best.score * 100)}%`;
    el("evaluation-dataset").textContent =
      `${evaluation.dataset.executed_cases}/${evaluation.dataset.total_cases} smoke cases executed · ${evaluation.dataset.name}`;
    el("evaluation-meter").style.width = `${Math.round(best.score * 100)}%`;
    const candidates = el("candidate-list");
    candidates.replaceChildren();
    evaluation.candidates.forEach(candidate => candidates.append(renderCandidate(candidate)));
    el("optimizer-state").textContent = evaluation.optimizer.state;
    el("optimizer-label").textContent = evaluation.optimizer.label;
    el("optimizer-reason").textContent = evaluation.optimizer.reason;
    el("optimizer-action").textContent = evaluation.optimizer.action;
    loading.hidden = true;
    content.hidden = false;
  } catch (error) {
    loading.textContent = `Evaluation evidence unavailable: ${error.message}`;
  }
}

function addEvent(event) {
  el("progress-label").textContent = `${event.progress}% · ${event.stage}`;
  el("bar").style.width = `${event.progress}%`;
  document.querySelector(".progress").setAttribute("aria-valuenow", event.progress);
  const entry = make("li");
  entry.append(make("strong", event.stage), document.createElement("br"), make("small", new Date(event.timestamp).toLocaleTimeString()));
  el("events").append(entry);
}

function appendLabeled(container, label, text) {
  const paragraph = make("p");
  paragraph.append(make("strong", label), document.createElement("br"), document.createTextNode(text));
  container.append(paragraph);
}

function renderResult(result) {
  el("result").hidden = false;
  el("incident-title").textContent = `${result.incident.severity} · ${result.incident.title}`;
  el("data-notice").textContent = result.data_notice;
  el("impact").replaceChildren();
  const impact = result.brief.field_impact;
  appendLabeled(el("impact"), impact.units_in_field.toLocaleString(), "units already in field");
  appendLabeled(el("impact"), impact.blockable_stock.toLocaleString(), "units blockable");
  appendLabeled(el("impact"), `${impact.containment_perimeter_pct}%`, "of modeled lot shipped");
  for (const customer of impact.impacted_customers) {
    appendLabeled(
      el("impact"),
      customer.name,
      `${customer.units_in_field.toLocaleString()} units · ${customer.application}`,
    );
  }
  el("actions").replaceChildren();
  appendLabeled(el("actions"), "Probable root cause", result.brief.probable_root_cause);
  for (const action of result.brief.recommended_actions) {
    appendLabeled(el("actions"), "Recommended", action);
  }
  const evidence = result.evidence_trace;
  el("evidence-count").textContent = `${evidence.completed}/${evidence.total}`;
  el("citations").replaceChildren();
  for (const citation of result.citations) {
    const source = make("div", undefined, "source");
    const description = make("p");
    const link = safeHttpsUrl(citation.url);
    if (link) {
      const anchor = make("a", citation.title);
      anchor.href = link;
      anchor.target = "_blank";
      anchor.rel = "noreferrer";
      description.append(anchor);
    } else {
      description.append(make("strong", citation.title));
    }
    description.append(document.createElement("br"), make("small", citation.excerpt));
    source.append(make("span", citation.badge, "badge"), description);
    el("citations").append(source);
  }
  el("radar-json").textContent = JSON.stringify(result.agent_outputs.radar, null, 2);
  el("fab-json").textContent = JSON.stringify(result.agent_outputs.fab_intelligence, null, 2);
  el("teams-text").textContent = "Teams-ready incident brief";
}

function failAssessment(message) {
  addEvent({ progress: 100, stage: `Failed · ${message}`, timestamp: new Date().toISOString() });
  el("start").disabled = false;
}

async function followRun(id) {
  runId = id;
  el("assessment").hidden = false;
  el("result").hidden = true;
  el("events").replaceChildren();
  const current = await jsonFetch(`/api/scenarios/${id}`);
  current.events.forEach(addEvent);
  if (current.status === "completed") {
    renderResult(await jsonFetch(`/api/scenarios/${id}/result`));
    return;
  }
  const events = new EventSource(`/api/scenarios/${id}/events`);
  let seen = current.events.length;
  let terminal = false;
  events.onmessage = event => {
    if (seen > 0) {
      seen -= 1;
      return;
    }
    addEvent(JSON.parse(event.data));
  };
  events.addEventListener("done", async event => {
    terminal = true;
    events.close();
    const summary = JSON.parse(event.data);
    if (summary.status !== "completed") {
      failAssessment(summary.stage || "Review service logs.");
      return;
    }
    renderResult(await jsonFetch(`/api/scenarios/${id}/result`));
    el("start").disabled = false;
    await loadHistory();
  });
  events.onerror = () => {
    if (!terminal && events.readyState === EventSource.CLOSED) failAssessment("Progress stream closed unexpectedly.");
  };
}

async function startTask() {
  el("start").disabled = true;
  el("assessment").hidden = false;
  el("result").hidden = true;
  el("events").replaceChildren();
  try {
    const run = await jsonFetch("/api/scenarios", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        objective: el("objective").value,
        include_work_iq: el("include-work-iq").checked,
      }),
    });
    await followRun(run.id);
  } catch (error) {
    failAssessment(error.message);
  }
}

async function showRun(id) {
  history.pushState({}, "", "/tasks");
  setRoute("tasks");
  await followRun(id);
}

document.querySelectorAll("a[data-route]").forEach(link => {
  link.addEventListener("click", event => {
    event.preventDefault();
    const route = link.dataset.route;
    history.pushState({}, "", `/${route}`);
    setRoute(route);
    if (route === "history") loadHistory();
    if (route === "evaluation") loadEvaluation();
  });
});
window.addEventListener("popstate", () => setRoute(routeFromPath()));
document.querySelectorAll("[data-prompt]").forEach(button => {
  button.addEventListener("click", () => {
    el("chat-input").value = button.dataset.prompt;
    el("chat-input").focus();
  });
});
el("chat-form").addEventListener("submit", async event => {
  event.preventDefault();
  const message = el("chat-input").value.trim();
  if (!message) return;
  el("chat-input").value = "";
  await sendChat(message);
});
el("start").addEventListener("click", startTask);
el("dry-run").addEventListener("click", async () => {
  const liveTeams = teamsSendMode === "live-work-iq" || teamsSendMode === "live";
  if (liveTeams && !window.confirm(
    `Send this exact incident update as a direct Teams message?\n\n${teamsDeliveryReason}`
  )) return;
  const approvalCode = liveTeams
    ? window.prompt("Enter the presenter approval code shown by deploy-web.ps1")
    : null;
  if (liveTeams && !approvalCode) return;
  el("dry-run").disabled = true;
  try {
    const result = await jsonFetch(`/api/scenarios/${runId}/teams`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ explicit_opt_in: liveTeams, approval_code: approvalCode }),
    });
    el("delivery").textContent = `${result.mode}: ${result.reason}`;
    el("delivery").className = "delivery-ok";
  } catch (error) {
    el("delivery").textContent = `Delivery failed: ${error.message}`;
    el("delivery").className = "";
  } finally {
    el("dry-run").disabled = false;
  }
});

setRoute(routeFromPath());
Promise.all([loadStatus(), loadHistory(), loadEvaluation()]);
