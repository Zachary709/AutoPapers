import { api } from "./api.js";
import { appendMessage } from "./jobs.js";
import { renderLibrary } from "./library.js";
import { hasRenderableMarkdown, queueMathTypeset, renderMarkdownPreview } from "./markdown.js";
import { renderAppChrome } from "./settings.js";
import {
  elements,
  escapeHtml,
  escapeHtmlAttribute,
  formatShortDate,
  formatTimeShort,
  persistConversationState,
  renderVenueMeta,
  state,
  syncDirectoryFocusToSelection,
} from "./state.js";

export async function selectPaper(paperId, { silent = false } = {}) {
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

export function renderPaperDetailLoading() {
  elements.paperDetail.innerHTML = `<div class="empty-state">正在加载论文预览...</div>`;
}

export function renderPaperDetail(errorText = "") {
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

export async function deletePaper(paperId, title) {
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

export async function refreshSelectedPaperMetadata(paperId) {
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

export function renderStructuredPaperFallback(paper, digest) {
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

export function renderMetadataRefreshPanel(refresh) {
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

export function renderFallbackParagraph(title, text) {
  const normalized = String(text || "").trim();
  if (!normalized) {
    return "";
  }
  return `<p><strong>${escapeHtml(title)}:</strong> ${escapeHtml(normalized)}</p>`;
}

export function renderFallbackList(title, items) {
  const normalized = (items || []).map((item) => String(item || "").trim()).filter(Boolean);
  if (normalized.length === 0) {
    return "";
  }
  return `<div><strong>${escapeHtml(title)}:</strong><ul>${normalized.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></div>`;
}
