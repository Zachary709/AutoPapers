const state = {
  app: null,
  library: null,
  activeMajorTopic: null,
  activeMinorTopic: "__all__",
  selectedPaperId: null,
  selectedPaper: null,
  selectedPaperRequestId: 0,
  filter: "",
  directorySearchOpen: false,
  settingsModalOpen: false,
  settingsSubmitting: false,
  profileData: null,
  openreviewAuthSubmitting: false,
  confirmationSubmittingByJobId: {},
  cancelSubmittingByJobId: {},
  timelineOpenByJobId: {},
  milestoneNoticeIds: new Set(),
  chatPinnedToBottom: true,
  chatHasUnseenUpdates: false,
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
  composerHeight: "autopapers.layout.composerHeight",
  composerCollapsed: "autopapers.layout.composerCollapsed",
};
const conversationKeys = {
  session: "autopapers.chat.session",
};
const layoutConfig = {
  splitterSize: 14,
  minChatWidth: 300,
  minDirectoryWidth: 360,
  minPreviewWidth: 340,
  collapseThreshold: 188,
  expandThreshold: 240,
  minComposerHeight: 212,
  maxComposerHeight: 420,
  composerCollapseThreshold: 86,
  composerExpandThreshold: 124,
  composerCollapsedHeight: 58,
  chatFollowThreshold: 44,
};
const persistenceConfig = {
  maxMessages: 30,
  maxNoticesPerJob: 120,
  maxReportChars: 24000,
  maxErrorChars: 12000,
};
const layoutState = {
  chatWidth: null,
  previewWidth: null,
  chatCollapsed: false,
  directoryCollapsed: false,
  previewCollapsed: false,
  composerHeight: null,
  composerCollapsed: false,
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
const runtimeState = {
  pollingJobIds: new Set(),
};

document.addEventListener("DOMContentLoaded", async () => {
  bindElements();
  initializeResizableLayout();
  restoreConversationState();
  bindEvents();
  await loadLibrary();
  renderMessages();
  updateJobChip();
  void resumeActiveJobs();
});

function bindElements() {
  elements.appShell = document.getElementById("appShell");
  elements.chatPanel = document.getElementById("chatPanel");
  elements.directoryPanel = document.getElementById("directoryPanel");
  elements.previewPanel = document.getElementById("previewPanel");
  elements.libraryStats = document.getElementById("libraryStats");
  elements.libraryFilter = document.getElementById("libraryFilter");
  elements.directorySearchToggle = document.getElementById("directorySearchToggle");
  elements.directorySearchToggleDot = document.getElementById("directorySearchToggleDot");
  elements.directorySearchPanel = document.getElementById("directorySearchPanel");
  elements.directorySearchClose = document.getElementById("directorySearchClose");
  elements.majorRail = document.getElementById("majorRail");
  elements.libraryBreadcrumb = document.getElementById("libraryBreadcrumb");
  elements.minorTabs = document.getElementById("minorTabs");
  elements.librarySummary = document.getElementById("librarySummary");
  elements.libraryTree = document.getElementById("libraryTree");
  elements.paperDetail = document.getElementById("paperDetail");
  elements.chatDirectorySplitter = document.getElementById("chatDirectorySplitter");
  elements.directoryPreviewSplitter = document.getElementById("directoryPreviewSplitter");
  elements.statusBanner = document.getElementById("statusBanner");
  elements.chatPanelBody = document.getElementById("chatPanelBody");
  elements.chatFeedWrap = document.getElementById("chatFeedWrap");
  elements.chatFeed = document.getElementById("chatFeed");
  elements.jumpLatestButton = document.getElementById("jumpLatestButton");
  elements.chatComposerSplitter = document.getElementById("chatComposerSplitter");
  elements.composerDock = document.getElementById("composerDock");
  elements.composerBody = document.getElementById("composerBody");
  elements.composerDockSummary = document.getElementById("composerDockSummary");
  elements.composerCollapseButton = document.getElementById("composerCollapseButton");
  elements.composerForm = document.getElementById("composerForm");
  elements.promptInput = document.getElementById("promptInput");
  elements.refreshExistingInput = document.getElementById("refreshExistingInput");
  elements.maxResultsInput = document.getElementById("maxResultsInput");
  elements.submitButton = document.getElementById("submitButton");
  elements.modelChip = document.getElementById("modelChip");
  elements.jobChip = document.getElementById("jobChip");
  elements.settingsButton = document.getElementById("settingsButton");
  elements.settingsModal = document.getElementById("settingsModal");
  elements.settingsClose = document.getElementById("settingsClose");
  elements.settingsForm = document.getElementById("settingsForm");
  elements.settingsProfileId = document.getElementById("settingsProfileId");
  elements.settingsProfileName = document.getElementById("settingsProfileName");
  elements.settingsApiKey = document.getElementById("settingsApiKey");
  elements.settingsModel = document.getElementById("settingsModel");
  elements.settingsApiUrl = document.getElementById("settingsApiUrl");
  elements.settingsProxy = document.getElementById("settingsProxy");
  elements.settingsSave = document.getElementById("settingsSave");
  elements.settingsNewProfile = document.getElementById("settingsNewProfile");
  elements.settingsDeleteProfile = document.getElementById("settingsDeleteProfile");
  elements.profileList = document.getElementById("profileList");
  elements.openreviewAuthForm = document.getElementById("openreviewAuthForm");
  elements.openreviewUsernameInput = document.getElementById("openreviewUsernameInput");
  elements.openreviewPasswordInput = document.getElementById("openreviewPasswordInput");
  elements.openreviewLoginSubmit = document.getElementById("openreviewLoginSubmit");
  elements.openreviewLogoutButton = document.getElementById("openreviewLogoutButton");
  elements.openreviewAuthStatusCopy = document.getElementById("openreviewAuthStatusCopy");
  elements.toastStack = document.getElementById("toastStack");
}

function bindEvents() {
  elements.libraryFilter.addEventListener("input", (event) => {
    state.filter = event.target.value.trim().toLowerCase();
    syncDirectorySearchUI();
    renderLibrary();
  });

  elements.directorySearchToggle.addEventListener("click", () => {
    setDirectorySearchOpen(!state.directorySearchOpen, { focusInput: !state.directorySearchOpen });
  });

  elements.directorySearchClose.addEventListener("click", () => {
    setDirectorySearchOpen(false, { restoreFocus: true });
  });

  elements.settingsButton.addEventListener("click", () => {
    setSettingsModalOpen(true);
  });

  elements.settingsClose.addEventListener("click", () => {
    setSettingsModalOpen(false);
  });

  elements.settingsModal.addEventListener("click", (event) => {
    if (event.target === elements.settingsModal) {
      setSettingsModalOpen(false);
    }
  });

  elements.settingsForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    await saveProfile();
  });

  elements.settingsNewProfile.addEventListener("click", () => {
    clearProfileForm();
  });

  elements.settingsDeleteProfile.addEventListener("click", async () => {
    await deleteProfile();
  });

  elements.profileList.addEventListener("click", (event) => {
    const pill = event.target.closest("[data-profile-id]");
    if (!pill || !elements.profileList.contains(pill)) {
      return;
    }
    const profileId = pill.getAttribute("data-profile-id");
    handleProfileClick(profileId);
  });

  elements.openreviewAuthForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    await submitOpenReviewLogin();
  });

  elements.openreviewLogoutButton.addEventListener("click", async () => {
    await logoutOpenReview();
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

  elements.chatFeed.addEventListener("scroll", () => {
    refreshChatPinState();
  });

  elements.jumpLatestButton.addEventListener("click", () => {
    scrollChatFeedToBottom({ smooth: true });
    state.chatPinnedToBottom = true;
    state.chatHasUnseenUpdates = false;
    updateJumpLatestButton();
  });

  elements.composerCollapseButton.addEventListener("click", () => {
    toggleComposerCollapsed();
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
    }, { forceBottom: true });

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
      }, { forceBottom: true });
      elements.promptInput.value = "";
      pollJob(response.job.id);
    } catch (error) {
      appendMessage({
        id: `error-${Date.now()}`,
        kind: "error",
        role: "assistant",
        text: error.message,
      }, { forceBottom: true });
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

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.settingsModalOpen) {
      setSettingsModalOpen(false);
      return;
    }
    if (event.key !== "Escape" || !state.directorySearchOpen) {
      return;
    }
    setDirectorySearchOpen(false, { restoreFocus: true });
  });

  document.addEventListener("click", (event) => {
    if (!state.directorySearchOpen) {
      return;
    }
    const target = event.target;
    if (
      elements.directorySearchPanel.contains(target)
      || elements.directorySearchToggle.contains(target)
    ) {
      return;
    }
    setDirectorySearchOpen(false);
  });
}

function initializeResizableLayout() {
  loadStoredLayoutState();
  syncShellLayout({ persist: false });
  bindResizableSplitters();
  syncComposerLayout({ persist: false });
  window.addEventListener("resize", () => {
    syncShellLayout({ persist: false });
    syncComposerLayout({ persist: false });
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

  bindDragSplitter(elements.chatComposerSplitter, {
    axis: "y",
    bodyClass: "is-resizing-row",
    getStartValue: () => getCurrentComposerHeight(),
    applyDelta: (startValue, delta) => setComposerHeight(startValue - delta),
    step: 24,
    onKeyAdjust: (delta) => setComposerHeight(getCurrentComposerHeight() - delta),
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
  layoutState.composerHeight = readStoredNumber(layoutKeys.composerHeight);
  layoutState.composerCollapsed = readStoredBoolean(layoutKeys.composerCollapsed, false);
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
  syncComposerLayout({ persist: false });
  if (persist) {
    persistLayoutState();
  }
}

function syncComposerLayout({ persist = true } = {}) {
  if (!elements.composerDock || !elements.chatComposerSplitter) {
    return;
  }

  const collapsed = Boolean(layoutState.composerCollapsed);
  elements.composerDock.classList.toggle("is-composer-collapsed", collapsed);
  elements.composerBody.setAttribute("aria-hidden", collapsed ? "true" : "false");
  elements.composerCollapseButton.textContent = collapsed ? "Expand" : "Collapse";
  elements.composerCollapseButton.setAttribute("aria-expanded", collapsed ? "false" : "true");
  elements.composerDockSummary.textContent = collapsed
    ? "输入区已折叠，展开后继续编辑 prompt。"
    : "输入任务、设置参数，并把执行请求发给模型。";

  if (!isDesktopLayout()) {
    elements.chatComposerSplitter.classList.add("hidden");
    elements.composerDock.style.removeProperty("height");
    if (persist) {
      persistLayoutState();
    }
    return;
  }

  elements.chatComposerSplitter.classList.toggle("hidden", collapsed);

  if (!collapsed) {
    const desiredHeight = clamp(
      layoutState.composerHeight ?? getDefaultComposerHeight(),
      layoutConfig.minComposerHeight,
      getComposerMaxHeight()
    );
    layoutState.composerHeight = desiredHeight;
    elements.composerDock.style.height = `${desiredHeight}px`;
  } else {
    elements.composerDock.style.height = `${layoutConfig.composerCollapsedHeight}px`;
  }

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

function getCurrentComposerHeight() {
  if (layoutState.composerCollapsed) {
    return layoutConfig.composerCollapsedHeight;
  }
  return clamp(
    layoutState.composerHeight ?? getDefaultComposerHeight(),
    layoutConfig.minComposerHeight,
    getComposerMaxHeight()
  );
}

function getDefaultComposerHeight() {
  const panelHeight = elements.chatPanel?.clientHeight || window.innerHeight;
  return clamp(Math.round(panelHeight * 0.28), layoutConfig.minComposerHeight, layoutConfig.maxComposerHeight);
}

function getComposerMaxHeight() {
  const panelHeight = elements.chatPanel?.clientHeight || window.innerHeight;
  return Math.max(layoutConfig.minComposerHeight, Math.min(layoutConfig.maxComposerHeight, Math.round(panelHeight * 0.52)));
}

function setComposerHeight(height, { persist = true } = {}) {
  const desired = Math.max(0, Number(height) || 0);
  if (!isDesktopLayout()) {
    syncComposerLayout({ persist });
    return;
  }

  if (layoutState.composerCollapsed) {
    if (desired < layoutConfig.composerExpandThreshold) {
      syncComposerLayout({ persist });
      return;
    }
    layoutState.composerCollapsed = false;
  } else if (desired < layoutConfig.composerCollapseThreshold) {
    layoutState.composerCollapsed = true;
    syncComposerLayout({ persist });
    return;
  }

  layoutState.composerHeight = clamp(desired, layoutConfig.minComposerHeight, getComposerMaxHeight());
  syncComposerLayout({ persist });
}

function toggleComposerCollapsed() {
  layoutState.composerCollapsed = !layoutState.composerCollapsed;
  if (!layoutState.composerCollapsed && !layoutState.composerHeight) {
    layoutState.composerHeight = getDefaultComposerHeight();
  }
  syncComposerLayout({ persist: true });
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
  persistLayoutValue(layoutKeys.composerHeight, layoutState.composerHeight ?? getDefaultComposerHeight());
  persistLayoutValue(layoutKeys.composerCollapsed, layoutState.composerCollapsed);
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

function restoreConversationState() {
  try {
    const raw = window.localStorage.getItem(conversationKeys.session);
    if (!raw) {
      return;
    }
    const payload = JSON.parse(raw);
    if (Array.isArray(payload.messages) && payload.messages.length) {
      const restoredMessages = payload.messages.filter((message) => message && typeof message === "object" && message.kind);
      if (restoredMessages.length) {
        state.messages = restoredMessages;
      }
    }
    if (payload.selectedPaperId) {
      state.selectedPaperId = String(payload.selectedPaperId);
    }
    if (payload.timelineOpenByJobId && typeof payload.timelineOpenByJobId === "object") {
      state.timelineOpenByJobId = payload.timelineOpenByJobId;
    }
  } catch (error) {
    // Ignore invalid stored chat state and start from defaults.
  }
}

function persistConversationState() {
  try {
    const payload = {
      messages: state.messages.slice(-persistenceConfig.maxMessages).map(serializeMessageForStorage).filter(Boolean),
      selectedPaperId: state.selectedPaperId,
      timelineOpenByJobId: state.timelineOpenByJobId,
    };
    window.localStorage.setItem(conversationKeys.session, JSON.stringify(payload));
  } catch (error) {
    // Ignore storage errors and keep the current in-memory session.
  }
}

function serializeMessageForStorage(message) {
  if (!message || typeof message !== "object") {
    return null;
  }
  if (message.kind !== "job") {
    return {
      id: message.id,
      kind: message.kind,
      role: message.role,
      text: message.text,
    };
  }
  return {
    id: message.id,
    kind: message.kind,
    role: message.role,
    job: compactJobForStorage(message.job),
  };
}

function compactJobForStorage(job) {
  if (!job || typeof job !== "object") {
    return job;
  }
  const compact = JSON.parse(JSON.stringify(job));
  if (Array.isArray(compact.notices) && compact.notices.length > persistenceConfig.maxNoticesPerJob) {
    compact.notices = compact.notices.slice(-persistenceConfig.maxNoticesPerJob);
  }
  if (compact.error) {
    compact.error = String(compact.error).slice(0, persistenceConfig.maxErrorChars);
  }
  if (compact.result && typeof compact.result === "object") {
    delete compact.result.library;
    if (compact.result.report_markdown) {
      compact.result.report_markdown = String(compact.result.report_markdown).slice(0, persistenceConfig.maxReportChars);
    }
  }
  return compact;
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

function renderAppChrome() {
  elements.modelChip.textContent = state.app?.model || "Unknown model";
  renderSettingsButtonState();
  if (!state.app?.api_key_configured) {
    elements.statusBanner.classList.remove("hidden");
    elements.statusBanner.textContent = "当前未配置 API Key。点击 Settings 按钮进行配置。";
  } else {
    elements.statusBanner.classList.add("hidden");
    elements.statusBanner.textContent = "";
  }
  updateJobChip();
  renderStats();
  syncDirectorySearchUI();
}

function renderSettingsButtonState() {
  const apiKeyConfigured = Boolean(state.app?.api_key_configured);
  const openreviewStatus = state.app?.openreview || {};
  const orAuthenticated = Boolean(openreviewStatus.authenticated);
  elements.settingsButton.classList.remove("chip-active", "chip-warning", "chip-disabled");
  if (!apiKeyConfigured) {
    elements.settingsButton.classList.add("chip-warning");
  } else if (orAuthenticated) {
    elements.settingsButton.classList.add("chip-active");
  }
  elements.settingsButton.disabled = false;
  renderOpenReviewAuthState();
}

function renderOpenReviewAuthState() {
  const status = state.app?.openreview || {};
  const authenticated = Boolean(status.authenticated);
  const available = status.available !== false;
  if (!available) {
    elements.openreviewAuthStatusCopy.textContent = "当前环境未安装 OpenReview 客户端。";
    elements.openreviewLogoutButton.disabled = true;
    return;
  }
  elements.openreviewAuthStatusCopy.textContent = authenticated
    ? `当前已登录：${status.username || "unknown"}。登录 token 已保存在本地。`
    : "登录后会把 token 保存到本地，仅当前机器使用。";
  elements.openreviewLogoutButton.disabled = !authenticated || state.openreviewAuthSubmitting;
  elements.openreviewLoginSubmit.disabled = state.openreviewAuthSubmitting;
}

function setSettingsModalOpen(isOpen) {
  state.settingsModalOpen = Boolean(isOpen);
  elements.settingsModal.classList.toggle("hidden", !state.settingsModalOpen);
  elements.settingsModal.setAttribute("aria-hidden", state.settingsModalOpen ? "false" : "true");
  if (state.settingsModalOpen) {
    void loadSettingsForm();
    window.setTimeout(() => {
      elements.settingsApiKey?.focus();
    }, 0);
  }
}

async function loadSettingsForm() {
  try {
    const payload = await api("/api/settings");
    state.profileData = payload;
    renderProfileList();
    state.app = state.app || {};
    state.app.openreview = payload.openreview;
    renderOpenReviewAuthState();
    const activeId = payload.active_profile;
    if (activeId && payload.profiles[activeId]) {
      loadProfileIntoForm(activeId, payload.profiles[activeId]);
    } else {
      clearProfileForm();
    }
  } catch (error) {
    showToast("加载设置失败：" + error.message, "warning");
  }
}

function renderProfileList() {
  const data = state.profileData || {};
  const profiles = data.profiles || {};
  const activeId = data.active_profile || "";
  const editingId = elements.settingsProfileId.value || "";
  if (!Object.keys(profiles).length) {
    elements.profileList.innerHTML = `<span class="muted">尚未保存任何 API 配置。</span>`;
    return;
  }
  elements.profileList.innerHTML = Object.entries(profiles).map(([id, p]) => {
    const classes = ["profile-pill"];
    if (id === activeId) classes.push("active");
    if (id === editingId) classes.push("editing");
    return `<button class="${classes.join(" ")}" type="button" data-profile-id="${escapeHtml(id)}"><span class="profile-pill-dot"></span><span class="profile-pill-name">${escapeHtml(p.name || p.model || "Unnamed")}</span></button>`;
  }).join("");
}

function loadProfileIntoForm(id, profile) {
  elements.settingsProfileId.value = id;
  elements.settingsProfileName.value = profile.name || "";
  elements.settingsApiKey.value = "";
  elements.settingsApiKey.placeholder = profile.api_key_masked
    ? `${profile.api_key_masked}（留空保持不变）`
    : "API Key";
  elements.settingsModel.value = profile.model || "";
  elements.settingsApiUrl.value = profile.api_url || "";
  elements.settingsProxy.value = profile.network_proxy_url || "";
  renderProfileList();
}

function clearProfileForm() {
  elements.settingsProfileId.value = "";
  elements.settingsProfileName.value = "";
  elements.settingsApiKey.value = "";
  elements.settingsApiKey.placeholder = "API Key";
  elements.settingsModel.value = "";
  elements.settingsApiUrl.value = "";
  elements.settingsProxy.value = "";
  renderProfileList();
}

async function handleProfileClick(profileId) {
  const data = state.profileData || {};
  const profiles = data.profiles || {};
  const profile = profiles[profileId];
  if (!profile) {
    return;
  }
  const activeId = data.active_profile || "";
  if (profileId === activeId) {
    loadProfileIntoForm(profileId, profile);
    return;
  }
  await activateProfile(profileId);
}

async function activateProfile(profileId) {
  if (state.settingsSubmitting) {
    return;
  }
  const data = state.profileData || {};
  const profile = (data.profiles || {})[profileId];
  if (!profile) {
    return;
  }
  state.settingsSubmitting = true;
  elements.settingsSave.disabled = true;
  try {
    const result = await api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "activate", profile_id: profileId }),
    });
    state.profileData = result.profiles_data;
    state.app = result.app;
    const activeProfile = result.profiles_data?.profiles?.[profileId];
    if (activeProfile) {
      loadProfileIntoForm(profileId, activeProfile);
    } else {
      renderProfileList();
    }
    renderAppChrome();
    showToast(`已切换到「${profile.name || profile.model || "Unnamed"}」。`, "info");
  } catch (error) {
    showToast("切换失败：" + error.message, "warning");
  } finally {
    state.settingsSubmitting = false;
    elements.settingsSave.disabled = false;
  }
}

async function saveProfile() {
  if (state.settingsSubmitting) {
    return;
  }
  const editingId = elements.settingsProfileId.value || "";
  const currentProfile = editingId ? (state.profileData?.profiles || {})[editingId] : null;
  const hasStoredApiKey = Boolean(currentProfile?.api_key_masked);
  const name = elements.settingsProfileName.value.trim();
  const apiKey = elements.settingsApiKey.value;
  const model = elements.settingsModel.value.trim();
  const apiUrl = elements.settingsApiUrl.value.trim();
  const proxy = elements.settingsProxy.value.trim();
  if (!apiKey && !hasStoredApiKey && !model && !apiUrl) {
    showToast("请至少填写 API Key 或 Model。", "warning");
    return;
  }
  state.settingsSubmitting = true;
  elements.settingsSave.disabled = true;
  try {
    const result = await api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        action: "save",
        profile_id: elements.settingsProfileId.value || null,
        profile: { name, api_key: apiKey, model, api_url: apiUrl, network_proxy_url: proxy },
      }),
    });
    state.profileData = result.profiles_data;
    state.app = result.app;
    renderProfileList();
    if (result.saved_id && result.profiles_data.profiles[result.saved_id]) {
      loadProfileIntoForm(result.saved_id, result.profiles_data.profiles[result.saved_id]);
    }
    renderAppChrome();
    showToast("配置已保存并激活。", "info");
  } catch (error) {
    showToast("保存失败：" + error.message, "warning");
  } finally {
    state.settingsSubmitting = false;
    elements.settingsSave.disabled = false;
  }
}

async function deleteProfile() {
  const profileId = elements.settingsProfileId.value;
  if (!profileId) {
    showToast("请先选择一个配置。", "warning");
    return;
  }
  const name = elements.settingsProfileName.value || "该配置";
  if (!window.confirm(`确定删除「${name}」？`)) {
    return;
  }
  if (state.settingsSubmitting) {
    return;
  }
  state.settingsSubmitting = true;
  try {
    const result = await api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "delete", profile_id: profileId }),
    });
    state.profileData = result.profiles_data;
    state.app = result.app;
    const newActiveId = result.profiles_data.active_profile;
    if (newActiveId && result.profiles_data.profiles[newActiveId]) {
      loadProfileIntoForm(newActiveId, result.profiles_data.profiles[newActiveId]);
    } else {
      clearProfileForm();
    }
    renderAppChrome();
    showToast("配置已删除。", "info");
  } catch (error) {
    showToast("删除失败：" + error.message, "warning");
  } finally {
    state.settingsSubmitting = false;
  }
}

async function submitOpenReviewLogin() {
  if (state.openreviewAuthSubmitting) {
    return;
  }
  const username = elements.openreviewUsernameInput.value.trim();
  const password = elements.openreviewPasswordInput.value;
  if (!username || !password) {
    showToast("请输入 OpenReview 用户名和密码。", "warning");
    return;
  }
  state.openreviewAuthSubmitting = true;
  renderOpenReviewAuthState();
  try {
    const payload = await api("/api/openreview/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    state.app = payload.app;
    elements.openreviewPasswordInput.value = "";
    elements.openreviewUsernameInput.value = "";
    renderAppChrome();
    showToast("OpenReview 登录成功。", "info");
  } catch (error) {
    showToast(error.message, "warning");
  } finally {
    state.openreviewAuthSubmitting = false;
    renderOpenReviewAuthState();
  }
}

async function logoutOpenReview() {
  if (state.openreviewAuthSubmitting) {
    return;
  }
  state.openreviewAuthSubmitting = true;
  renderOpenReviewAuthState();
  try {
    const payload = await api("/api/openreview/logout", { method: "POST" });
    state.app = payload.app;
    elements.openreviewPasswordInput.value = "";
    renderAppChrome();
    showToast("OpenReview 已退出登录。", "info");
  } catch (error) {
    showToast(error.message, "warning");
  } finally {
    state.openreviewAuthSubmitting = false;
    renderOpenReviewAuthState();
  }
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

function setDirectorySearchOpen(isOpen, options = {}) {
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

function syncDirectorySearchUI() {
  const hasFilter = Boolean(state.filter);
  elements.directorySearchPanel.classList.toggle("hidden", !state.directorySearchOpen);
  elements.directorySearchToggle.classList.toggle("active", state.directorySearchOpen || hasFilter);
  elements.directorySearchToggle.setAttribute("aria-expanded", state.directorySearchOpen ? "true" : "false");
  elements.directorySearchToggleDot.classList.toggle("hidden", !hasFilter);
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

async function selectPaper(paperId, { silent = false } = {}) {
  if (!paperId) {
    state.selectedPaperId = null;
    state.selectedPaper = null;
    state.selectedPaperRequestId += 1;
    persistConversationState();
    renderPaperDetail();
    return;
  }

  const requestId = state.selectedPaperRequestId + 1;
  state.selectedPaperRequestId = requestId;
  state.selectedPaperId = paperId;
  state.selectedPaper = null;
  persistConversationState();
  syncDirectoryFocusToSelection();
  if (!silent) {
    renderLibrary();
  }
  renderPaperDetailLoading();

  try {
    const detail = await api(`/api/papers/${encodeURIComponent(paperId)}`);
    if (requestId !== state.selectedPaperRequestId || state.selectedPaperId !== paperId) {
      return;
    }
    state.selectedPaper = detail;
    renderPaperDetail();
  } catch (error) {
    if (requestId !== state.selectedPaperRequestId || state.selectedPaperId !== paperId) {
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

  const { summary, paper, digest, download_urls, markdown_content, metadata_refresh } = state.selectedPaper;
  const sourceLinks = [
    paper.entry_url || paper.entry_id ? `<a class="button-link" href="${escapeHtmlAttribute(paper.entry_url || paper.entry_id)}" target="_blank" rel="noreferrer">Open Source</a>` : "",
    paper.openreview_url ? `<a class="button-link" href="${escapeHtmlAttribute(paper.openreview_url)}" target="_blank" rel="noreferrer">OpenReview</a>` : "",
    paper.scholar_url ? `<a class="button-link" href="${escapeHtmlAttribute(paper.scholar_url)}" target="_blank" rel="noreferrer">Scholar</a>` : "",
  ].filter(Boolean).join("");
  const pdfButton = download_urls.pdf ? `<a class="button-link" href="${download_urls.pdf}" target="_blank" rel="noreferrer">Open PDF</a>` : "";
  const venueMeta = renderVenueMeta(summary.venue);
  const citationMeta = typeof summary.citation_count === "number"
    ? `<span>Cited ${escapeHtml(String(summary.citation_count))}</span>`
    : "";
  const detailBody = hasRenderableMarkdown(markdown_content)
    ? `<div class="detail-section"><h4>Note Preview</h4>${renderMarkdownPreview(markdown_content)}</div>`
    : renderStructuredPaperFallback(paper, digest);
  const metadataRefreshPanel = renderMetadataRefreshPanel(metadata_refresh);

  elements.paperDetail.innerHTML = `
    <article class="detail-card">
      <div>
        <div class="eyebrow">${escapeHtml(summary.major_topic)} / ${escapeHtml(summary.minor_topic)}</div>
        <h3>${escapeHtml(summary.title)}</h3>
        <div class="paper-meta"><span>${escapeHtml(summary.source_primary || "unknown")}</span><span>${escapeHtml(summary.versioned_id || summary.paper_id || "")}</span><span>${escapeHtml(formatShortDate(summary.published))}</span></div>
        <div class="paper-meta">${venueMeta}${citationMeta}</div>
      </div>
      <div class="detail-actions">
        ${pdfButton}
        ${sourceLinks}
        <a class="button-link" href="${download_urls.markdown}" target="_blank" rel="noreferrer">Open Note</a>
        <button class="button-link ghost-button" type="button" id="refreshMetadataButton">Refresh Metadata</button>
        <button class="danger-button" type="button" id="deletePaperButton">Delete Paper</button>
      </div>
      <div class="tag-row">${(digest.keywords || []).map((item) => `<span class="tag">${escapeHtml(item)}</span>`).join("")}</div>
      ${metadataRefreshPanel}
      ${detailBody}
    </article>
  `;

  const deleteButton = document.getElementById("deletePaperButton");
  if (deleteButton) {
    deleteButton.addEventListener("click", () => void deletePaper(summary.paper_id, summary.title));
  }
  const refreshButton = document.getElementById("refreshMetadataButton");
  if (refreshButton) {
    refreshButton.addEventListener("click", () => void refreshSelectedPaperMetadata(summary.paper_id));
  }
  queueMathTypeset(elements.paperDetail);
}

async function deletePaper(paperId, title) {
  const confirmed = window.confirm(`确定删除这篇论文及其本地文件？\n\n${title}`);
  if (!confirmed) {
    return;
  }

  try {
    const payload = await api(`/api/papers/${encodeURIComponent(paperId)}`, { method: "DELETE" });
    if (state.selectedPaperId === paperId) {
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

async function refreshSelectedPaperMetadata(paperId) {
  if (!paperId) {
    return;
  }
  try {
    const payload = await api(`/api/papers/${encodeURIComponent(paperId)}/refresh-metadata`, { method: "POST" });
    state.selectedPaper = payload.detail;
    state.app = payload.app;
    state.library = payload.library;
    renderAppChrome();
    renderLibrary();
    renderPaperDetail();
    appendMessage({
      id: `metadata-refresh-${Date.now()}`,
      kind: "text",
      role: "assistant",
      text: payload.detail.metadata_refresh?.message || `已刷新论文元数据：${payload.detail.summary.title}`,
    });
  } catch (error) {
    appendMessage({ id: `metadata-refresh-error-${Date.now()}`, kind: "error", role: "assistant", text: error.message });
  }
}

async function respondToJobConfirmation(jobId, confirmationId, approved) {
  if (!jobId || !confirmationId || state.confirmationSubmittingByJobId[jobId]) {
    return;
  }
  state.confirmationSubmittingByJobId[jobId] = true;
  renderMessages();
  let confirmed = false;
  try {
    const payload = await api(`/api/tasks/${encodeURIComponent(jobId)}/confirmation`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirmation_id: confirmationId, approved }),
    });
    confirmed = true;
    updateJobMessage(payload.job);
  } catch (error) {
    appendMessage({ id: `confirm-error-${Date.now()}`, kind: "error", role: "assistant", text: error.message });
  } finally {
    if (!confirmed) {
      delete state.confirmationSubmittingByJobId[jobId];
    }
    renderMessages();
  }
}

async function cancelJob(jobId) {
  if (!jobId || state.cancelSubmittingByJobId[jobId]) {
    return;
  }
  state.cancelSubmittingByJobId[jobId] = true;
  renderMessages();
  let acknowledged = false;
  try {
    const payload = await api(`/api/tasks/${encodeURIComponent(jobId)}/cancel`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    acknowledged = true;
    updateJobMessage(payload.job);
    updateJobChip();
  } catch (error) {
    appendMessage({
      id: `cancel-error-${Date.now()}`,
      kind: "error",
      role: "assistant",
      text: describeTaskApiError(error, "停止任务失败"),
    });
  } finally {
    if (!acknowledged) {
      delete state.cancelSubmittingByJobId[jobId];
    }
    renderMessages();
  }
}

function appendMessage(message, options = {}) {
  state.messages.push(message);
  persistConversationState();
  renderMessages({ newContent: true, forceBottom: Boolean(options.forceBottom) });
}

function renderMessages({ newContent = false, forceBottom = false } = {}) {
  const previousScrollTop = elements.chatFeed?.scrollTop || 0;
  const wasPinned = state.chatPinnedToBottom;
  elements.chatFeed.innerHTML = state.messages.map(renderMessage).join("");
  elements.chatFeed.querySelectorAll("[data-focus-paper]").forEach((button) => {
    button.addEventListener("click", () => void selectPaper(button.getAttribute("data-focus-paper")));
  });
  elements.chatFeed.querySelectorAll("[data-job-confirm]").forEach((button) => {
    button.addEventListener("click", () => {
      const jobId = button.getAttribute("data-job-id");
      const confirmationId = button.getAttribute("data-confirmation-id");
      const approved = button.getAttribute("data-job-confirm") === "approve";
      void respondToJobConfirmation(jobId, confirmationId, approved);
    });
  });
  elements.chatFeed.querySelectorAll("[data-job-stop]").forEach((button) => {
    button.addEventListener("click", () => {
      const jobId = button.getAttribute("data-job-stop");
      void cancelJob(jobId);
    });
  });
  elements.chatFeed.querySelectorAll("[data-job-timeline]").forEach((timeline) => {
    timeline.addEventListener("toggle", () => {
      state.timelineOpenByJobId[timeline.getAttribute("data-job-timeline")] = timeline.open;
      persistConversationState();
    });
  });
  queueMathTypeset(elements.chatFeed);
  if (forceBottom || wasPinned) {
    scrollChatFeedToBottom();
    state.chatPinnedToBottom = true;
    state.chatHasUnseenUpdates = false;
  } else {
    const nextScrollTop = Math.max(
      0,
      Math.min(previousScrollTop, elements.chatFeed.scrollHeight - elements.chatFeed.clientHeight)
    );
    elements.chatFeed.scrollTop = nextScrollTop;
    if (newContent) {
      state.chatHasUnseenUpdates = true;
    }
  }
  updateJumpLatestButton();
  persistConversationState();
}

function renderMessage(message) {
  if (message.kind === "intro" || message.kind === "text") {
    return `<article class="message ${escapeHtml(message.role)}"><div class="message-title"><strong>${message.role === "user" ? "You" : "Assistant"}</strong></div><pre>${escapeHtml(message.text)}</pre></article>`;
  }
  if (message.kind === "milestone") {
    return `<article class="message assistant milestone"><div class="message-title"><strong>Progress Update</strong></div><p>${escapeHtml(message.text)}</p></article>`;
  }
  if (message.kind === "error") {
    return `<article class="message assistant error"><div class="message-title"><strong>Task Failed</strong></div><pre>${escapeHtml(message.text)}</pre></article>`;
  }
  if (message.kind === "job") {
    const job = message.job;
    if (job.status === "completed") {
      return renderCompletedJob(job);
    }
    if (job.status === "cancelled") {
      return renderCancelledJob(job);
    }
    if (job.status === "failed") {
      return renderFailedJob(job);
    }
    return renderActiveJob(job);
  }
  return "";
}

function scrollChatFeedToBottom({ smooth = false } = {}) {
  if (!elements.chatFeed) {
    return;
  }
  elements.chatFeed.scrollTo({
    top: elements.chatFeed.scrollHeight,
    behavior: smooth ? "smooth" : "auto",
  });
}

function isChatFeedNearBottom() {
  if (!elements.chatFeed) {
    return true;
  }
  const remaining = elements.chatFeed.scrollHeight - elements.chatFeed.scrollTop - elements.chatFeed.clientHeight;
  return remaining <= layoutConfig.chatFollowThreshold;
}

function refreshChatPinState() {
  const pinned = isChatFeedNearBottom();
  state.chatPinnedToBottom = pinned;
  if (pinned) {
    state.chatHasUnseenUpdates = false;
  }
  updateJumpLatestButton();
}

function updateJumpLatestButton() {
  if (!elements.jumpLatestButton) {
    return;
  }
  const shouldShow = !state.chatPinnedToBottom && state.chatHasUnseenUpdates;
  elements.jumpLatestButton.classList.toggle("hidden", !shouldShow);
}

function renderActiveJob(job) {
  const progress = normalizeJobProgress(job);
  const heading = job.cancel_requested
    ? "Stopping Task"
    : job.status === "awaiting_confirmation"
      ? "Need Confirmation"
      : job.status === "queued"
        ? "Queued Task"
        : "Running Task";
  return `
    <article class="message assistant job-message">
      <div class="message-title"><strong>${heading}</strong><span class="chip">${escapeHtml(progress.label)}</span></div>
      <div class="job-meta">${escapeHtml(job.request)}</div>
      ${renderJobProgressPanel(job, { timelineOpen: true })}
    </article>
  `;
}

function renderCancelledJob(job) {
  const progress = normalizeJobProgress(job);
  return `
    <article class="message assistant job-message">
      <div class="message-title"><strong>Task Stopped</strong><span class="chip">${escapeHtml(progress.label)}</span></div>
      <div class="job-meta">${escapeHtml(job.request)}</div>
      ${renderJobProgressPanel(job, { timelineOpen: true })}
      <pre>${escapeHtml(job.error || "Task stopped by user decision.")}</pre>
    </article>
  `;
}

function renderFailedJob(job) {
  const progress = normalizeJobProgress(job);
  return `
    <article class="message assistant error job-message">
      <div class="message-title"><strong>Task Failed</strong><span class="chip">${escapeHtml(progress.label)}</span></div>
      <div class="job-meta">${escapeHtml(job.request)}</div>
      ${renderJobProgressPanel(job, { timelineOpen: true })}
      <pre>${escapeHtml(job.error || "Unknown error")}</pre>
    </article>
  `;
}

function renderCompletedJob(job) {
  const result = job.result;
  const progress = normalizeJobProgress(job);
  return `
    <article class="message assistant job-message">
      <div class="message-title"><strong>Task Completed</strong><span class="chip">${escapeHtml(result.plan.intent)}</span></div>
      <div class="job-meta">${escapeHtml(job.request)}</div>
      ${renderJobProgressPanel(job, { timelineOpen: false, progress })}
      <section class="report-section"><h4>Plan</h4><p>${escapeHtml(result.plan.user_goal)}</p></section>
      ${renderPaperSection("New / Refreshed Papers", result.new_papers)}
      ${renderPaperSection("Reused Local Papers", result.reused_papers)}
      ${renderPaperSection("Related Local Papers", result.related_papers)}
      <section class="report-section"><h4>Report Preview</h4>${renderMarkdownPreview(result.report_markdown, { compact: true })}</section>
    </article>
  `;
}

function renderJobProgressPanel(job, options = {}) {
  const progress = options.progress || normalizeJobProgress(job);
  const percentLabel = progress.indeterminate ? "..." : `${progress.percent}%`;
  const stageMeta = renderProgressMeta(progress, job);
  const currentTitle = progress.current_title
    ? `<div class="job-current-paper"><span class="job-progress-caption">Current Paper</span><strong>${escapeHtml(progress.current_title)}</strong></div>`
    : "";
  return `
    <section class="job-progress-panel">
      <div class="job-progress-header">
        <div>
          <div class="job-progress-caption">Current Stage</div>
          <div class="job-stage-label">${escapeHtml(progress.label)}</div>
        </div>
        <div class="job-progress-percent">${escapeHtml(percentLabel)}</div>
      </div>
      <div class="job-progress-track ${progress.indeterminate ? "is-indeterminate" : ""}">
        <span style="width: ${Math.max(0, Math.min(progress.percent, 100))}%"></span>
      </div>
      <div class="job-progress-detail">${escapeHtml(progress.detail)}</div>
      ${stageMeta}
      ${currentTitle}
      ${renderJobActionPanel(job)}
      ${renderConfirmationPanel(job)}
      ${renderNoticeSection(job.notices, { title: "Execution Timeline", open: options.timelineOpen, jobId: job.id })}
    </section>
  `;
}

function renderJobActionPanel(job) {
  if (job.status !== "queued" && job.status !== "running") {
    return "";
  }
  const busy = Boolean(state.cancelSubmittingByJobId[job.id]) || Boolean(job.cancel_requested);
  const label = busy ? "Stopping..." : "Stop Task";
  return `
    <div class="job-action-row">
      <button class="danger-button job-stop-button" type="button" data-job-stop="${escapeHtml(job.id)}" ${busy ? "disabled" : ""}>${label}</button>
    </div>
  `;
}

function renderConfirmationPanel(job) {
  const confirmation = job.confirmation;
  if (!confirmation || job.status !== "awaiting_confirmation") {
    return "";
  }
  const busy = Boolean(state.confirmationSubmittingByJobId[job.id]);
  const similarityLabel = Number.isFinite(Number(confirmation.similarity_score))
    ? Number(confirmation.similarity_score).toFixed(2)
    : "--";
  return `
    <section class="job-confirmation-panel">
      <div class="job-confirmation-eyebrow">Low Similarity Match</div>
      <p class="job-confirmation-prompt">${escapeHtml(confirmation.prompt || "")}</p>
      <div class="job-confirmation-grid">
        <div><strong>Requested</strong><span>${escapeHtml(confirmation.requested_title || "")}</span></div>
        <div><strong>Candidate</strong><span>${escapeHtml(confirmation.candidate_title || "")}</span></div>
        <div><strong>Source</strong><span>${escapeHtml(confirmation.source || "")}</span></div>
        <div><strong>Similarity</strong><span>${escapeHtml(similarityLabel)}</span></div>
      </div>
      <div class="job-confirmation-detail">${escapeHtml(confirmation.detail || "")}</div>
      <div class="job-confirmation-actions">
        <button class="button-link confirmation-button" type="button" data-job-id="${escapeHtml(job.id)}" data-confirmation-id="${escapeHtml(confirmation.id)}" data-job-confirm="approve" ${busy ? "disabled" : ""}>继续解析</button>
        <button class="danger-button confirmation-button" type="button" data-job-id="${escapeHtml(job.id)}" data-confirmation-id="${escapeHtml(confirmation.id)}" data-job-confirm="reject" ${busy ? "disabled" : ""}>终止任务</button>
      </div>
    </section>
  `;
}

function renderProgressMeta(progress, job) {
  const items = [
    `<span><strong>Elapsed</strong>${escapeHtml(formatElapsed(job.created_at, job.status === "completed" ? job.updated_at : null))}</span>`,
    `<span><strong>Stage</strong>${escapeHtml(progress.stage)}</span>`,
  ];
  if (progress.paper_total) {
    items.push(`<span><strong>Papers</strong>${escapeHtml(`${progress.paper_index || 0} / ${progress.paper_total}`)}</span>`);
  }
  if (progress.queue_position) {
    items.push(`<span><strong>Queue</strong>#${escapeHtml(String(progress.queue_position))}</span>`);
  }
  return `<div class="job-progress-stats">${items.join("")}</div>`;
}

function renderNoticeSection(notices = [], options = {}) {
  if (!notices || notices.length === 0) {
    return "";
  }
  const jobId = options.jobId || "";
  const storedOpen = Object.prototype.hasOwnProperty.call(state.timelineOpenByJobId, jobId)
    ? Boolean(state.timelineOpenByJobId[jobId])
    : Boolean(options.open);
  const openAttr = storedOpen ? " open" : "";
  return `
    <details class="timeline-panel"${openAttr} data-job-timeline="${escapeHtml(jobId)}">
      <summary><span>${escapeHtml(options.title || "Execution Timeline")}</span><span class="timeline-count">${escapeHtml(String(notices.length))}</span></summary>
      <ol class="notice-list timeline-list">${notices.map(renderNoticeItem).join("")}</ol>
    </details>
  `;
}

function renderNoticeItem(notice) {
  const kind = String(notice.kind || "info");
  const stage = String(notice.stage || "");
  const timeLabel = formatTimeShort(notice.created_at);
  return `
    <li class="notice-item notice-${escapeHtml(kind)}">
      <span class="notice-marker" aria-hidden="true"></span>
      <div class="notice-body">
        <div class="notice-line">${escapeHtml(notice.message)}</div>
        <div class="notice-meta">${escapeHtml(stage || "task")} · ${escapeHtml(timeLabel)}</div>
      </div>
    </li>
  `;
}

function renderPaperSection(title, papers) {
  if (!papers || papers.length === 0) {
    return `<section class="report-section"><h4>${escapeHtml(title)}</h4><p class="muted">None.</p></section>`;
  }
  return `<section class="report-section"><h4>${escapeHtml(title)}</h4><div class="paper-chip-grid">${papers.map(renderPaperChip).join("")}</div></section>`;
}

function renderPaperChip(paper) {
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
  const venueMeta = venueBits.length ? ` · ${escapeHtml(venueBits.join(" · "))}` : "";
  return `
    <div class="paper-chip">
      <button type="button" data-focus-paper="${escapeHtml(paper.paper_id)}">${escapeHtml(paper.title)}</button>
      <div class="paper-chip-meta">${escapeHtml(paper.major_topic)} / ${escapeHtml(paper.minor_topic)} · ${escapeHtml(formatShortDate(paper.published))}${venueMeta}</div>
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

function renderMetadataRefreshPanel(refresh) {
  if (!refresh) {
    return "";
  }
  const statusClass = refresh.status === "updated" ? "success" : refresh.status === "warning" ? "warning" : "muted";
  const sourceLines = Array.isArray(refresh.sources)
    ? refresh.sources.map((item) => {
      const itemClass = item.status === "updated" ? "success" : item.status === "error" ? "warning" : "muted";
      return `
        <div class="metadata-refresh-source ${itemClass}">
          <strong>${escapeHtml(item.source || "Source")}</strong>
          <span>${escapeHtml(item.message || "")}</span>
        </div>
      `;
    }).join("")
    : "";
  const updatedAt = refresh.updated_at ? `<div class="metadata-refresh-time">Last refresh · ${escapeHtml(formatTimeShort(refresh.updated_at))}</div>` : "";
  return `
    <section class="detail-section metadata-refresh-panel ${statusClass}">
      <h4>Metadata Refresh</h4>
      <p>${escapeHtml(refresh.message || "")}</p>
      ${updatedAt}
      ${sourceLines}
    </section>
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

function findNearestNonEmptyMarkdownLine(lines, index, step) {
  for (let cursor = index + step; cursor >= 0 && cursor < lines.length; cursor += step) {
    const candidate = String(lines[cursor] || "").trim();
    if (candidate) {
      return { index: cursor, text: candidate, gap: Math.max(0, Math.abs(cursor - index) - 1) };
    }
  }
  return { index: -1, text: "", gap: 0 };
}

function isOrderedMarkdownLine(line) {
  return /^\s*\d+\.\s+.+$/.test(String(line || ""));
}

function orderedMarkdownIndex(line) {
  const match = String(line || "").trim().match(/^(\d+)\.\s+.+$/);
  return match ? Number(match[1]) : null;
}

function looksLikeStandaloneNumberedHeading(title, previousNonempty, nextNonempty, previousGap = 0, nextGap = 0) {
  const normalized = String(title || "").trim().replace(/\s+/g, " ");
  if (!normalized) {
    return false;
  }
  if (normalized.length > 48) {
    return false;
  }
  if (normalized.includes("**") || normalized.includes("$$") || normalized.includes("$") || normalized.includes("`")) {
    return false;
  }
  if (/[。！？!?；;]$/.test(normalized)) {
    return false;
  }
  if (/[：:].{18,}$/.test(normalized)) {
    return false;
  }
  if (previousGap === 0 && isOrderedMarkdownLine(previousNonempty)) {
    return false;
  }
  if (nextGap === 0 && isOrderedMarkdownLine(nextNonempty)) {
    return false;
  }
  if (isOrderedMarkdownLine(previousNonempty) || isOrderedMarkdownLine(nextNonempty)) {
    return false;
  }
  return true;
}

function classifyStructuredNumberedHeading(line, previousNeighbor, nextNeighbor) {
  const trimmed = String(line || "").trim();
  const previousNonempty = previousNeighbor?.text || "";
  const nextNonempty = nextNeighbor?.text || "";
  const explicitHeading = trimmed.match(/^(#{1,6})\s+((?:\d+\.)+\d+|\d+\.)\s+(.+)$/);
  if (explicitHeading) {
    return { level: explicitHeading[1].length, text: explicitHeading[3].trim() };
  }

  const multilevelMatch = trimmed.match(/^((?:\d+\.)+\d+)\s+(.+)$/);
  if (
    multilevelMatch &&
    looksLikeStandaloneNumberedHeading(multilevelMatch[2], previousNonempty, nextNonempty, previousNeighbor?.gap || 0, nextNeighbor?.gap || 0)
  ) {
    return {
      level: Math.min(6, 2 + multilevelMatch[1].split(".").length),
      text: multilevelMatch[2].trim(),
    };
  }

  const singleLevelMatch = trimmed.match(/^(\d+)\.\s+(.+)$/);
  if (
    singleLevelMatch &&
    looksLikeStandaloneNumberedHeading(singleLevelMatch[2], previousNonempty, nextNonempty, previousNeighbor?.gap || 0, nextNeighbor?.gap || 0)
  ) {
    return { level: 3, text: singleLevelMatch[2].trim() };
  }
  const previousOrderedIndex = orderedMarkdownIndex(previousNonempty);
  if (
    singleLevelMatch &&
    previousOrderedIndex !== null &&
    (previousNeighbor?.gap || 0) > 0 &&
    orderedMarkdownIndex(nextNonempty) === null &&
    Number(singleLevelMatch[1]) <= previousOrderedIndex &&
    looksLikeStandaloneNumberedHeading(singleLevelMatch[2], "", nextNonempty, 0, nextNeighbor?.gap || 0)
  ) {
    return { level: 3, text: singleLevelMatch[2].trim() };
  }
  return null;
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
    const itemsHtml = listItems.map((item) => {
      if (listType === "ol" && typeof item.value === "number") {
        return `<li value="${item.value}">${renderInlineMarkdown(item.text)}</li>`;
      }
      return `<li>${renderInlineMarkdown(item.text)}</li>`;
    }).join("");
    html.push(`<${listType}>${itemsHtml}</${listType}>`);
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

  const splitMarkdownTableRow = (input) => {
    let working = String(input || "").trim();
    if (!working.includes("|")) {
      return [];
    }
    if (working.startsWith("|")) {
      working = working.slice(1);
    }
    if (working.endsWith("|")) {
      working = working.slice(0, -1);
    }

    const cells = [];
    let current = "";
    let escaped = false;
    for (const char of working) {
      if (escaped) {
        current += char;
        escaped = false;
        continue;
      }
      if (char === "\\") {
        current += char;
        escaped = true;
        continue;
      }
      if (char === "|") {
        cells.push(current.trim());
        current = "";
        continue;
      }
      current += char;
    }
    cells.push(current.trim());
    return cells;
  };

  const parseMarkdownTableAlignment = (cell) => {
    const normalized = String(cell || "").trim();
    if (!/^:?-{3,}:?$/.test(normalized)) {
      return null;
    }
    const startsWithColon = normalized.startsWith(":");
    const endsWithColon = normalized.endsWith(":");
    if (startsWithColon && endsWithColon) {
      return "center";
    }
    if (endsWithColon) {
      return "right";
    }
    if (startsWithColon) {
      return "left";
    }
    return "";
  };

  const parseMarkdownTableAt = (startIndex) => {
    if (startIndex + 1 >= lines.length) {
      return null;
    }

    const headerCells = splitMarkdownTableRow(lines[startIndex]);
    const separatorCells = splitMarkdownTableRow(lines[startIndex + 1]);
    if (headerCells.length < 2 || separatorCells.length !== headerCells.length) {
      return null;
    }

    const alignments = separatorCells.map(parseMarkdownTableAlignment);
    if (alignments.some((value) => value === null)) {
      return null;
    }

    const bodyRows = [];
    let cursor = startIndex + 2;
    while (cursor < lines.length) {
      const candidate = lines[cursor];
      if (!String(candidate || "").trim()) {
        break;
      }
      const cells = splitMarkdownTableRow(candidate);
      if (cells.length !== headerCells.length) {
        break;
      }
      bodyRows.push(cells);
      cursor += 1;
    }

    return {
      nextIndex: cursor - 1,
      headerCells,
      alignments,
      bodyRows,
    };
  };

  const renderMarkdownTable = (table) => {
    const head = table.headerCells.map((cell, index) => {
      const alignment = table.alignments[index];
      const alignAttr = alignment ? ` style="text-align:${alignment}"` : "";
      return `<th${alignAttr}>${renderInlineMarkdown(cell)}</th>`;
    }).join("");
    const body = table.bodyRows.map((row) => {
      const cells = row.map((cell, index) => {
        const alignment = table.alignments[index];
        const alignAttr = alignment ? ` style="text-align:${alignment}"` : "";
        return `<td${alignAttr}>${renderInlineMarkdown(cell)}</td>`;
      }).join("");
      return `<tr>${cells}</tr>`;
    }).join("");
    const tbody = body ? `<tbody>${body}</tbody>` : "";
    return `<div class="markdown-table-wrap"><table class="markdown-table"><thead><tr>${head}</tr></thead>${tbody}</table></div>`;
  };

  for (let index = 0; index < lines.length; index += 1) {
    const rawLine = lines[index];
    const line = rawLine.replace(/\t/g, "  ");
    const trimmed = line.trim();
    const previousNonempty = findNearestNonEmptyMarkdownLine(lines, index, -1);
    const nextNonempty = findNearestNonEmptyMarkdownLine(lines, index, 1);

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

    const structuredHeading = classifyStructuredNumberedHeading(trimmed, previousNonempty, nextNonempty);
    if (structuredHeading) {
      flushParagraph();
      flushList();
      flushQuote();
      html.push(`<h${structuredHeading.level}>${renderInlineMarkdown(structuredHeading.text)}</h${structuredHeading.level}>`);
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

    const table = parseMarkdownTableAt(index);
    if (table) {
      flushParagraph();
      flushList();
      flushQuote();
      html.push(renderMarkdownTable(table));
      index = table.nextIndex;
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
      listItems.push({ text: unorderedMatch[1].trim(), value: null });
      continue;
    }

    const orderedMatch = line.match(/^\s*(\d+)\.\s+(.+)$/);
    if (orderedMatch) {
      flushParagraph();
      flushQuote();
      if (listType && listType !== "ol") {
        flushList();
      }
      listType = "ol";
      listItems.push({ text: orderedMatch[2].trim(), value: Number(orderedMatch[1]) });
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
  if (!jobId || runtimeState.pollingJobIds.has(jobId)) {
    return;
  }
  runtimeState.pollingJobIds.add(jobId);
  try {
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
            await selectPaper(firstNew.paper_id, { silent: true });
          }
          break;
        }
        if (job.status === "failed" || job.status === "cancelled") {
          break;
        }
      } catch (error) {
        updateJobMessage({
          id: jobId,
          request: findStoredJobRequest(jobId) || "Task polling failed",
          status: "failed",
          error: describeTaskApiError(error, "任务状态同步失败"),
          notices: [],
        });
        break;
      }
    }
  } finally {
    runtimeState.pollingJobIds.delete(jobId);
  }
}

function updateJobMessage(job) {
  const messageId = `job-${job.id}`;
  const index = state.messages.findIndex((item) => item.id === messageId);
  if (index >= 0) {
    const previousJob = state.messages[index].job || { notices: [] };
    const previousCount = Array.isArray(previousJob.notices) ? previousJob.notices.length : 0;
    const nextNotices = Array.isArray(job.notices) ? job.notices : [];
    const milestoneMessages = [];
    let hasFreshContent = previousJob.status !== job.status || hasProgressChanged(previousJob.progress, job.progress);
    for (let idx = previousCount; idx < nextNotices.length; idx += 1) {
      const notice = nextNotices[idx];
      if ((notice.kind === "retry" || notice.kind === "warning") && notice.message) {
        showToast(notice.message, notice.level || "warning");
      }
       hasFreshContent = true;
      if (notice.kind === "milestone" && !state.milestoneNoticeIds.has(notice.id)) {
        state.milestoneNoticeIds.add(notice.id);
        milestoneMessages.push({
          id: `milestone-${notice.id}`,
          kind: "milestone",
          role: "assistant",
          text: notice.message,
        });
      }
    }
    const previousStatus = previousJob.status;
    state.messages[index] = { ...state.messages[index], job };
    if (job.status !== "awaiting_confirmation") {
      delete state.confirmationSubmittingByJobId[job.id];
    }
    if (job.status === "failed" || job.status === "completed" || job.status === "cancelled" || !job.cancel_requested) {
      delete state.cancelSubmittingByJobId[job.id];
    }
    if (job.status === "failed" && previousStatus !== "failed") {
      showToast("任务执行失败，请查看时间线和错误详情。", "warning");
    }
    if (milestoneMessages.length) {
      state.messages.push(...milestoneMessages);
      hasFreshContent = true;
    }
    renderMessages({ newContent: hasFreshContent });
    return;
  }
  state.messages.push({ id: messageId, kind: "job", role: "assistant", job });
  renderMessages({ newContent: true });
}

function updateJobChip() {
  const activeJobs = state.messages.filter((message) => message.kind === "job" && (message.job.status === "queued" || message.job.status === "running" || message.job.status === "awaiting_confirmation")).length;
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

function findPaperLocationById(paperId) {
  if (!paperId || !state.library) {
    return null;
  }
  for (const major of state.library.major_topics) {
    for (const minor of major.minor_topics) {
      const paper = minor.papers.find((item) => item.paper_id === paperId);
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

function findPaperSummaryById(paperId) {
  return findPaperLocationById(paperId)?.paper || null;
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const contentType = response.headers.get("Content-Type") || "";
  const isJson = contentType.includes("application/json");
  const payload = isJson ? await response.json() : await response.text();
  if (!response.ok) {
    const message = isJson && payload.error ? payload.error : response.statusText;
    const error = new Error(message);
    error.status = response.status;
    error.path = path;
    throw error;
  }
  return payload;
}

function describeTaskApiError(error, prefix) {
  const path = typeof error?.path === "string" ? error.path : "";
  if (error?.status === 404 && path.startsWith("/api/tasks/")) {
    return `${prefix}：任务已不存在于服务端（404）。这通常表示 Web 服务刚刚重启，内存中的任务状态已经丢失。`;
  }
  return prefix ? `${prefix}：${error.message}` : error.message;
}

async function resumeActiveJobs() {
  const activeJobIds = Array.from(new Set(
    state.messages
      .filter((message) => message.kind === "job")
      .map((message) => message.job)
      .filter((job) => job && (job.status === "queued" || job.status === "running" || job.status === "awaiting_confirmation"))
      .map((job) => job.id)
  ));
  for (const jobId of activeJobIds) {
    await resumeJob(jobId);
  }
}

async function resumeJob(jobId) {
  if (!jobId || runtimeState.pollingJobIds.has(jobId)) {
    return;
  }
  try {
    const payload = await api(`/api/tasks/${encodeURIComponent(jobId)}`);
    updateJobMessage(payload.job);
    updateJobChip();
    if (payload.job.status === "queued" || payload.job.status === "running" || payload.job.status === "awaiting_confirmation") {
      void pollJob(jobId);
    }
  } catch (error) {
    const requestLabel = findStoredJobRequest(jobId);
    updateJobMessage({
      id: jobId,
      request: requestLabel || "Restored Task",
      status: "failed",
      error: describeTaskApiError(error, "刷新后恢复任务失败"),
      notices: [],
    });
    updateJobChip();
  }
}

function findStoredJobRequest(jobId) {
  const message = state.messages.find((item) => item.kind === "job" && item.job && item.job.id === jobId);
  return message?.job?.request || "";
}

function normalizeJobProgress(job) {
  const progress = job.progress || {};
  const status = String(job.status || "queued");
  const defaultStage = status === "failed"
    ? "failed"
    : status === "cancelled"
      ? "cancelled"
      : status === "completed"
        ? "completed"
        : status === "queued"
          ? "queued"
          : status === "awaiting_confirmation"
            ? "confirmation"
            : "running";
  const defaultLabel = status === "failed"
    ? "任务失败"
    : status === "cancelled"
      ? "任务已终止"
      : status === "completed"
        ? "任务完成"
        : status === "queued"
          ? "排队中"
          : status === "awaiting_confirmation"
            ? "等待确认"
            : "执行中";
  return {
    stage: String(progress.stage || defaultStage),
    label: String(progress.label || defaultLabel),
    detail: String(progress.detail || "等待更多进度信息"),
    percent: Number.isFinite(Number(progress.percent)) ? Number(progress.percent) : 0,
    indeterminate: Boolean(progress.indeterminate),
    paper_index: progress.paper_index == null ? null : Number(progress.paper_index),
    paper_total: progress.paper_total == null ? null : Number(progress.paper_total),
    current_title: progress.current_title ? String(progress.current_title) : "",
    queue_position: progress.queue_position == null ? null : Number(progress.queue_position),
  };
}

function hasProgressChanged(previous, next) {
  const before = previous || {};
  const after = next || {};
  return (
    before.stage !== after.stage
    || before.label !== after.label
    || before.detail !== after.detail
    || Number(before.percent || 0) !== Number(after.percent || 0)
    || Number(before.paper_index || 0) !== Number(after.paper_index || 0)
    || Number(before.paper_total || 0) !== Number(after.paper_total || 0)
    || String(before.current_title || "") !== String(after.current_title || "")
    || Number(before.queue_position || 0) !== Number(after.queue_position || 0)
    || Boolean(before.indeterminate) !== Boolean(after.indeterminate)
  );
}

function formatElapsed(createdAt, frozenAt = null) {
  const start = new Date(createdAt || "");
  if (Number.isNaN(start.getTime())) {
    return "--:--";
  }
  const end = frozenAt ? new Date(frozenAt) : new Date();
  const elapsedSeconds = Math.max(0, Math.floor((end.getTime() - start.getTime()) / 1000));
  const hours = Math.floor(elapsedSeconds / 3600);
  const minutes = Math.floor((elapsedSeconds % 3600) / 60);
  const seconds = elapsedSeconds % 60;
  if (hours > 0) {
    return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  }
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function formatTimeShort(value) {
  if (!value) {
    return "--:--";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
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

function escapeHtmlAttribute(value) {
  return escapeHtml(value);
}

function renderVenueMeta(venue) {
  if (!venue || !venue.name) {
    return "";
  }
  const bits = [venue.name];
  if (venue.year) {
    bits.push(String(venue.year));
  }
  if (venue.kind) {
    bits.push(venue.kind);
  }
  return `<span>${escapeHtml(bits.join(" · "))}</span>`;
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}
