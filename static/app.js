const state = {
  projects: [],
  analytics: null,
};

const els = {
  form: document.getElementById("projectForm"),
  projectList: document.getElementById("projectList"),
  causesBars: document.getElementById("commonCausesBars"),
  analyticsCards: document.getElementById("analyticsCards"),
  heroStats: document.getElementById("heroStats"),
  causeChartNote: document.getElementById("causeChartNote"),
  causesPanel: document.getElementById("causesPanel"),
  categoryPanel: document.getElementById("categoryPanel"),
  refreshBtn: document.getElementById("refreshBtn"),
  cardTemplate: document.getElementById("projectCardTemplate"),
  loadingOverlay: document.getElementById("loadingOverlay"),
  loadingText: document.getElementById("loadingText"),
};

const loadingMessages = [
  "Collecting failed project records...",
  "Running Gemini failure pattern synthesis...",
  "Clustering realistic cause themes...",
  "Generating clearer pattern console insights...",
];
let loadingTicker = null;
let loadingIdx = 0;

function setLoading(isLoading, firstMessage) {
  if (!els.loadingOverlay || !els.loadingText) return;
  if (isLoading) {
    els.loadingOverlay.classList.remove("hidden");
    loadingIdx = 0;
    els.loadingText.textContent = firstMessage || loadingMessages[0];
    clearInterval(loadingTicker);
    loadingTicker = setInterval(() => {
      loadingIdx = (loadingIdx + 1) % loadingMessages.length;
      els.loadingText.textContent = loadingMessages[loadingIdx];
    }, 1350);
    return;
  }

  clearInterval(loadingTicker);
  loadingTicker = null;
  els.loadingOverlay.classList.add("hidden");
}

async function request(url, options = {}) {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `Request failed: ${res.status}`);
  }
  return res.json();
}

function num(n) {
  return typeof n === "number" ? n : 0;
}

function parseCsv(input) {
  return (input || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

function toPayload(form) {
  const fd = new FormData(form);
  const payload = Object.fromEntries(fd.entries());
  payload.initial_causes = parseCsv(payload.initial_causes);
  payload.tags = parseCsv(payload.tags).map((v) => v.toLowerCase());
  return payload;
}

function barRow(cause, maxVotes) {
  const row = document.createElement("div");
  row.className = "bar-row";
  const coverageWidth = Math.max(6, num(cause.coverage_pct));
  const voteWidth = maxVotes > 0 ? (num(cause.total_votes) / maxVotes) * 100 : 0;
  row.innerHTML = `
    <span class="bar-label">
      ${cause.name}
      <small>${cause.project_count} projects • ${num(cause.coverage_pct).toFixed(1)}% coverage</small>
    </span>
    <div class="bar-track">
      <div class="bar-fill" style="width:${coverageWidth}%"></div>
      <div class="bar-accent" style="width:${voteWidth}%"></div>
    </div>
    <strong>${cause.total_votes}</strong>
  `;
  return row;
}

function renderAnalytics() {
  const data = state.analytics;
  if (!data) return;

  els.heroStats.innerHTML = "";
  const topCause = data.top_cause_name || data.common_causes[0]?.name || "N/A";
  const topVotes = data.top_cause_votes || data.common_causes[0]?.total_votes || 0;
  const topCoverage = data.top_cause_coverage_pct || data.common_causes[0]?.coverage_pct || 0;
  [
    `Total Failed Projects: ${num(data.total_projects)}`,
    `Primary Failure Pattern: ${topCause}`,
    `Top Cause Strength: ${topVotes} votes • ${topCoverage}% coverage`,
    `Portfolio Health Signal: Burnout ${num(data.signals.avg_burnout).toFixed(1)} / Market ${num(data.signals.avg_market_signal).toFixed(1)}`,
  ].forEach((txt) => {
    const span = document.createElement("span");
    span.textContent = txt;
    els.heroStats.appendChild(span);
  });

  let cards = (data.console_cards || []).slice(0, 4);
  if (!cards.length) {
    cards = [
      { label: "Total Submissions", value: String(num(data.total_projects)), note: "Projects currently included in Gemini portfolio analysis." },
      { label: "Avg Burnout", value: num(data.signals.avg_burnout).toFixed(1), note: "Higher values indicate founder sustainability pressure." },
      { label: "Avg Market Signal", value: num(data.signals.avg_market_signal).toFixed(1), note: "Lower values suggest weak demand validation before build." },
      { label: "Avg Tech Debt", value: num(data.signals.avg_tech_debt).toFixed(1), note: "Proxy for execution friction over project lifecycle." },
    ];
  }
  els.analyticsCards.innerHTML = cards
    .map(
      (card) => `
      <div class="metric">
        <small>${card.label || "Insight"}</small>
        <strong>${card.value || "-"}</strong>
        <div class="metric-note">${card.note || ""}</div>
      </div>
    `
    )
    .join("");

  const maxCauseVotes = Math.max(...data.common_causes.map((c) => c.total_votes), 1);
  els.causesBars.innerHTML = "";
  if (els.causeChartNote) {
    els.causeChartNote.textContent = data.causes_chart_note || "Live crowd signal across all failed projects.";
  }
  data.common_causes.forEach((cause) => {
    els.causesBars.appendChild(barRow(cause, maxCauseVotes));
  });

  els.causesPanel.innerHTML = "<h3>AI Cause Leaderboard</h3>";
  const leaderboard = (data.cause_leaderboard || []).slice(0, 6);
  if (!leaderboard.length) {
    const p = document.createElement("p");
    p.textContent = "No stable leaderboard yet.";
    els.causesPanel.appendChild(p);
  }
  leaderboard.forEach((line, i) => {
    const p = document.createElement("p");
    p.textContent = `${i + 1}. ${line}`;
    els.causesPanel.appendChild(p);
  });

  els.categoryPanel.innerHTML = "<h3>Category Pattern Narrative</h3>";
  const categoryStory = (data.category_story || []).slice(0, 6);
  if (!categoryStory.length) {
    const p = document.createElement("p");
    p.textContent = "Need more project variety for category patterns.";
    els.categoryPanel.appendChild(p);
  }
  categoryStory.forEach((line) => {
    const p = document.createElement("p");
    p.textContent = line;
    els.categoryPanel.appendChild(p);
  });
}

function renderProjects() {
  els.projectList.innerHTML = "";
  if (!state.projects.length) {
    els.projectList.innerHTML = '<div class="empty">No projects yet. Submit one to start the dataset.</div>';
    return;
  }

  state.projects.forEach((project) => {
    const node = els.cardTemplate.content.cloneNode(true);
    const card = node.querySelector(".project-card");
    node.querySelector(".title").textContent = project.title;
    node.querySelector(".status").textContent = project.status;
    node.querySelector(".summary").textContent = project.summary;

    node.querySelector(".meta").innerHTML = [
      `Category: ${project.category}`,
      `Team: ${project.team_size || "-"}`,
      `Duration: ${project.duration_months || "-"} mo`,
      `Burnout: ${project.burnout_level}/10`,
      `Market Signal: ${project.market_signal}/10`,
      `Tech Debt: ${project.tech_debt_level}/10`,
    ]
      .map((m) => `<span>${m}</span>`)
      .join("");

    node.querySelector(".causes").innerHTML = (project.causes || [])
      .map((c) => `<span class="chip cause">${c.name} (${c.votes})</span>`)
      .join("");

    node.querySelector(".tags").innerHTML = (project.tags || [])
      .map((t) => `<span class="chip tag">#${t}</span>`)
      .join("");

    node.querySelector(".details").innerHTML = `
      <strong>What happened:</strong> ${project.what_happened || "-"}<br>
      <strong>Why failed:</strong> ${project.why_failed || "-"}<br>
      <strong>Lessons:</strong> ${project.lessons_learned || "-"}
    `;

    const ai = node.querySelector(".ai");
    if (project.analysis?.report) {
      const r = project.analysis.report;
      ai.innerHTML = `
        <strong>AI Autopsy (${project.analysis.model})</strong><br>
        Pattern: ${(r.failure_vector || []).join(", ")}<br>
        Summary: ${r.common_pattern_summary || "-"}<br>
        Playbook: ${(r.next_attempt_playbook || []).join(" | ")}
      `;
    } else {
      ai.textContent = "No AI autopsy yet. Run analysis to generate pattern insights.";
    }

    const causeInput = node.querySelector(".causeInput");
    const tagInput = node.querySelector(".tagInput");

    node.querySelector(".voteBtn").addEventListener("click", async () => {
      try {
        const cause = causeInput.value.trim();
        if (!cause) return;
        await request(`/api/projects/${project.id}/vote-cause`, {
          method: "POST",
          body: JSON.stringify({ cause, votes: 1 }),
        });
        causeInput.value = "";
        await refresh();
      } catch (err) {
        alert(err.message);
      }
    });

    node.querySelector(".tagBtn").addEventListener("click", async () => {
      try {
        const tag = tagInput.value.trim();
        if (!tag) return;
        await request(`/api/projects/${project.id}/tags`, {
          method: "POST",
          body: JSON.stringify({ tag }),
        });
        tagInput.value = "";
        await refresh();
      } catch (err) {
        alert(err.message);
      }
    });

    node.querySelector(".analyzeBtn").addEventListener("click", async () => {
      try {
        await request(`/api/projects/${project.id}/analyze`, { method: "POST" });
        await refresh();
      } catch (err) {
        alert(err.message);
      }
    });

    els.projectList.appendChild(node);
  });
}

async function refresh() {
  setLoading(true, "Syncing your graveyard dataset...");
  try {
    const [projects, analytics] = await Promise.all([
      request("/api/projects"),
      request("/api/analytics/overview"),
    ]);
    state.projects = projects;
    state.analytics = analytics;
    renderProjects();
    renderAnalytics();
  } finally {
    setLoading(false);
  }
}

els.form.addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const payload = toPayload(els.form);
    await request("/api/projects", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    els.form.reset();
    await refresh();
  } catch (err) {
    alert(err.message);
  }
});

els.refreshBtn.addEventListener("click", async () => {
  try {
    await refresh();
  } catch (err) {
    alert(err.message);
  }
});

refresh().catch((err) => {
  console.error(err);
  setLoading(false);
  alert(`Failed to load app data: ${err.message}`);
});
