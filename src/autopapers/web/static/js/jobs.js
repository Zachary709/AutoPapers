import { api, describeTaskApiError } from "./api.js";
import { renderLibrary } from "./library.js";
import { queueMathTypeset, renderMarkdownPreview } from "./markdown.js";
import { selectPaper } from "./paper_detail.js";
import { renderAppChrome } from "./settings.js";
import {
  elements,
  escapeHtml,
  formatElapsed,
  formatShortDate,
  formatTimeShort,
  layoutConfig,
  persistConversationState,
  runtimeState,
  sleep,
  state,
} from "./state.js";
import { loadLibrary } from "./library.js";

export async function respondToJobConfirmation(jobId, confirmationId, approved) {
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

export async function cancelJob(jobId) {
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

export function appendMessage(message, options = {}) {
  state.messages.push(message);
  persistConversationState();
  renderMessages({ newContent: true, forceBottom: Boolean(options.forceBottom) });
}

export function renderMessages({ newContent = false, forceBottom = false } = {}) {
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

export function refreshChatPinState() {
  const pinned = isChatFeedNearBottom();
  state.chatPinnedToBottom = pinned;
  if (pinned) {
    state.chatHasUnseenUpdates = false;
  }
  updateJumpLatestButton();
}

export function updateJumpLatestButton() {
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

export async function pollJob(jobId) {
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

export function updateJobMessage(job) {
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

export function updateJobChip() {
  const activeJobs = state.messages.filter((message) => message.kind === "job" && (message.job.status === "queued" || message.job.status === "running" || message.job.status === "awaiting_confirmation")).length;
  elements.jobChip.textContent = activeJobs > 0 ? `${activeJobs} active` : "Idle";
}

export function setSubmitting(isSubmitting) {
  elements.submitButton.disabled = isSubmitting;
  elements.submitButton.textContent = isSubmitting ? "Dispatching..." : "Dispatch to LLM";
}

export function showToast(message, level = "warning") {
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

export async function resumeActiveJobs() {
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

export async function resumeJob(jobId) {
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

export function findStoredJobRequest(jobId) {
  const message = state.messages.find((item) => item.kind === "job" && item.job && item.job.id === jobId);
  return message?.job?.request || "";
}

export function normalizeJobProgress(job) {
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

export function hasProgressChanged(previous, next) {
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
