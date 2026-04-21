export const state = {
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

export const elements = {};

export const layoutKeys = {
  chatWidth: "autopapers.layout.chatWidth",
  chatCollapsed: "autopapers.layout.chatCollapsed",
  directoryCollapsed: "autopapers.layout.directoryCollapsed",
  previewWidth: "autopapers.layout.previewWidth",
  previewCollapsed: "autopapers.layout.previewCollapsed",
  composerHeight: "autopapers.layout.composerHeight",
  composerCollapsed: "autopapers.layout.composerCollapsed",
};

export const conversationKeys = {
  session: "autopapers.chat.session",
};

export const layoutConfig = {
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

export const persistenceConfig = {
  maxMessages: 30,
  maxNoticesPerJob: 120,
  maxReportChars: 24000,
  maxErrorChars: 12000,
};

export const layoutState = {
  chatWidth: null,
  previewWidth: null,
  chatCollapsed: false,
  directoryCollapsed: false,
  previewCollapsed: false,
  composerHeight: null,
  composerCollapsed: false,
};

export const panelLabels = {
  chat: "LLM",
  directory: "Directory",
  preview: "Preview",
};

export const mathRenderState = {
  pendingRoots: new Set(),
  scheduled: false,
  retryCount: 0,
  maxRetries: 20,
};

export const runtimeState = {
  pollingJobIds: new Set(),
};

export function bindElements() {
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

export function persistLayoutValue(key, value) {
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

export function readStoredNumber(key) {
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

export function readStoredBoolean(key, fallback = false) {
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

export function restoreConversationState() {
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

export function persistConversationState() {
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

export function serializeMessageForStorage(message) {
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

export function compactJobForStorage(job) {
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

export function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

export function isDesktopLayout() {
  return window.matchMedia("(min-width: 1081px)").matches;
}

export function firstPaperFromTree(library) {
  for (const major of library.major_topics || []) {
    for (const minor of major.minor_topics || []) {
      if (minor.papers && minor.papers.length) {
        return minor.papers[0];
      }
    }
  }
  return null;
}

export function findPaperLocationById(paperId) {
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

export function syncDirectoryFocusToSelection() {
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

export function findPaperSummaryById(paperId) {
  return findPaperLocationById(paperId)?.paper || null;
}

export function formatElapsed(createdAt, frozenAt = null) {
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

export function formatTimeShort(value) {
  if (!value) {
    return "--:--";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function formatShortDate(value) {
  if (!value) {
    return "Unknown";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });
}

export function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function escapeHtmlAttribute(value) {
  return escapeHtml(value);
}

export function renderVenueMeta(venue) {
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

export function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}
