export function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

export function renderMarkdown(text) {
  const parts = String(text).replace(/\r\n/g, "\n").split("```");
  return parts
    .map((part, index) => {
      if (index % 2 === 1) {
        const lines = part.replace(/^\w+\n/, "");
        return `<pre><code>${escapeHtml(lines.trim())}</code></pre>`;
      }
      // Handle display math blocks: $$ ... $$
      return part
        .split("$$")
        .map((subPart, subIndex) => {
          if (subIndex % 2 === 1) {
            return renderMath(subPart.trim(), true);
          }
          return renderMarkdownText(subPart);
        })
        .join("");
    })
    .join("");
}

function renderMarkdownText(text) {
  const lines = text.split("\n");
  const html = [];
  let paragraph = [];
  let listType = null;
  let listItems = [];

  function flushParagraph() {
    if (!paragraph.length) {
      return;
    }
    html.push(`<p>${parseInline(paragraph.join(" ").trim())}</p>`);
    paragraph = [];
  }

  function flushList() {
    if (!listType) {
      return;
    }
    const tag = listType === "ordered" ? "ol" : "ul";
    html.push(
      `<${tag}>${listItems.map((item) => `<li>${parseInline(item)}</li>`).join("")}</${tag}>`,
    );
    listType = null;
    listItems = [];
  }

  for (let index = 0; index < lines.length; index += 1) {
    const rawLine = lines[index];
    const line = rawLine.trim();
    if (!line) {
      flushParagraph();
      flushList();
      continue;
    }

    if (isTableRow(line) && isTableDivider((lines[index + 1] || "").trim())) {
      flushParagraph();
      flushList();
      const tableLines = [line, lines[index + 1].trim()];
      index += 2;
      while (index < lines.length && isTableRow(lines[index].trim())) {
        tableLines.push(lines[index].trim());
        index += 1;
      }
      index -= 1;
      html.push(renderTableFromLines(tableLines));
      continue;
    }

    const compactTableRows = parseCompactTableRows(line);
    if (compactTableRows) {
      flushParagraph();
      flushList();
      html.push(renderTable(compactTableRows.header, compactTableRows.rows));
      continue;
    }

    const heading = line.match(/^(#{1,4})\s*(.+)$/);
    if (heading) {
      flushParagraph();
      flushList();
      const level = Math.min(heading[1].length + 1, 4);
      html.push(`<h${level}>${parseInline(heading[2])}</h${level}>`);
      continue;
    }

    const unordered = line.match(/^[-*+]\s+(.+)$/);
    const ordered = line.match(/^\d+[.)]\s+(.+)$/);
    if (unordered || ordered) {
      flushParagraph();
      const currentType = ordered ? "ordered" : "unordered";
      if (listType && listType !== currentType) {
        flushList();
      }
      listType = currentType;
      listItems.push((ordered || unordered)[1].trim());
      continue;
    }

    const quote = line.match(/^>\s?(.+)$/);
    if (quote) {
      flushParagraph();
      flushList();
      html.push(`<blockquote>${parseInline(quote[1])}</blockquote>`);
      continue;
    }

    flushList();
    paragraph.push(line);
  }

  flushParagraph();
  flushList();
  return html.join("");
}

function isTableRow(line) {
  const trimmed = line.trim();
  return trimmed.startsWith("|") && (trimmed.match(/\|/g) || []).length >= 2;
}

function isDividerCell(cell) {
  return /^:?-{2,}:?$/.test(cell.trim());
}

function isTableDivider(line) {
  if (!isTableRow(line)) {
    return false;
  }
  const cells = splitTableCells(line).filter(Boolean);
  return cells.length > 0 && cells.every(isDividerCell);
}

function splitTableCells(row) {
  let trimmed = row.trim();
  if (trimmed.startsWith("|")) {
    trimmed = trimmed.slice(1);
  }
  if (trimmed.endsWith("|")) {
    trimmed = trimmed.slice(0, -1);
  }
  return trimmed.split("|").map((cell) => cell.trim());
}

function normalizeTableCells(cells, columnCount) {
  const normalized = [...cells];
  if (normalized.length > columnCount) {
    return [
      ...normalized.slice(0, columnCount - 1),
      normalized.slice(columnCount - 1).join(" | "),
    ];
  }
  while (normalized.length < columnCount) {
    normalized.push("");
  }
  return normalized;
}

function renderTableFromLines(tableLines) {
  const header = splitTableCells(tableLines[0]).filter(Boolean);
  const columnCount = Math.max(header.length, 1);
  const rows = tableLines
    .slice(2)
    .map((line) =>
      normalizeTableCells(splitTableCells(line).filter(Boolean), columnCount),
    );
  return renderTable(normalizeTableCells(header, columnCount), rows);
}

function parseCompactTableRows(line) {
  if (!line.includes("|") || !/-{2,}/.test(line)) {
    return null;
  }
  const cells = splitTableCells(line).filter((cell) => cell.length > 0);
  for (let dividerStart = 1; dividerStart < cells.length; dividerStart += 1) {
    let dividerEnd = dividerStart;
    while (dividerEnd < cells.length && isDividerCell(cells[dividerEnd])) {
      dividerEnd += 1;
    }

    const columnCount = dividerEnd - dividerStart;
    if (columnCount < 2 || dividerStart < columnCount) {
      continue;
    }

    const header = cells.slice(dividerStart - columnCount, dividerStart);
    const remaining = cells.slice(dividerEnd);
    if (remaining.length < columnCount) {
      continue;
    }

    const rows = [];
    for (let index = 0; index < remaining.length; index += columnCount) {
      rows.push(
        normalizeTableCells(
          remaining.slice(index, index + columnCount),
          columnCount,
        ),
      );
    }
    return {
      header: normalizeTableCells(header, columnCount),
      rows,
    };
  }
  return null;
}

function renderTable(header, rows) {
  const thead = header.map((cell) => `<th>${parseInline(cell)}</th>`).join("");
  const tbody = rows
    .map(
      (row) =>
        `<tr>${row.map((cell) => `<td>${parseInline(cell)}</td>`).join("")}</tr>`,
    )
    .join("");
  return `<div class="markdown-table-wrap"><table><thead><tr>${thead}</tr></thead><tbody>${tbody}</tbody></table></div>`;
}

function parseInline(text) {
  return String(text)
    .split(/(`[^`]+`)/g)
    .map((part) => {
      if (part.startsWith("`") && part.endsWith("`")) {
        return `<code>${escapeHtml(part.slice(1, -1))}</code>`;
      }
      return parseInlineMath(part);
    })
    .join("");
}

function parseInlineMath(text) {
  return String(text)
    .split(/(\$[^$\n]+?\$)/g)
    .map((part) => {
      if (part.startsWith("$") && part.endsWith("$")) {
        return renderMath(part.slice(1, -1).trim(), false);
      }
      return parseInlineEmphasis(part);
    })
    .join("");
}

function parseInlineEmphasis(text) {
  let value = escapeHtml(text);
  value = value.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  value = value.replace(/\*([^*]+)\*/g, "<em>$1</em>");
  return value;
}

function renderMath(formula, displayMode) {
  if (typeof katex === "undefined") {
    return displayMode
      ? `<pre class="math-block-fallback">$$${escapeHtml(formula)}$$</pre>`
      : `<code class="math-inline-fallback">$${escapeHtml(formula)}$</code>`;
  }
  try {
    return katex.renderToString(formula, {
      throwOnError: false,
      displayMode: displayMode,
      trust: false,
    });
  } catch (_error) {
    return displayMode
      ? `<pre class="math-block-fallback">$$${escapeHtml(formula)}$$</pre>`
      : `<code class="math-inline-fallback">$${escapeHtml(formula)}$</code>`;
  }
}
