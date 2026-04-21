import {
  elements,
  isDesktopLayout,
  layoutConfig,
  layoutKeys,
  layoutState,
  panelLabels,
  clamp,
  persistLayoutValue,
  readStoredBoolean,
  readStoredNumber,
} from "./state.js";

export function initializeResizableLayout() {
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

export function syncShellLayout({ persist = true } = {}) {
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

export function syncComposerLayout({ persist = true } = {}) {
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

export function setChatPanelWidth(width, { persist = true } = {}) {
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

export function setPreviewPanelWidth(width, { persist = true } = {}) {
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

export function toggleComposerCollapsed() {
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
