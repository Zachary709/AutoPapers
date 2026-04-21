import { api } from "./api.js";
import { renderPaperDetail, selectPaper } from "./paper_detail.js";
import { renderAppChrome } from "./settings.js";
import {
  elements,
  escapeHtml,
  findPaperLocationById,
  findPaperSummaryById,
  firstPaperFromTree,
  formatShortDate,
  persistConversationState,
  state,
  syncDirectoryFocusToSelection,
} from "./state.js";

export async function loadLibrary({ preserveSelection = true } = {}) {
  const payload = await api("/api/library");
  state.app = payload.app;
  state.library = payload.library;

  if (!preserveSelection || !findPaperSummaryById(state.selectedPaperId)) {
    const firstPaper = firstPaperFromTree(payload.library);
    state.selectedPaperId = firstPaper ? firstPaper.paper_id : null;
    persistConversationState();
  }

  syncDirectoryFocusToSelection();
  renderAppChrome();
  renderLibrary();
  if (state.selectedPaperId) {
    await selectPaper(state.selectedPaperId, { silent: true });
  } else {
    state.selectedPaper = null;
    renderPaperDetail();
  }
}

export function renderStats() {
  if (!state.library) {
    elements.libraryStats.innerHTML = "";
    return;
  }
  const stats = state.library.stats;
  elements.libraryStats.innerHTML = [
    statCard(stats.paper_count, "papers"),
    statCard(stats.major_topic_count, "major"),
    statCard(stats.minor_topic_count, "minor"),
  ].join("");
}

function statCard(value, label) {
  return `<div class="stat-card"><span class="stat-value">${escapeHtml(String(value))}</span><span class="stat-label">${escapeHtml(label)}</span></div>`;
}

export function setDirectorySearchOpen(isOpen, options = {}) {
  state.directorySearchOpen = Boolean(isOpen);
  syncDirectorySearchUI();
  if (state.directorySearchOpen && options.focusInput) {
    window.setTimeout(() => {
      elements.libraryFilter?.focus();
      elements.libraryFilter?.select();
    }, 0);
    return;
  }
  if (!state.directorySearchOpen && options.restoreFocus) {
    window.setTimeout(() => {
      elements.directorySearchToggle?.focus();
    }, 0);
  }
}

export function syncDirectorySearchUI() {
  const hasFilter = Boolean(state.filter);
  elements.directorySearchPanel.classList.toggle("hidden", !state.directorySearchOpen);
  elements.directorySearchToggle.classList.toggle("active", state.directorySearchOpen || hasFilter);
  elements.directorySearchToggle.setAttribute("aria-expanded", state.directorySearchOpen ? "true" : "false");
  elements.directorySearchToggleDot.classList.toggle("hidden", !hasFilter);
}

export function renderLibrary() {
  if (!state.library || state.library.major_topics.length === 0) {
    elements.majorRail.innerHTML = "";
    elements.libraryBreadcrumb.innerHTML = "";
    elements.minorTabs.innerHTML = "";
    elements.librarySummary.innerHTML = "";
    elements.libraryTree.innerHTML = `<div class="empty-state">当前论文库为空。提交任务后，新论文会自动落到这里。</div>`;
    return;
  }

  const topics = state.library.major_topics
    .map((major) => filterMajorTopic(major, state.filter))
    .filter(Boolean);

  if (topics.length === 0) {
    elements.majorRail.innerHTML = "";
    elements.libraryBreadcrumb.innerHTML = "";
    elements.minorTabs.innerHTML = "";
    elements.librarySummary.innerHTML = "";
    elements.libraryTree.innerHTML = `<div class="empty-state">没有匹配当前过滤词的目录项。</div>`;
    return;
  }

  const activeMajor = resolveActiveMajorTopic(topics);
  const activeMinor = resolveActiveMinorTopic(activeMajor);
  const visiblePapers = buildVisiblePapers(activeMajor, activeMinor);

  elements.majorRail.innerHTML = renderMajorRail(topics, activeMajor.name);
  elements.libraryBreadcrumb.innerHTML = renderBreadcrumb(activeMajor, activeMinor);
  elements.minorTabs.innerHTML = renderMinorTabs(activeMajor, activeMinor);
  elements.librarySummary.innerHTML = renderLibrarySummary(activeMajor, activeMinor, visiblePapers.length);
  elements.libraryTree.innerHTML = renderPaperListView(visiblePapers);
}

function filterMajorTopic(major, filter) {
  if (!filter) {
    return major;
  }

  const filteredMinorTopics = major.minor_topics
    .map((minor) => {
      const filteredPapers = minor.papers.filter((paper) =>
        [paper.title, paper.takeaway, major.name, minor.name].join(" ").toLowerCase().includes(filter)
      );
      const topicHit = `${major.name} ${minor.name}`.toLowerCase().includes(filter);
      if (filteredPapers.length === 0 && !topicHit) {
        return null;
      }
      return {
        ...minor,
        papers: topicHit && filteredPapers.length === 0 ? minor.papers : filteredPapers,
        count: topicHit && filteredPapers.length === 0 ? minor.papers.length : filteredPapers.length,
      };
    })
    .filter(Boolean);

  if (filteredMinorTopics.length === 0 && !major.name.toLowerCase().includes(filter)) {
    return null;
  }

  return {
    ...major,
    minor_topics: filteredMinorTopics.length ? filteredMinorTopics : major.minor_topics,
  };
}

function resolveActiveMajorTopic(topics) {
  const matched = topics.find((major) => major.name === state.activeMajorTopic);
  const nextMajor = matched || topics[0];
  state.activeMajorTopic = nextMajor.name;
  return nextMajor;
}

function resolveActiveMinorTopic(major) {
  const availableMinorNames = new Set(major.minor_topics.map((minor) => minor.name));
  if (state.activeMinorTopic === "__all__") {
    return "__all__";
  }
  if (availableMinorNames.has(state.activeMinorTopic)) {
    return state.activeMinorTopic;
  }
  const selectedLocation = findPaperLocationById(state.selectedPaperId);
  if (selectedLocation && selectedLocation.major.name === major.name && availableMinorNames.has(selectedLocation.minor.name)) {
    state.activeMinorTopic = selectedLocation.minor.name;
    return state.activeMinorTopic;
  }
  state.activeMinorTopic = "__all__";
  return "__all__";
}

function buildVisiblePapers(major, activeMinor) {
  const items = [];
  const minors = activeMinor === "__all__"
    ? major.minor_topics
    : major.minor_topics.filter((minor) => minor.name === activeMinor);

  for (const minor of minors) {
    for (const paper of minor.papers) {
      items.push({ ...paper, minor_name: minor.name, major_name: major.name });
    }
  }

  return items.sort((left, right) => {
    const leftTime = Date.parse(left.published || "") || 0;
    const rightTime = Date.parse(right.published || "") || 0;
    return rightTime - leftTime;
  });
}

function renderMajorRail(topics, activeMajorName) {
  return `
    <div class="major-rail-list">
      ${topics.map((major) => renderMajorRailButton(major, activeMajorName)).join("")}
    </div>
  `;
}

function renderMajorRailButton(major, activeMajorName) {
  const activeClass = major.name === activeMajorName ? "active" : "";
  return `
    <button class="major-button ${activeClass}" type="button" data-major-topic="${escapeHtml(major.name)}">
      <span class="major-button-title">${escapeHtml(major.name)}</span>
      <span class="major-button-meta">
        <span>${escapeHtml(String(major.minor_topic_count))} tracks</span>
        <span>${escapeHtml(String(major.count))}</span>
      </span>
    </button>
  `;
}

function renderBreadcrumb(major, activeMinor) {
  const segments = [
    `<span class="breadcrumb-segment"><span class="breadcrumb-pill">全部论文</span></span>`,
    `<span class="breadcrumb-segment"><span>/</span><span class="breadcrumb-pill">${escapeHtml(major.name)}</span></span>`,
  ];
  if (activeMinor !== "__all__") {
    segments.push(`<span class="breadcrumb-segment"><span>/</span><span class="breadcrumb-pill">${escapeHtml(activeMinor)}</span></span>`);
  }
  return segments.join("");
}

function renderMinorTabs(major, activeMinor) {
  const totalCount = major.minor_topics.reduce((sum, minor) => sum + minor.papers.length, 0);
  const items = [
    { name: "__all__", label: "全部子方向", count: totalCount },
    ...major.minor_topics.map((minor) => ({ name: minor.name, label: minor.name, count: minor.papers.length })),
  ];
  return items.map((item) => {
    const activeClass = item.name === activeMinor ? "active" : "";
    return `
      <button class="minor-tab ${activeClass}" type="button" data-minor-topic="${escapeHtml(item.name)}">
        <span>${escapeHtml(item.label)}</span>
        <span class="minor-tab-count">${escapeHtml(String(item.count))}</span>
      </button>
    `;
  }).join("");
}

function renderLibrarySummary(major, activeMinor, visibleCount) {
  const minorLabel = activeMinor === "__all__" ? "当前查看该方向下全部论文" : `当前子方向：${activeMinor}`;
  return `
    <span><strong>${escapeHtml(major.name)}</strong> · ${escapeHtml(minorLabel)}</span>
    <span>${escapeHtml(String(visibleCount))} papers</span>
  `;
}

function renderPaperListView(papers) {
  if (!papers.length) {
    return `<div class="empty-state">当前方向下没有匹配论文。</div>`;
  }
  return `<div class="paper-list-view">${papers.map(renderPaperRow).join("")}</div>`;
}

function renderPaperRow(paper) {
  const activeClass = paper.paper_id === state.selectedPaperId ? "active" : "";
  const statusClass = paper.paper_id === state.selectedPaperId ? "ready" : "ready";
  const takeaway = paper.takeaway || "暂无整理摘要。";
  const venueBits = [];
  if (paper.venue?.name) {
    venueBits.push(paper.venue.name);
  }
  if (paper.venue?.year) {
    venueBits.push(String(paper.venue.year));
  }
  if (typeof paper.citation_count === "number") {
    venueBits.push(`cited ${paper.citation_count}`);
  }
  const venueMeta = venueBits.length ? `<span class="paper-meta">${escapeHtml(venueBits.join(" · "))}</span>` : "";
  return `
    <button class="paper-row ${activeClass}" type="button" data-paper-id="${escapeHtml(paper.paper_id)}">
      <span class="paper-row-main">
        <span class="paper-title">${escapeHtml(paper.title)}</span>
        <span class="paper-meta">
          <span class="paper-row-date">${escapeHtml(formatShortDate(paper.published))}</span>
          <span class="paper-row-track">${escapeHtml(paper.minor_name)}</span>
        </span>
        ${venueMeta}
        <span class="paper-meta">${escapeHtml(takeaway)}</span>
      </span>
      <span class="paper-row-status">
        <span class="paper-status-dot ${statusClass}"></span>
        <span class="paper-status-meta">${paper.paper_id === state.selectedPaperId ? "open" : "ready"}</span>
      </span>
    </button>
  `;
}
