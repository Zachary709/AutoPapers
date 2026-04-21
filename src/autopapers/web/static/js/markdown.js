import { escapeHtml, mathRenderState } from "./state.js";

export function hasRenderableMarkdown(markdown) {
  return Boolean(String(markdown || "").trim());
}

export function renderMarkdownPreview(markdown, options = {}) {
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

export function renderMarkdown(markdown) {
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

export function renderInlineMarkdown(text) {
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

export function renderMarkdownLink(label, href) {
  const safeHref = sanitizeMarkdownHref(href);
  const safeLabel = escapeHtml(label);
  if (!safeHref) {
    return `<span class="markdown-link-fallback">${safeLabel}</span>`;
  }
  const external = /^(https?:)?\/\//i.test(safeHref);
  const target = external ? ' target="_blank" rel="noreferrer"' : "";
  return `<a href="${escapeHtml(safeHref)}"${target}>${safeLabel}</a>`;
}

export function queueMathTypeset(root) {
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

export function flushMathTypesetQueue() {
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

export function sanitizeMarkdownHref(href) {
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
