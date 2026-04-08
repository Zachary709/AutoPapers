const state = {
  app: null,
  library: null,
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
  previewWidth: "autopapers.layout.previewWidth",
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
  applyStoredLayout();
  bindResizableSplitters();
  window.addEventListener("resize", () => {
    clampLayoutToViewport();
  });
}

function bindResizableSplitters() {
  bindDragSplitter(elements.chatDirectorySplitter, {
    axis: "x",
    bodyClass: "is-resizing-col",
    getStartValue: () => getCurrentChatWidth(),
    applyDelta: (startValue, delta) => setChatPanelWidth(startValue + delta),
    step: 28,
    onKeyAdjust: (delta) => setChatPanelWidth(getCurrentChatWidth() + delta),
  });

  bindDragSplitter(elements.directoryPreviewSplitter, {
    axis: "x",
    bodyClass: "is-resizing-col",
    getStartValue: () => getCurrentPreviewWidth(),
    applyDelta: (startValue, delta) => setPreviewPanelWidth(startValue - delta),
    step: 28,
    onKeyAdjust: (delta) => setPreviewPanelWidth(getCurrentPreviewWidth() - delta),
  });
}

function bindDragSplitter(handle, options) {
  if (!handle) {
    return;
  }

  handle.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || !isDesktopLayout()) {
      return;
    }
    event.preventDefault();
    const pointerId = event.pointerId;
    const startValue = options.getStartValue();
    const startPointer = options.axis === "x" ? event.clientX : event.clientY;
    handle.classList.add("dragging");
    document.body.classList.add(options.bodyClass);
    handle.setPointerCapture(pointerId);

    const onMove = (moveEvent) => {
      if (moveEvent.pointerId !== pointerId) {
        return;
      }
      const currentPointer = options.axis === "x" ? moveEvent.clientX : moveEvent.clientY;
      options.applyDelta(startValue, currentPointer - startPointer);
    };

    const stop = (endEvent) => {
      if (endEvent.pointerId !== pointerId) {
        return;
      }
      handle.classList.remove("dragging");
      document.body.classList.remove(options.bodyClass);
      handle.releasePointerCapture(pointerId);
      handle.removeEventListener("pointermove", onMove);
      handle.removeEventListener("pointerup", stop);
      handle.removeEventListener("pointercancel", stop);
    };

    handle.addEventListener("pointermove", onMove);
    handle.addEventListener("pointerup", stop);
    handle.addEventListener("pointercancel", stop);
  });

  handle.addEventListener("keydown", (event) => {
    if (!isDesktopLayout()) {
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

function applyStoredLayout() {
  if (!isDesktopLayout()) {
    return;
  }
  const storedChatWidth = readStoredNumber(layoutKeys.chatWidth);
  const storedPreviewWidth = readStoredNumber(layoutKeys.previewWidth);

  if (storedChatWidth) {
    setChatPanelWidth(storedChatWidth);
  }
  if (storedPreviewWidth) {
    setPreviewPanelWidth(storedPreviewWidth);
  }
  clampLayoutToViewport();
}

function clampLayoutToViewport() {
  if (!isDesktopLayout()) {
    return;
  }
  setChatPanelWidth(getCurrentChatWidth(), { persist: false });
  setPreviewPanelWidth(getCurrentPreviewWidth(), { persist: false });
}

function setChatPanelWidth(width, { persist = true } = {}) {
  const bounds = getShellBounds(getCurrentPreviewWidth(), 300);
  const clamped = clamp(width, bounds.min, bounds.max);
  elements.appShell?.style.setProperty("--layout-chat-width", `${Math.round(clamped)}px`);
  if (persist) {
    persistLayoutValue(layoutKeys.chatWidth, clamped);
  }
}

function setPreviewPanelWidth(width, { persist = true } = {}) {
  const bounds = getShellBounds(getCurrentChatWidth(), 340);
  const clamped = clamp(width, bounds.min, bounds.max);
  elements.appShell?.style.setProperty("--layout-preview-width", `${Math.round(clamped)}px`);
  if (persist) {
    persistLayoutValue(layoutKeys.previewWidth, clamped);
  }
}

function getCurrentChatWidth() {
  return elements.chatPanel?.getBoundingClientRect().width || getShellBounds(getCurrentPreviewWidth(), 300).preferred;
}

function getCurrentPreviewWidth() {
  return elements.previewPanel?.getBoundingClientRect().width || getShellBounds(getCurrentChatWidth(), 340).preferred;
}

function getShellBounds(otherPanelWidth, minWidth) {
  const shellWidth = elements.appShell?.clientWidth || window.innerWidth;
  const min = minWidth;
  const centerMin = 360;
  const splitterTotal = 28;
  const safeOtherWidth = Number.isFinite(otherPanelWidth) && otherPanelWidth > 0 ? otherPanelWidth : shellWidth * 0.3;
  const max = Math.max(min, shellWidth - centerMin - safeOtherWidth - splitterTotal);
  return {
    min,
    max,
    preferred: Math.min(Math.max(shellWidth * 0.29, min), max),
  };
}

function persistLayoutValue(key, value) {
  try {
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
    elements.libraryTree.innerHTML = `<div class="empty-state">当前论文库为空。提交任务后，新论文会自动落到这里。</div>`;
    return;
  }

  const topics = state.library.major_topics
    .map((major) => filterMajorTopic(major, state.filter))
    .filter(Boolean);

  if (topics.length === 0) {
    elements.libraryTree.innerHTML = `<div class="empty-state">没有匹配当前过滤词的目录项。</div>`;
    return;
  }

  elements.libraryTree.innerHTML = topics.map(renderMajorTopic).join("");
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

function renderMajorTopic(major) {
  return `
    <details class="topic-card" open>
      <summary class="topic-summary">
        <div class="topic-meta">
          <span class="topic-title">${escapeHtml(major.name)}</span>
          <span class="muted">${escapeHtml(String(major.minor_topic_count))} subtracks</span>
        </div>
        <span class="topic-count">${escapeHtml(String(major.count))}</span>
      </summary>
      <div class="minor-list">${major.minor_topics.map(renderMinorTopic).join("")}</div>
    </details>
  `;
}

function renderMinorTopic(minor) {
  return `
    <details class="minor-card" open>
      <summary class="minor-summary">
        <span class="minor-title">${escapeHtml(minor.name)}</span>
        <span class="minor-count">${escapeHtml(String(minor.count))}</span>
      </summary>
      <div class="paper-list">${minor.papers.map(renderPaperButton).join("")}</div>
    </details>
  `;
}

function renderPaperButton(paper) {
  const activeClass = paper.arxiv_id === state.selectedPaperId ? "active" : "";
  return `
    <button class="paper-button ${activeClass}" type="button" data-paper-id="${escapeHtml(paper.arxiv_id)}">
      <span class="paper-title">${escapeHtml(paper.title)}</span>
      <span class="paper-meta"><span>${escapeHtml(formatShortDate(paper.published))}</span><span>${escapeHtml(paper.takeaway)}</span></span>
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
  return `
    <div class="detail-section">
      <h4>Summary Snapshot</h4>
      <div class="markdown-preview compact">
        <p><strong>Takeaway:</strong> ${escapeHtml(digest.one_sentence_takeaway)}</p>
        <p><strong>Abstract:</strong> ${escapeHtml(paper.abstract)}</p>
        <p><strong>Method:</strong> ${escapeHtml(digest.method)}</p>
        <p><strong>Findings:</strong> ${escapeHtml((digest.findings || []).join("；") || "暂无。")}</p>
        <p><strong>Limitations:</strong> ${escapeHtml((digest.limitations || []).join("；") || "暂无。")}</p>
      </div>
    </div>
  `;
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

function findPaperSummaryById(arxivId) {
  if (!arxivId || !state.library) {
    return null;
  }
  for (const major of state.library.major_topics) {
    for (const minor of major.minor_topics) {
      const match = minor.papers.find((paper) => paper.arxiv_id === arxivId);
      if (match) {
        return match;
      }
    }
  }
  return null;
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
