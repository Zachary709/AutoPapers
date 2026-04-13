const state = {
  app: null,
  library: null,
  activeMajorTopic: null,
  activeMinorTopic: "__all__",
  selectedPaperId: null,
  selectedPaper: null,
  selectedPaperRequestId: 0,
  filter: "",
  messages: [
    {
      id: "welcome",
      kind: "intro",
      role: "assistant",
      text: "把任务交给右侧对话框。左侧目录会展示当前论文库，并允许你随时预览或删除单篇论文。",
    },
  ],
};

const elements = {};
const layoutKeys = {
  chatWidth: "autopapers.layout.chatWidth",
  chatCollapsed: "autopapers.layout.chatCollapsed",
  directoryCollapsed: "autopapers.layout.directoryCollapsed",
  previewWidth: "autopapers.layout.previewWidth",
  previewCollapsed: "autopapers.layout.previewCollapsed",
};
const layoutConfig = {
  splitterSize: 14,
  minChatWidth: 300,
  minDirectoryWidth: 360,
  minPreviewWidth: 340,
  collapseThreshold: 188,
  expandThreshold: 240,
};
const layoutState = {
  chatWidth: null,
  previewWidth: null,
  chatCollapsed: false,
  directoryCollapsed: false,
  previewCollapsed: false,
};
const panelLabels = {
  chat: "LLM",
  directory: "Directory",
  preview: "Preview",
};
const mathRenderState = {
  pendingRoots: new Set(),
  scheduled: false,
  retryCount: 0,
  maxRetries: 20,
};

document.addEventListener("DOMContentLoaded", async () => {
  bindElements();
  initializeResizableLayout();
  bindEvents();
  await loadLibrary();
  renderMessages();
});

function bindElements() {
  elements.appShell = document.getElementById("appShell");
  elements.chatPanel = document.getElementById("chatPanel");
  elements.directoryPanel = document.getElementById("directoryPanel");
  elements.previewPanel = document.getElementById("previewPanel");
  elements.libraryStats = document.getElementById("libraryStats");
  elements.libraryFilter = document.getElementById("libraryFilter");
  elements.majorRail = document.getElementById("majorRail");
  elements.libraryBreadcrumb = document.getElementById("libraryBreadcrumb");
  elements.minorTabs = document.getElementById("minorTabs");
  elements.librarySummary = document.getElementById("librarySummary");
  elements.libraryTree = document.getElementById("libraryTree");
  elements.paperDetail = document.getElementById("paperDetail");
  elements.chatDirectorySplitter = document.getElementById("chatDirectorySplitter");
  elements.directoryPreviewSplitter = document.getElementById("directoryPreviewSplitter");
  elements.statusBanner = document.getElementById("statusBanner");
  elements.chatFeed = document.getElementById("chatFeed");
  elements.composerForm = document.getElementById("composerForm");
  elements.promptInput = document.getElementById("promptInput");
  elements.refreshExistingInput = document.getElementById("refreshExistingInput");
  elements.maxResultsInput = document.getElementById("maxResultsInput");
  elements.submitButton = document.getElementById("submitButton");
  elements.modelChip = document.getElementById("modelChip");
  elements.jobChip = document.getElementById("jobChip");
  elements.toastStack = document.getElementById("toastStack");
}

function bindEvents() {
  elements.libraryFilter.addEventListener("input", (event) => {
    state.filter = event.target.value.trim().toLowerCase();
    renderLibrary();
  });

  elements.libraryTree.addEventListener("click", (event) => {
    const button = event.target.closest("[data-paper-id]");
    if (!button || !elements.libraryTree.contains(button)) {
      return;
    }
    void selectPaper(button.getAttribute("data-paper-id"));
  });

  elements.majorRail.addEventListener("click", (event) => {
    const button = event.target.closest("[data-major-topic]");
    if (!button || !elements.majorRail.contains(button)) {
      return;
    }
    state.activeMajorTopic = button.getAttribute("data-major-topic");
    state.activeMinorTopic = "__all__";
    renderLibrary();
  });

  elements.minorTabs.addEventListener("click", (event) => {
    const button = event.target.closest("[data-minor-topic]");
    if (!button || !elements.minorTabs.contains(button)) {
      return;
    }
    state.activeMinorTopic = button.getAttribute("data-minor-topic") || "__all__";
    renderLibrary();
  });

  elements.composerForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const prompt = elements.promptInput.value.trim();
    if (!prompt) {
      return;
    }

    appendMessage({
      id: `user-${Date.now()}`,
      kind: "text",
      role: "user",
      text: prompt,
    });

    const maxResultsValue = elements.maxResultsInput.value.trim();
    const payload = {
      prompt,
      refresh_existing: elements.refreshExistingInput.checked,
      max_results: maxResultsValue ? Number(maxResultsValue) : null,
    };

    setSubmitting(true);
    try {
      const response = await api("/api/tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      appendMessage({
        id: `job-${response.job.id}`,
        kind: "job",
        role: "assistant",
        job: response.job,
      });
      elements.promptInput.value = "";
      pollJob(response.job.id);
    } catch (error) {
      appendMessage({
        id: `error-${Date.now()}`,
        kind: "error",
        role: "assistant",
        text: error.message,
      });
    } finally {
      setSubmitting(false);
      updateJobChip();
    }
  });

  elements.promptInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      elements.composerForm.requestSubmit();
    }
  });
}

function initializeResizableLayout() {
  loadStoredLayoutState();
  syncShellLayout({ persist: false });
  bindResizableSplitters();
  window.addEventListener("resize", () => {
    syncShellLayout({ persist: false });
  });
}

function bindResizableSplitters() {
  bindDragSplitter(elements.chatDirectorySplitter, {
    axis: "x",
    bodyClass: "is-resizing-col",
    getStartValue: () => getCurrentChatWidth(),
    applyDelta: (startValue, delta) => setChatPanelWidth(startValue + delta),
    getRestorePanel: () => getSplitterRestoreTarget("chat", "directory", "chat"),
    step: 28,
    onKeyAdjust: (delta) => setChatPanelWidth(getCurrentChatWidth() + delta),
  });

  bindDragSplitter(elements.directoryPreviewSplitter, {
    axis: "x",
    bodyClass: "is-resizing-col",
    getStartValue: () => getCurrentPreviewWidth(),
    applyDelta: (startValue, delta) => setPreviewPanelWidth(startValue - delta),
    getRestorePanel: () => getSplitterRestoreTarget("directory", "preview", "preview"),
    step: 28,
    onKeyAdjust: (delta) => setPreviewPanelWidth(getCurrentPreviewWidth() - delta),
  });
}

function bindDragSplitter(handle, options) {
  if (!handle) {
    return;
  }

  const startDrag = (pointerId, startPointer, pointerType = "mouse") => {
    const startValue = options.getStartValue();
    let moved = false;
    handle.classList.add("dragging");
    document.body.classList.add(options.bodyClass);

    const onMove = (moveEvent) => {
      if (pointerId !== null && "pointerId" in moveEvent && moveEvent.pointerId !== pointerId) {
        return;
      }
      const currentPointer = options.axis === "x" ? moveEvent.clientX : moveEvent.clientY;
      moved = moved || Math.abs(currentPointer - startPointer) > 3;
      options.applyDelta(startValue, currentPointer - startPointer);
    };

    const stop = (endEvent) => {
      if (pointerId !== null && "pointerId" in endEvent && endEvent.pointerId !== pointerId) {
        return;
      }
      handle.classList.remove("dragging");
      document.body.classList.remove(options.bodyClass);
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerup", stop);
      document.removeEventListener("pointercancel", stop);
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", stop);
      if (!moved) {
        const restorePanel = options.getRestorePanel?.();
        if (restorePanel) {
          expandPanel(restorePanel);
        }
      }
    };

    if (pointerType === "pointer") {
      document.addEventListener("pointermove", onMove);
      document.addEventListener("pointerup", stop);
      document.addEventListener("pointercancel", stop);
    } else {
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", stop);
    }
  };

  handle.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || !isDesktopLayout()) {
      return;
    }
    event.preventDefault();
    const startPointer = options.axis === "x" ? event.clientX : event.clientY;
    startDrag(event.pointerId ?? null, startPointer, "pointer");
  });

  handle.addEventListener("mousedown", (event) => {
    if (event.button !== 0 || !isDesktopLayout()) {
      return;
    }
    if (window.PointerEvent) {
      return;
    }
    event.preventDefault();
    const startPointer = options.axis === "x" ? event.clientX : event.clientY;
    startDrag(null, startPointer, "mouse");
  });

  handle.addEventListener("keydown", (event) => {
    if (!isDesktopLayout()) {
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      const restorePanel = options.getRestorePanel?.();
      if (restorePanel) {
        event.preventDefault();
        expandPanel(restorePanel);
      }
      return;
    }
    const horizontal = options.axis === "x";
    const decrementKeys = horizontal ? ["ArrowLeft"] : ["ArrowUp"];
    const incrementKeys = horizontal ? ["ArrowRight"] : ["ArrowDown"];
    if (!decrementKeys.includes(event.key) && !incrementKeys.includes(event.key)) {
      return;
    }
    event.preventDefault();
    const direction = incrementKeys.includes(event.key) ? 1 : -1;
    options.onKeyAdjust(direction * options.step);
  });
}

function loadStoredLayoutState() {
  layoutState.chatWidth = readStoredNumber(layoutKeys.chatWidth);
  layoutState.previewWidth = readStoredNumber(layoutKeys.previewWidth);
  layoutState.chatCollapsed = readStoredBoolean(layoutKeys.chatCollapsed, false);
  layoutState.directoryCollapsed = readStoredBoolean(layoutKeys.directoryCollapsed, false);
  layoutState.previewCollapsed = readStoredBoolean(layoutKeys.previewCollapsed, false);
}

function syncShellLayout({ persist = true } = {}) {
  if (!elements.appShell) {
    return;
  }
  if (!isDesktopLayout()) {
    elements.appShell.style.removeProperty("grid-template-columns");
    [elements.chatPanel, elements.directoryPanel, elements.previewPanel].forEach((panel) => {
      panel?.classList.remove("is-collapsed", "panel-leading", "panel-trailing", "panel-solo");
      if (panel) {
        panel.removeAttribute("aria-hidden");
      }
    });
    [elements.chatDirectorySplitter, elements.directoryPreviewSplitter].forEach((splitter) => {
      splitter?.classList.remove("is-collapsed-handle");
      splitter?.removeAttribute("data-restore-panel");
      splitter?.setAttribute("aria-label", splitter?.id === "chatDirectorySplitter" ? "调整对话区和目录区宽度" : "调整目录区和预览区宽度");
      const label = splitter?.querySelector(".splitter-label");
      if (label) {
        label.textContent = "";
      }
    });
    return;
  }

  ensureAtLeastOneVisiblePanel();
  const resolved = resolveTrackWidths();
  layoutState.chatWidth = layoutState.chatCollapsed ? resolved.chatWidth || layoutState.chatWidth : resolved.chatWidth;
  layoutState.previewWidth = layoutState.previewCollapsed ? resolved.previewWidth || layoutState.previewWidth : resolved.previewWidth;
  elements.appShell.style.gridTemplateColumns = `${resolved.chatWidth}px ${layoutConfig.splitterSize}px ${resolved.directoryWidth}px ${layoutConfig.splitterSize}px ${resolved.previewWidth}px`;
  updatePanelChrome(resolved);
  if (persist) {
    persistLayoutState();
  }
}

function resolveTrackWidths() {
  const shellWidth = Math.max(elements.appShell?.clientWidth || window.innerWidth, 0);
  const splitTotal = layoutConfig.splitterSize * 2;
  let chatWidth = layoutState.chatCollapsed ? 0 : clamp(
    layoutState.chatWidth ?? getDefaultChatWidth(shellWidth),
    layoutConfig.minChatWidth,
    shellWidth
  );
  let previewWidth = layoutState.previewCollapsed ? 0 : clamp(
    layoutState.previewWidth ?? getDefaultPreviewWidth(shellWidth),
    layoutConfig.minPreviewWidth,
    shellWidth
  );

  if (layoutState.directoryCollapsed) {
    [chatWidth, previewWidth] = fitTrackPair({
      first: chatWidth,
      second: previewWidth,
      firstMin: layoutState.chatCollapsed ? 0 : layoutConfig.minChatWidth,
      secondMin: layoutState.previewCollapsed ? 0 : layoutConfig.minPreviewWidth,
      available: Math.max(0, shellWidth - splitTotal),
    });
    return {
      shellWidth,
      chatWidth,
      directoryWidth: 0,
      previewWidth,
    };
  }

  [chatWidth, previewWidth] = fitTrackPair({
    first: chatWidth,
    second: previewWidth,
    firstMin: layoutState.chatCollapsed ? 0 : layoutConfig.minChatWidth,
    secondMin: layoutState.previewCollapsed ? 0 : layoutConfig.minPreviewWidth,
    available: Math.max(0, shellWidth - splitTotal - layoutConfig.minDirectoryWidth),
  });

  return {
    shellWidth,
    chatWidth,
    directoryWidth: Math.max(0, shellWidth - splitTotal - chatWidth - previewWidth),
    previewWidth,
  };
}

function ensureAtLeastOneVisiblePanel() {
  if (getExpandedPanelCount() > 0) {
    return;
  }
  layoutState.directoryCollapsed = false;
}

function fitTrackPair({ first, second, firstMin, secondMin, available }) {
  let nextFirst = Math.max(0, first);
  let nextSecond = Math.max(0, second);
  if (nextFirst + nextSecond <= available) {
    return [nextFirst, nextSecond];
  }

  let overflow = nextFirst + nextSecond - available;
  const firstReducible = Math.max(0, nextFirst - firstMin);
  const secondReducible = Math.max(0, nextSecond - secondMin);
  const totalReducible = firstReducible + secondReducible;

  if (totalReducible <= 0) {
    return [Math.max(0, firstMin), Math.max(0, secondMin)];
  }

  const firstShare = firstReducible / totalReducible;
  let reduceFirst = Math.min(firstReducible, overflow * firstShare);
  let reduceSecond = Math.min(secondReducible, overflow - reduceFirst);
  overflow -= reduceFirst + reduceSecond;

  if (overflow > 0 && reduceFirst < firstReducible) {
    const extra = Math.min(firstReducible - reduceFirst, overflow);
    reduceFirst += extra;
    overflow -= extra;
  }
  if (overflow > 0 && reduceSecond < secondReducible) {
    const extra = Math.min(secondReducible - reduceSecond, overflow);
    reduceSecond += extra;
  }

  nextFirst = Math.max(firstMin, nextFirst - reduceFirst);
  nextSecond = Math.max(secondMin, nextSecond - reduceSecond);
  return [nextFirst, nextSecond];
}

function setChatPanelWidth(width, { persist = true } = {}) {
  const desired = Math.max(0, Number(width) || 0);

  if (layoutState.chatCollapsed) {
    if (desired < layoutConfig.expandThreshold) {
      syncShellLayout({ persist });
      return;
    }
    layoutState.chatCollapsed = false;
  } else if (desired < layoutConfig.collapseThreshold && canCollapsePanel("chat")) {
    layoutState.chatCollapsed = true;
    syncShellLayout({ persist });
    return;
  }

  layoutState.chatWidth = desired;

  const currentPreviewWidth = resolveTrackWidths().previewWidth;
  const potentialDirectoryWidth = getPotentialDirectoryWidth(layoutState.chatWidth, currentPreviewWidth);
  if (layoutState.directoryCollapsed && potentialDirectoryWidth >= layoutConfig.expandThreshold) {
    layoutState.directoryCollapsed = false;
  } else if (!layoutState.directoryCollapsed && potentialDirectoryWidth < layoutConfig.collapseThreshold && canCollapsePanel("directory")) {
    layoutState.directoryCollapsed = true;
  }

  syncShellLayout({ persist });
}

function setPreviewPanelWidth(width, { persist = true } = {}) {
  const desired = Math.max(0, Number(width) || 0);

  if (layoutState.previewCollapsed) {
    if (desired < layoutConfig.expandThreshold) {
      syncShellLayout({ persist });
      return;
    }
    layoutState.previewCollapsed = false;
  } else if (desired < layoutConfig.collapseThreshold && canCollapsePanel("preview")) {
    layoutState.previewCollapsed = true;
    syncShellLayout({ persist });
    return;
  }

  layoutState.previewWidth = desired;

  const currentChatWidth = resolveTrackWidths().chatWidth;
  const potentialDirectoryWidth = getPotentialDirectoryWidth(currentChatWidth, layoutState.previewWidth);
  if (layoutState.directoryCollapsed && potentialDirectoryWidth >= layoutConfig.expandThreshold) {
    layoutState.directoryCollapsed = false;
  } else if (!layoutState.directoryCollapsed && potentialDirectoryWidth < layoutConfig.collapseThreshold && canCollapsePanel("directory")) {
    layoutState.directoryCollapsed = true;
  }

  syncShellLayout({ persist });
}

function collapsePanel(panel, { persist = true } = {}) {
  if (!canCollapsePanel(panel)) {
    return;
  }
  layoutState[`${panel}Collapsed`] = true;
  syncShellLayout({ persist });
}

function expandPanel(panel, { persist = true } = {}) {
  layoutState[`${panel}Collapsed`] = false;
  if (panel === "chat" && !layoutState.chatWidth) {
    layoutState.chatWidth = getDefaultChatWidth(elements.appShell?.clientWidth || window.innerWidth);
  }
  if (panel === "preview" && !layoutState.previewWidth) {
    layoutState.previewWidth = getDefaultPreviewWidth(elements.appShell?.clientWidth || window.innerWidth);
  }
  syncShellLayout({ persist });
}

function canCollapsePanel(panel) {
  if (layoutState[`${panel}Collapsed`]) {
    return false;
  }
  return getExpandedPanelCount() > 1;
}

function getExpandedPanelCount() {
  return ["chat", "directory", "preview"].filter((panel) => !layoutState[`${panel}Collapsed`]).length;
}

function getCurrentChatWidth() {
  return resolveTrackWidths().chatWidth;
}

function getCurrentPreviewWidth() {
  return resolveTrackWidths().previewWidth;
}

function getPotentialDirectoryWidth(chatWidth, previewWidth) {
  const shellWidth = elements.appShell?.clientWidth || window.innerWidth;
  const splitTotal = layoutConfig.splitterSize * 2;
  const nextChat = layoutState.chatCollapsed ? 0 : Math.max(0, chatWidth);
  const nextPreview = layoutState.previewCollapsed ? 0 : Math.max(0, previewWidth);
  return shellWidth - splitTotal - nextChat - nextPreview;
}

function updatePanelChrome({ chatWidth, directoryWidth, previewWidth }) {
  const panels = [
    { key: "chat", element: elements.chatPanel, width: chatWidth },
    { key: "directory", element: elements.directoryPanel, width: directoryWidth },
    { key: "preview", element: elements.previewPanel, width: previewWidth },
  ];

  for (const panel of panels) {
    if (!panel.element) {
      continue;
    }
    const collapsed = panel.width <= 0;
    panel.element.classList.toggle("is-collapsed", collapsed);
    panel.element.classList.remove("panel-leading", "panel-trailing", "panel-solo");
    panel.element.setAttribute("aria-hidden", collapsed ? "true" : "false");
  }

  const visiblePanels = panels.filter((panel) => panel.width > 0);
  if (visiblePanels.length === 1) {
    visiblePanels[0].element.classList.add("panel-solo");
  } else if (visiblePanels.length >= 2) {
    visiblePanels[0].element.classList.add("panel-leading");
    visiblePanels[visiblePanels.length - 1].element.classList.add("panel-trailing");
  }

  setSplitterHandleState(
    elements.chatDirectorySplitter,
    getSplitterRestoreTarget("chat", "directory", "chat"),
    "调整对话区和目录区宽度"
  );
  setSplitterHandleState(
    elements.directoryPreviewSplitter,
    getSplitterRestoreTarget("directory", "preview", "preview"),
    "调整目录区和预览区宽度"
  );
}

function setSplitterHandleState(splitter, restorePanel, defaultLabel) {
  if (!splitter) {
    return;
  }
  const label = splitter.querySelector(".splitter-label");
  const isCollapsedHandle = Boolean(restorePanel);
  splitter.classList.toggle("is-collapsed-handle", isCollapsedHandle);
  if (restorePanel) {
    splitter.dataset.restorePanel = restorePanel;
    splitter.setAttribute("aria-label", `展开 ${panelLabels[restorePanel]}`);
  } else {
    delete splitter.dataset.restorePanel;
    splitter.setAttribute("aria-label", defaultLabel);
  }
  if (label) {
    label.textContent = restorePanel ? panelLabels[restorePanel] : "";
  }
}

function getSplitterRestoreTarget(firstPanel, secondPanel, fallbackPanel) {
  const firstCollapsed = layoutState[`${firstPanel}Collapsed`];
  const secondCollapsed = layoutState[`${secondPanel}Collapsed`];

  if (firstCollapsed && !secondCollapsed) {
    return firstPanel;
  }
  if (!firstCollapsed && secondCollapsed) {
    return secondPanel;
  }
  if (firstCollapsed && secondCollapsed) {
    return fallbackPanel;
  }
  return "";
}

function getDefaultChatWidth(shellWidth) {
  return Math.round(shellWidth * 0.28);
}

function getDefaultPreviewWidth(shellWidth) {
  return Math.round(shellWidth * 0.3);
}

function persistLayoutState() {
  persistLayoutValue(layoutKeys.chatWidth, layoutState.chatWidth ?? getDefaultChatWidth(elements.appShell?.clientWidth || window.innerWidth));
  persistLayoutValue(layoutKeys.previewWidth, layoutState.previewWidth ?? getDefaultPreviewWidth(elements.appShell?.clientWidth || window.innerWidth));
  persistLayoutValue(layoutKeys.chatCollapsed, layoutState.chatCollapsed);
  persistLayoutValue(layoutKeys.directoryCollapsed, layoutState.directoryCollapsed);
  persistLayoutValue(layoutKeys.previewCollapsed, layoutState.previewCollapsed);
}

function persistLayoutValue(key, value) {
  try {
    if (typeof value === "boolean") {
      window.localStorage.setItem(key, value ? "1" : "0");
      return;
    }
    window.localStorage.setItem(key, String(Math.round(value)));
  } catch (error) {
    // Ignore localStorage failures and keep the layout change in memory only.
  }
}

function readStoredNumber(key) {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) {
      return null;
    }
    const parsed = Number(raw);
    return Number.isFinite(parsed) ? parsed : null;
  } catch (error) {
    return null;
  }
}

function readStoredBoolean(key, fallback = false) {
  try {
    const raw = window.localStorage.getItem(key);
    if (raw === null) {
      return fallback;
    }
    return raw === "1" || raw === "true";
  } catch (error) {
    return fallback;
  }
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function isDesktopLayout() {
  return window.matchMedia("(min-width: 1081px)").matches;
}

async function loadLibrary({ preserveSelection = true } = {}) {
  const payload = await api("/api/library");
  state.app = payload.app;
  state.library = payload.library;

  if (!preserveSelection || !findPaperSummaryById(state.selectedPaperId)) {
    const firstPaper = firstPaperFromTree(payload.library);
    state.selectedPaperId = firstPaper ? firstPaper.arxiv_id : null;
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

function renderAppChrome() {
  elements.modelChip.textContent = state.app?.model || "Unknown model";
  if (!state.app?.api_key_configured) {
    elements.statusBanner.classList.remove("hidden");
    elements.statusBanner.textContent = "当前未配置 MiniMax API key。目录可浏览，但新任务会失败。";
  } else {
    elements.statusBanner.classList.add("hidden");
    elements.statusBanner.textContent = "";
  }
  updateJobChip();
  renderStats();
}

function renderStats() {
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

function renderLibrary() {
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
  const activeClass = paper.arxiv_id === state.selectedPaperId ? "active" : "";
  const statusClass = paper.arxiv_id === state.selectedPaperId ? "ready" : "ready";
  const takeaway = paper.takeaway || "暂无整理摘要。";
  return `
    <button class="paper-row ${activeClass}" type="button" data-paper-id="${escapeHtml(paper.arxiv_id)}">
      <span class="paper-row-main">
        <span class="paper-title">${escapeHtml(paper.title)}</span>
        <span class="paper-meta">
          <span class="paper-row-date">${escapeHtml(formatShortDate(paper.published))}</span>
          <span class="paper-row-track">${escapeHtml(paper.minor_name)}</span>
        </span>
        <span class="paper-meta">${escapeHtml(takeaway)}</span>
      </span>
      <span class="paper-row-status">
        <span class="paper-status-dot ${statusClass}"></span>
        <span class="paper-status-meta">${paper.arxiv_id === state.selectedPaperId ? "open" : "ready"}</span>
      </span>
    </button>
  `;
}

async function selectPaper(arxivId, { silent = false } = {}) {
  if (!arxivId) {
    state.selectedPaperId = null;
    state.selectedPaper = null;
    state.selectedPaperRequestId += 1;
    renderPaperDetail();
    return;
  }

  const requestId = state.selectedPaperRequestId + 1;
  state.selectedPaperRequestId = requestId;
  state.selectedPaperId = arxivId;
  state.selectedPaper = null;
  syncDirectoryFocusToSelection();
  if (!silent) {
    renderLibrary();
  }
  renderPaperDetailLoading();

  try {
    const detail = await api(`/api/papers/${encodeURIComponent(arxivId)}`);
    if (requestId !== state.selectedPaperRequestId || state.selectedPaperId !== arxivId) {
      return;
    }
    state.selectedPaper = detail;
    renderPaperDetail();
  } catch (error) {
    if (requestId !== state.selectedPaperRequestId || state.selectedPaperId !== arxivId) {
      return;
    }
    state.selectedPaper = null;
    renderPaperDetail(error.message);
  }
}

function renderPaperDetailLoading() {
  elements.paperDetail.innerHTML = `<div class="empty-state">正在加载论文预览...</div>`;
}

function renderPaperDetail(errorText = "") {
  if (errorText) {
    elements.paperDetail.innerHTML = `<div class="empty-state">${escapeHtml(errorText)}</div>`;
    return;
  }

  if (!state.selectedPaper) {
    elements.paperDetail.innerHTML = `<div class="empty-state">选中一篇论文后，这里会显示摘要、关键词、方法概览和操作按钮。</div>`;
    return;
  }

  const { summary, paper, digest, download_urls, markdown_content } = state.selectedPaper;
  const pdfButton = download_urls.pdf ? `<a class="button-link" href="${download_urls.pdf}" target="_blank" rel="noreferrer">Open PDF</a>` : "";
  const detailBody = hasRenderableMarkdown(markdown_content)
    ? `<div class="detail-section"><h4>Note Preview</h4>${renderMarkdownPreview(markdown_content)}</div>`
    : renderStructuredPaperFallback(paper, digest);

  elements.paperDetail.innerHTML = `
    <article class="detail-card">
      <div>
        <div class="eyebrow">${escapeHtml(summary.major_topic)} / ${escapeHtml(summary.minor_topic)}</div>
        <h3>${escapeHtml(summary.title)}</h3>
        <div class="paper-meta"><span>${escapeHtml(summary.versioned_id)}</span><span>${escapeHtml(formatShortDate(summary.published))}</span></div>
      </div>
      <div class="detail-actions">
        ${pdfButton}
        <a class="button-link" href="${download_urls.markdown}" target="_blank" rel="noreferrer">Open Note</a>
        <button class="danger-button" type="button" id="deletePaperButton">Delete Paper</button>
      </div>
      <div class="tag-row">${(digest.keywords || []).map((item) => `<span class="tag">${escapeHtml(item)}</span>`).join("")}</div>
      ${detailBody}
    </article>
  `;

  const deleteButton = document.getElementById("deletePaperButton");
  if (deleteButton) {
    deleteButton.addEventListener("click", () => void deletePaper(summary.arxiv_id, summary.title));
  }
  queueMathTypeset(elements.paperDetail);
}

async function deletePaper(arxivId, title) {
  const confirmed = window.confirm(`确定删除这篇论文及其本地文件？\n\n${title}`);
  if (!confirmed) {
    return;
  }

  try {
    const payload = await api(`/api/papers/${encodeURIComponent(arxivId)}`, { method: "DELETE" });
    if (state.selectedPaperId === arxivId) {
      state.selectedPaperId = null;
      state.selectedPaper = null;
    }
    state.app = payload.app;
    state.library = payload.library;
    renderAppChrome();
    renderLibrary();
    renderPaperDetail();
    appendMessage({ id: `delete-${Date.now()}`, kind: "text", role: "assistant", text: `已删除论文：${title}` });
  } catch (error) {
    appendMessage({ id: `delete-error-${Date.now()}`, kind: "error", role: "assistant", text: error.message });
  }
}

function appendMessage(message) {
  state.messages.push(message);
  renderMessages();
}

function renderMessages() {
  elements.chatFeed.innerHTML = state.messages.map(renderMessage).join("");
  elements.chatFeed.querySelectorAll("[data-focus-paper]").forEach((button) => {
    button.addEventListener("click", () => void selectPaper(button.getAttribute("data-focus-paper")));
  });
  queueMathTypeset(elements.chatFeed);
  elements.chatFeed.scrollTop = elements.chatFeed.scrollHeight;
}

function renderMessage(message) {
  if (message.kind === "intro" || message.kind === "text") {
    return `<article class="message ${escapeHtml(message.role)}"><div class="message-title"><strong>${message.role === "user" ? "You" : "Assistant"}</strong></div><pre>${escapeHtml(message.text)}</pre></article>`;
  }
  if (message.kind === "error") {
    return `<article class="message assistant error"><div class="message-title"><strong>Task Failed</strong></div><pre>${escapeHtml(message.text)}</pre></article>`;
  }
  if (message.kind === "job") {
    const job = message.job;
    if (job.status === "completed") {
      return renderCompletedJob(job);
    }
    if (job.status === "failed") {
      return `<article class="message assistant error"><div class="message-title"><strong>Task Failed</strong><span class="chip">${escapeHtml(job.status)}</span></div><div class="job-meta">${escapeHtml(job.request)}</div>${renderNoticeSection(job.notices)}<pre>${escapeHtml(job.error || "Unknown error")}</pre></article>`;
    }
    return `<article class="message assistant"><div class="message-title"><strong>Running Task</strong><span class="chip">${escapeHtml(job.status)}</span></div><div class="job-meta">${escapeHtml(job.request)}</div>${renderNoticeSection(job.notices)}<p class="muted">任务已进入队列。完成后会自动刷新目录并展示结果。</p></article>`;
  }
  return "";
}

function renderCompletedJob(job) {
  const result = job.result;
  return `
    <article class="message assistant">
      <div class="message-title"><strong>Task Completed</strong><span class="chip">${escapeHtml(result.plan.intent)}</span></div>
      <div class="job-meta">${escapeHtml(job.request)}</div>
      ${renderNoticeSection(job.notices)}
      <section class="report-section"><h4>Plan</h4><p>${escapeHtml(result.plan.user_goal)}</p></section>
      ${renderPaperSection("New / Refreshed Papers", result.new_papers)}
      ${renderPaperSection("Reused Local Papers", result.reused_papers)}
      ${renderPaperSection("Related Local Papers", result.related_papers)}
      <section class="report-section"><h4>Report Preview</h4>${renderMarkdownPreview(result.report_markdown, { compact: true })}</section>
    </article>
  `;
}

function renderNoticeSection(notices = []) {
  if (!notices || notices.length === 0) {
    return "";
  }
  return `
    <section class="report-section">
      <h4>Notices</h4>
      <ul class="notice-list">${notices.map((notice) => `<li>${escapeHtml(notice.message)}</li>`).join("")}</ul>
    </section>
  `;
}

function renderPaperSection(title, papers) {
  if (!papers || papers.length === 0) {
    return `<section class="report-section"><h4>${escapeHtml(title)}</h4><p class="muted">None.</p></section>`;
  }
  return `<section class="report-section"><h4>${escapeHtml(title)}</h4><div class="paper-chip-grid">${papers.map(renderPaperChip).join("")}</div></section>`;
}

function renderPaperChip(paper) {
  return `
    <div class="paper-chip">
      <button type="button" data-focus-paper="${escapeHtml(paper.arxiv_id)}">${escapeHtml(paper.title)}</button>
      <div class="paper-chip-meta">${escapeHtml(paper.major_topic)} / ${escapeHtml(paper.minor_topic)} · ${escapeHtml(formatShortDate(paper.published))}</div>
      <div class="paper-chip-meta">${escapeHtml(paper.takeaway)}</div>
    </div>
  `;
}

function hasRenderableMarkdown(markdown) {
  return Boolean(String(markdown || "").trim());
}

function renderStructuredPaperFallback(paper, digest) {
  const blocks = [
    renderFallbackParagraph("一句话概括", digest.one_sentence_takeaway),
    renderFallbackParagraph("论文在做什么", digest.problem),
    renderFallbackParagraph("直觉上为什么成立", digest.background),
    renderFallbackParagraph("方法怎么理解", digest.method),
    renderFallbackParagraph("实验怎么设置", digest.experiment_setup),
    renderFallbackList("实验里最值得关注的点", digest.findings),
    renderFallbackParagraph("这篇论文的价值", digest.relevance),
    renderFallbackList("局限", digest.limitations),
    renderFallbackList("可以怎么优化", digest.improvement_ideas),
    renderFallbackParagraph("摘要", paper.abstract),
  ].filter(Boolean);

  return `
    <div class="detail-section">
      <h4>Summary Snapshot</h4>
      <div class="markdown-preview compact">${blocks.join("")}</div>
    </div>
  `;
}

function renderFallbackParagraph(title, text) {
  const normalized = String(text || "").trim();
  if (!normalized) {
    return "";
  }
  return `<p><strong>${escapeHtml(title)}:</strong> ${escapeHtml(normalized)}</p>`;
}

function renderFallbackList(title, items) {
  const normalized = (items || []).map((item) => String(item || "").trim()).filter(Boolean);
  if (normalized.length === 0) {
    return "";
  }
  return `<div><strong>${escapeHtml(title)}:</strong><ul>${normalized.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></div>`;
}

function renderMarkdownPreview(markdown, options = {}) {
  const rendered = renderMarkdown(markdown);
  if (!rendered) {
    return `<div class="markdown-preview ${options.compact ? "compact" : ""}"><p class="markdown-empty">暂无 Markdown 内容。</p></div>`;
  }
  return `<div class="markdown-preview ${options.compact ? "compact" : ""}">${rendered}</div>`;
}

function renderMarkdown(markdown) {
  const lines = String(markdown || "").replace(/\r\n?/g, "\n").split("\n");
  const html = [];
  let paragraph = [];
  let listItems = [];
  let listType = "";
  let quoteLines = [];
  let codeLines = [];
  let codeFence = false;

  const flushParagraph = () => {
    if (!paragraph.length) {
      return;
    }
    html.push(`<p>${renderInlineMarkdown(paragraph.join(" "))}</p>`);
    paragraph = [];
  };

  const flushList = () => {
    if (!listItems.length || !listType) {
      return;
    }
    html.push(`<${listType}>${listItems.map((item) => `<li>${renderInlineMarkdown(item)}</li>`).join("")}</${listType}>`);
    listItems = [];
    listType = "";
  };

  const flushQuote = () => {
    if (!quoteLines.length) {
      return;
    }
    html.push(`<blockquote><p>${renderInlineMarkdown(quoteLines.join(" "))}</p></blockquote>`);
    quoteLines = [];
  };

  const flushCode = () => {
    if (!codeLines.length && !codeFence) {
      return;
    }
    html.push(`<pre class="markdown-code"><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
    codeLines = [];
  };

  for (const rawLine of lines) {
    const line = rawLine.replace(/\t/g, "  ");
    const trimmed = line.trim();

    if (codeFence) {
      if (trimmed.startsWith("```")) {
        flushCode();
        codeFence = false;
      } else {
        codeLines.push(rawLine);
      }
      continue;
    }

    if (!trimmed) {
      flushParagraph();
      flushList();
      flushQuote();
      continue;
    }

    if (trimmed.startsWith("```")) {
      flushParagraph();
      flushList();
      flushQuote();
      codeFence = true;
      codeLines = [];
      continue;
    }

    const headingMatch = trimmed.match(/^(#{1,6})\s+(.+)$/);
    if (headingMatch) {
      flushParagraph();
      flushList();
      flushQuote();
      const level = headingMatch[1].length;
      html.push(`<h${level}>${renderInlineMarkdown(headingMatch[2])}</h${level}>`);
      continue;
    }

    if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
      flushParagraph();
      flushList();
      flushQuote();
      html.push("<hr>");
      continue;
    }

    const unorderedMatch = line.match(/^\s*[-*+]\s+(.+)$/);
    if (unorderedMatch) {
      flushParagraph();
      flushQuote();
      if (listType && listType !== "ul") {
        flushList();
      }
      listType = "ul";
      listItems.push(unorderedMatch[1].trim());
      continue;
    }

    const orderedMatch = line.match(/^\s*\d+\.\s+(.+)$/);
    if (orderedMatch) {
      flushParagraph();
      flushQuote();
      if (listType && listType !== "ol") {
        flushList();
      }
      listType = "ol";
      listItems.push(orderedMatch[1].trim());
      continue;
    }

    const quoteMatch = line.match(/^\s*>\s?(.*)$/);
    if (quoteMatch) {
      flushParagraph();
      flushList();
      quoteLines.push(quoteMatch[1].trim());
      continue;
    }

    if (quoteLines.length) {
      flushQuote();
    }
    if (listItems.length) {
      flushList();
    }
    paragraph.push(trimmed);
  }

  if (codeFence) {
    flushCode();
  }
  flushParagraph();
  flushList();
  flushQuote();
  return html.join("");
}

function renderInlineMarkdown(text) {
  const placeholders = [];
  const store = (value) => {
    const token = `@@MD${placeholders.length}@@`;
    placeholders.push(value);
    return token;
  };

  let working = String(text || "");
  working = working.replace(/`([^`]+)`/g, (_match, code) => store(`<code>${escapeHtml(code)}</code>`));
  working = working.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_match, label, href) => store(renderMarkdownLink(label, href)));
  working = escapeHtml(working);
  working = working.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  working = working.replace(/__([^_]+)__/g, "<strong>$1</strong>");
  working = working.replace(/(^|[\s(>])\*([^*]+)\*(?=(?:[\s).,!?:;]|$))/g, "$1<em>$2</em>");
  working = working.replace(/(^|[\s(>])_([^_]+)_(?=(?:[\s).,!?:;]|$))/g, "$1<em>$2</em>");

  return working.replace(/@@MD(\d+)@@/g, (_match, indexText) => placeholders[Number(indexText)] || "");
}

function renderMarkdownLink(label, href) {
  const safeHref = sanitizeMarkdownHref(href);
  const safeLabel = escapeHtml(label);
  if (!safeHref) {
    return `<span class="markdown-link-fallback">${safeLabel}</span>`;
  }
  const external = /^(https?:)?\/\//i.test(safeHref);
  const target = external ? ' target="_blank" rel="noreferrer"' : "";
  return `<a href="${escapeHtml(safeHref)}"${target}>${safeLabel}</a>`;
}

function queueMathTypeset(root) {
  if (!root) {
    return;
  }
  mathRenderState.pendingRoots.add(root);
  if (mathRenderState.scheduled) {
    return;
  }
  mathRenderState.scheduled = true;
  window.setTimeout(flushMathTypesetQueue, 0);
}

function flushMathTypesetQueue() {
  mathRenderState.scheduled = false;
  const renderMath = window.renderMathInElement;
  if (typeof renderMath !== "function") {
    if (mathRenderState.pendingRoots.size === 0 || mathRenderState.retryCount >= mathRenderState.maxRetries) {
      mathRenderState.pendingRoots.clear();
      return;
    }
    mathRenderState.retryCount += 1;
    mathRenderState.scheduled = true;
    window.setTimeout(flushMathTypesetQueue, 180);
    return;
  }

  const roots = Array.from(mathRenderState.pendingRoots);
  mathRenderState.pendingRoots.clear();
  mathRenderState.retryCount = 0;

  for (const root of roots) {
    try {
      renderMath(root, {
        throwOnError: false,
        strict: "ignore",
        ignoredTags: ["script", "noscript", "style", "textarea", "pre", "code"],
        delimiters: [
          { left: "$$", right: "$$", display: true },
          { left: "\\[", right: "\\]", display: true },
          { left: "$", right: "$", display: false },
          { left: "\\(", right: "\\)", display: false },
        ],
      });
    } catch (error) {
      // Keep the raw text when math rendering fails on malformed formulas.
    }
  }
}

function sanitizeMarkdownHref(href) {
  const value = String(href || "").trim();
  if (!value) {
    return "";
  }
  if (/^(javascript:|data:)/i.test(value)) {
    return "";
  }
  if (/^(https?:\/\/|mailto:|#|\/)/i.test(value)) {
    return value;
  }
  return "";
}

async function pollJob(jobId) {
  while (true) {
    await sleep(1500);
    try {
      const payload = await api(`/api/tasks/${encodeURIComponent(jobId)}`);
      const job = payload.job;
      updateJobMessage(job);
      updateJobChip();
      if (job.status === "completed") {
        if (job.result && job.result.library) {
          state.library = job.result.library;
          renderAppChrome();
          renderLibrary();
        } else {
          await loadLibrary();
        }
        const firstNew = job.result?.new_papers?.[0] || job.result?.reused_papers?.[0];
        if (firstNew) {
          await selectPaper(firstNew.arxiv_id, { silent: true });
        }
        break;
      }
      if (job.status === "failed") {
        break;
      }
    } catch (error) {
      updateJobMessage({ id: jobId, request: "Task polling failed", status: "failed", error: error.message, notices: [] });
      break;
    }
  }
}

function updateJobMessage(job) {
  const messageId = `job-${job.id}`;
  const index = state.messages.findIndex((item) => item.id === messageId);
  if (index >= 0) {
    const previousJob = state.messages[index].job || { notices: [] };
    const previousCount = Array.isArray(previousJob.notices) ? previousJob.notices.length : 0;
    const nextNotices = Array.isArray(job.notices) ? job.notices : [];
    for (let idx = previousCount; idx < nextNotices.length; idx += 1) {
      showToast(nextNotices[idx].message, nextNotices[idx].level || "warning");
    }
    state.messages[index] = { ...state.messages[index], job };
    renderMessages();
  }
}

function updateJobChip() {
  const activeJobs = state.messages.filter((message) => message.kind === "job" && (message.job.status === "queued" || message.job.status === "running")).length;
  elements.jobChip.textContent = activeJobs > 0 ? `${activeJobs} active` : "Idle";
}

function setSubmitting(isSubmitting) {
  elements.submitButton.disabled = isSubmitting;
  elements.submitButton.textContent = isSubmitting ? "Dispatching..." : "Dispatch to LLM";
}

function showToast(message, level = "warning") {
  if (!elements.toastStack) {
    return;
  }
  const toast = document.createElement("div");
  toast.className = `toast ${level}`;
  toast.textContent = message;
  elements.toastStack.appendChild(toast);
  window.setTimeout(() => {
    toast.remove();
  }, 5200);
}

function firstPaperFromTree(library) {
  for (const major of library.major_topics || []) {
    for (const minor of major.minor_topics || []) {
      if (minor.papers && minor.papers.length) {
        return minor.papers[0];
      }
    }
  }
  return null;
}

function findPaperLocationById(arxivId) {
  if (!arxivId || !state.library) {
    return null;
  }
  for (const major of state.library.major_topics) {
    for (const minor of major.minor_topics) {
      const paper = minor.papers.find((item) => item.arxiv_id === arxivId);
      if (paper) {
        return { major, minor, paper };
      }
    }
  }
  return null;
}

function syncDirectoryFocusToSelection() {
  const location = findPaperLocationById(state.selectedPaperId);
  if (!location) {
    if (!state.activeMajorTopic && state.library?.major_topics?.length) {
      state.activeMajorTopic = state.library.major_topics[0].name;
    }
    if (!state.activeMinorTopic) {
      state.activeMinorTopic = "__all__";
    }
    return;
  }
  state.activeMajorTopic = location.major.name;
  state.activeMinorTopic = location.minor.name;
}

function findPaperSummaryById(arxivId) {
  return findPaperLocationById(arxivId)?.paper || null;
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const contentType = response.headers.get("Content-Type") || "";
  const isJson = contentType.includes("application/json");
  const payload = isJson ? await response.json() : await response.text();
  if (!response.ok) {
    const message = isJson && payload.error ? payload.error : response.statusText;
    throw new Error(message);
  }
  return payload;
}

function formatShortDate(value) {
  if (!value) {
    return "Unknown";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}
