import { Fragment, type ReactNode } from "react";
import type { ResearchCitation } from "../types";

import { safeResearchUrl } from "../lib/research";

// A deliberately small Markdown vocabulary: React escapes all raw HTML.
function inline(value: string): ReactNode[] {
  return value
    .split(/(\[[^\]\n]+\]\(https?:\/\/[^\s)]+\)|\*\*[^*]+\*\*|`[^`]+`)/g)
    .map((part, index) => {
      const link = /^\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)$/.exec(part);
      if (link) {
        const url = safeResearchUrl(link[2]);
        if (url)
          return (
            <a key={index} href={url} target="_blank" rel="noopener noreferrer">
              {link[1]}
            </a>
          );
      }
      if (part.startsWith("**") && part.endsWith("**"))
        return <strong key={index}>{part.slice(2, -2)}</strong>;
      if (part.startsWith("`") && part.endsWith("`"))
        return <code key={index}>{part.slice(1, -1)}</code>;
      return <Fragment key={index}>{part}</Fragment>;
    });
}

function citedText(text: string, citations: ResearchCitation[]): string {
  const characters = Array.from(text);
  let lastStart = characters.length;
  const spans = citations
    .filter((citation) => citation.start_index !== null && citation.end_index !== null)
    .sort((a, b) => b.start_index! - a.start_index!);
  for (const citation of spans) {
    const start = citation.start_index!;
    const end = citation.end_index!;
    const url = safeResearchUrl(citation.url);
    if (!url || start < 0 || end <= start || end > lastStart) continue;
    const original = characters.slice(start, end).join("");
    const label = original.includes("")
      ? `Source ${citations.indexOf(citation) + 1}`
      : original.replace(/[[\]\n]/g, " ");
    characters.splice(
      start,
      end - start,
      `[${label}](${url.replace(/\(/g, "%28").replace(/\)/g, "%29")})`,
    );
    lastStart = start;
  }
  return characters.join("");
}

export function ResearchReport({
  text,
  citations,
}: {
  text: string;
  citations: ResearchCitation[];
}) {
  const lines = citedText(text, citations).split("\n");
  const blocks: ReactNode[] = [];
  const cells = (line: string) =>
    line
      .trim()
      .replace(/^\||\|$/g, "")
      .split("|")
      .map((cell) => cell.trim());
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line) continue;
    if (line.includes("|") && /^\|?\s*:?-{3,}/.test(lines[i + 1]?.trim() ?? "")) {
      const headers = cells(line);
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && lines[i].includes("|")) rows.push(cells(lines[i++]));
      i--;
      blocks.push(
        <div
          key={`table-${i}`}
          className="research-table"
          tabIndex={0}
          role="region"
          aria-label="Research comparison table"
        >
          <table>
            <thead>
              <tr>
                {headers.map((cell, j) => (
                  <th key={j}>{inline(cell)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, j) => (
                <tr key={j}>
                  {headers.map((_, k) => (
                    <td key={k}>{inline(row[k] ?? "—")}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }
    if (/^#{1,6}\s/.test(line)) {
      blocks.push(<h3 key={i}>{inline(line.replace(/^#{1,6}\s+/, ""))}</h3>);
    } else if (/^[-*]\s/.test(line) || /^\d+\.\s/.test(line)) {
      const items: string[] = [line.replace(/^(?:[-*]|\d+\.)\s+/, "")];
      while (/^(?:[-*]|\d+\.)\s/.test(lines[i + 1]?.trim() ?? ""))
        items.push(lines[++i].trim().replace(/^(?:[-*]|\d+\.)\s+/, ""));
      blocks.push(
        <ul key={i}>
          {items.map((item, j) => (
            <li key={j}>{inline(item)}</li>
          ))}
        </ul>,
      );
    } else if (/^[-*_]{3,}$/.test(line)) {
      blocks.push(<hr key={i} />);
    } else {
      blocks.push(<p key={i}>{inline(line)}</p>);
    }
  }
  return <div className="research-report">{blocks}</div>;
}
