const $ = (selector) => document.querySelector(selector);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
const get = async (path) => {
  const response = await fetch(path, {cache: "no-store"});
  if (!response.ok) throw new Error(`${response.status} ${path}`);
  return response.json();
};
const status = (value) => `<span class="status ${esc(value)}">${esc(value)}</span>`;
const empty = () => `<p class="empty">暂无运行数据</p>`;

function renderMetrics(data) {
  const executionTotal = Object.values(data.executions || {}).reduce((a, b) => a + b, 0);
  const cards = [
    ["执行总数", executionTotal], ["运行中", data.executions?.running || 0],
    ["消息积压", (data.messages?.queued || 0) + (data.messages?.retry_wait || 0)],
    ["死信", data.messages?.dead_letter || 0], ["Agent 定义", data.agents || 0],
    ["Skill 定义", data.skills || 0],
  ];
  $("#metrics").innerHTML = cards.map(([label, value]) => `<div class="metric"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join("");
}

function renderExecutions(rows) {
  $("#executions").innerHTML = rows.length ? rows.slice(0, 20).map((row) => `<tr>
    <td>${status(row.status)}</td><td>${esc(row.agent_id)}</td>
    <td class="code" title="${esc(row.execution_id)}">${esc(row.execution_id.slice(0, 18))}</td>
    <td>${esc(row.backend)}</td><td>${esc(new Date(row.created_at).toLocaleString())}</td>
  </tr>`).join("") : `<tr><td colspan="5">${empty()}</td></tr>`;
}

function renderBars(values) {
  const entries = Object.entries(values).filter(([key]) => key !== "total");
  const max = Math.max(1, ...entries.map(([, value]) => value));
  $("#message-bars").innerHTML = entries.length ? entries.map(([key, value]) => `<div class="bar-row"><span>${esc(key)}</span><div class="bar-track"><div class="bar-fill" style="width:${Math.round(value / max * 100)}%"></div></div><strong>${value}</strong></div>`).join("") : empty();
}

function renderList(selector, rows, title, detail, badge) {
  $(selector).innerHTML = rows.length ? rows.slice(0, 40).map((row) => `<div class="list-item"><strong>${esc(title(row))}</strong><span class="badge">${esc(badge(row))}</span><small>${esc(detail(row))}</small></div>`).join("") : empty();
}

function addEvent(row) {
  const list = $("#events");
  const item = document.createElement("li");
  item.innerHTML = `<time>${esc(new Date(row.occurred_at).toLocaleTimeString())}</time><strong>${esc(row.event_type)}</strong><code>${esc(row.execution_id || row.payload?.message_id || "system")}</code>`;
  list.prepend(item);
  while (list.children.length > 60) list.lastChild.remove();
}

async function refresh() {
  try {
    const [health, metrics, executions, agents, memory, capabilities, events] = await Promise.all([
      get("/api/health"), get("/api/metrics"), get("/api/executions?limit=30"),
      get("/api/agents"), get("/api/memory?limit=40"), get("/api/capabilities"), get("/api/events?limit=30")
    ]);
    $(".health").className = "health ok";
    $("#health-label").textContent = `Runtime ${health.version}`;
    renderMetrics(metrics); renderExecutions(executions); renderBars(metrics.messages || {});
    renderList("#agents", agents, (x) => x.agent_id, (x) => `${x.backend} · ${x.model || "default model"}`, (x) => x.status);
    renderList("#memory", memory, (x) => x.subject, (x) => `${x.namespace} · confidence ${x.confidence}`, (x) => x.status);
    renderList("#capabilities", capabilities, (x) => x.name, (x) => `${x.owner || "unowned"} · evidence ${x.evidence_count || 0}`, (x) => `${x.status}/${x.maturity}`);
    $("#events").innerHTML = ""; events.reverse().forEach(addEvent);
  } catch (error) {
    $(".health").className = "health bad";
    $("#health-label").textContent = "Runtime 不可达";
    console.error(error);
  }
}

function connectEvents() {
  const source = new EventSource(`/api/events/stream?after=${encodeURIComponent(new Date().toISOString())}`);
  source.addEventListener("trace", (event) => { addEvent(JSON.parse(event.data)); $("#stream-state").textContent = "实时连接"; });
  source.onerror = () => { $("#stream-state").textContent = "正在重连"; };
}

refresh(); connectEvents(); setInterval(refresh, 15000);
