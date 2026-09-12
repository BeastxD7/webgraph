import type { ReactNode } from "react";

/**
 * Render extracted Markdown as React elements, never as HTML.
 *
 * The safety argument is the whole reason this exists rather than a dependency.
 *
 * This Markdown is fetched from arbitrary third-party websites, and since the engine began
 * preserving complex tables it legitimately *contains raw HTML*. Handing that to
 * `dangerouslySetInnerHTML`, with or without a sanitiser, means one library's bug is a
 * cross-site scripting hole in this app. Building React elements instead means there is no
 * HTML string anywhere in the path: a `<script>` in the input cannot become a script, because
 * nothing here can produce one.
 *
 * Tables are the one case that needs real parsing, and they are parsed with `DOMParser` into
 * an inert document and then walked against an allowlist. The engine already cleans preserved
 * tables down to these same tags, but this does not trust that -- a renderer that assumes its
 * input was cleaned is a renderer that breaks the day something else writes to it.
 *
 * It covers what this engine emits and not the whole of Markdown. Anything unrecognised is
 * shown as its own text, which is the honest failure: you see the source rather than nothing.
 */

const TABLE_TAGS = new Set(["TABLE", "THEAD", "TBODY", "TFOOT", "TR", "TD", "TH", "CAPTION", "SUB", "SUP", "A"]);
const KEPT_ATTRS = new Set(["colspan", "rowspan"]);

/** A link target is only followed if it is one a browser should follow. */
function safeHref(raw: string): string | null {
  try {
    const url = new URL(raw, "https://example.invalid/");
    return url.protocol === "http:" || url.protocol === "https:" || url.protocol === "mailto:"
      ? raw
      : null;
  } catch {
    return null;
  }
}

/** Markdown's backslash escapes, undone for display: `\$5` is five dollars. */
function unescape(text: string): string {
  return text.replace(/\\([\\`*_{}[\]()#+\-.!$|>~])/g, "$1");
}

function inline(text: string, keyPrefix: string, depth = 0): ReactNode[] {
  const out: ReactNode[] = [];
  // One pass, longest-first so `**bold**` is not eaten by the italic rule. Images come
  // before links because `![alt](src)` is a link with a bang in front, and matching the
  // link first rendered every picture as "!" followed by a link named after its alt text.
  const pattern =
    /(`[^`]+`)|(!\[([^\]]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\))|(\[([^\]]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\))|(\*\*(.+?)\*\*)|(\*([^*\s][^*]*?)\*)/g;
  let last = 0;
  let match: RegExpExecArray | null;
  let index = 0;
  // Bold, italic and link labels are themselves Markdown -- `**see [the docs](url)**` is
  // common -- so their contents go back through this function. Bounded, because nothing
  // real nests more than a few levels and an unbounded recursion on adversarial input is
  // a way to hang the page.
  const nested = (inner: string, key: string): ReactNode[] =>
    depth < 4 ? inline(inner, key, depth + 1) : [unescape(inner)];

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) out.push(unescape(text.slice(last, match.index)));
    const key = `${keyPrefix}-${index++}`;
    if (match[1]) {
      out.push(
        <code key={key} className="rounded bg-sunk px-1 py-0.5 font-mono text-[0.9em]">
          {match[1].slice(1, -1)}
        </code>,
      );
    } else if (match[2]) {
      const src = safeHref(match[4] ?? "");
      const alt = unescape(match[3] ?? "");
      out.push(
        src && !src.startsWith("mailto:") ? (
          // Arbitrary remote hosts, so next/image's optimiser is not usable here.
          // eslint-disable-next-line @next/next/no-img-element
          <img
            key={key}
            src={src}
            alt={alt}
            loading="lazy"
            className="my-2 inline-block max-h-64 max-w-full rounded-lg border border-line align-middle"
          />
        ) : (
          <span key={key} className="text-ink-faint">
            [image: {alt || "untitled"}]
          </span>
        ),
      );
    } else if (match[5]) {
      const href = safeHref(match[7] ?? "");
      const label = match[6] ?? "";
      out.push(
        href ? (
          <a
            key={key}
            href={href}
            target="_blank"
            rel="noreferrer nofollow"
            className="text-leaf-700 underline underline-offset-2"
          >
            {label ? nested(label, key) : href}
          </a>
        ) : (
          <span key={key}>{nested(label, key)}</span>
        ),
      );
    } else if (match[8]) {
      out.push(<strong key={key}>{nested(match[9] ?? "", key)}</strong>);
    } else if (match[10]) {
      out.push(<em key={key}>{nested(match[11] ?? "", key)}</em>);
    }
    last = pattern.lastIndex;
  }
  if (last < text.length) out.push(unescape(text.slice(last)));
  return out;
}

/** Walk a parsed table into React elements, keeping only what an allowlist permits. */
function element(node: Node, key: string): ReactNode {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent;
  if (node.nodeType !== Node.ELEMENT_NODE) return null;
  const el = node as Element;
  if (!TABLE_TAGS.has(el.tagName)) {
    // Not permitted: keep the text, drop the element. A `<script>` contributes its source as
    // visible text and nothing else, which is the safe reading of an unexpected tag.
    return Array.from(el.childNodes).map((child, i) => element(child, `${key}-${i}`));
  }
  const children = Array.from(el.childNodes).map((child, i) => element(child, `${key}-${i}`));
  const props: Record<string, unknown> = { key };
  for (const name of KEPT_ATTRS) {
    const value = el.getAttribute(name);
    if (value && /^\d+$/.test(value)) props[name === "colspan" ? "colSpan" : "rowSpan"] = Number(value);
  }
  if (el.tagName === "A") {
    const href = safeHref(el.getAttribute("href") ?? "");
    if (!href) return children;
    return (
      <a {...props} href={href} target="_blank" rel="noreferrer nofollow" className="text-leaf-700 underline underline-offset-2">
        {children}
      </a>
    );
  }
  const Tag = el.tagName.toLowerCase() as "table";
  return <Tag {...props}>{children}</Tag>;
}

function htmlTable(source: string, key: string): ReactNode {
  if (typeof window === "undefined") return <pre key={key} className="overflow-x-auto">{source}</pre>;
  // `text/html` parsing is inert: no script runs, no resource is fetched.
  const parsed = new DOMParser().parseFromString(source, "text/html");
  const table = parsed.body.querySelector("table");
  if (!table) return <p key={key}>{source}</p>;
  return (
    <div key={key} className="my-3 overflow-x-auto">
      <table className="w-full border-collapse text-[13px] [&_td]:border [&_td]:border-line [&_td]:px-2 [&_td]:py-1 [&_th]:border [&_th]:border-line [&_th]:bg-sunk [&_th]:px-2 [&_th]:py-1">
        {Array.from(table.childNodes).map((child, i) => element(child, `${key}-${i}`))}
      </table>
    </div>
  );
}

export function renderMarkdown(source: string): ReactNode[] {
  const out: ReactNode[] = [];
  const lines = source.split("\n");
  let i = 0;
  let key = 0;

  while (i < lines.length) {
    // `noUncheckedIndexedAccess` is on: the loop guard makes this safe, the compiler cannot.
    const line = lines[i] ?? "";

    if (!line.trim()) {
      i += 1;
      continue;
    }

    if (line.trimStart().startsWith("<table")) {
      const start = i;
      while (i < lines.length && !(lines[i] ?? "").includes("</table>")) i += 1;
      out.push(htmlTable(lines.slice(start, i + 1).join("\n"), `t${key++}`));
      i += 1;
      continue;
    }

    if (line.startsWith("```")) {
      const language = line.slice(3).trim();
      const start = ++i;
      while (i < lines.length && !(lines[i] ?? "").startsWith("```")) i += 1;
      out.push(
        <pre key={`c${key++}`} className="my-3 overflow-x-auto rounded-lg border border-line bg-sunk p-3 font-mono text-[12px] leading-relaxed">
          <code>{lines.slice(start, i).join("\n")}</code>
          {language && <span className="sr-only">{` (${language})`}</span>}
        </pre>,
      );
      i += 1;
      continue;
    }

    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      const level = (heading[1] ?? "#").length;
      const Tag = `h${Math.min(level + 1, 6)}` as "h2";
      const size = ["text-[1.35rem]", "text-[1.15rem]", "text-[1.02rem]", "text-[0.95rem]", "text-[0.9rem]", "text-[0.88rem]"][level - 1];
      out.push(
        <Tag key={`h${key++}`} className={`mt-4 mb-1.5 font-display leading-tight ${size}`}>
          {inline(heading[2] ?? "", `h${key}`)}
        </Tag>,
      );
      i += 1;
      continue;
    }

    if (/^\s*\|.*\|\s*$/.test(line)) {
      const start = i;
      while (i < lines.length && /^\s*\|/.test(lines[i] ?? "")) i += 1;
      const rows = lines
        .slice(start, i)
        .filter((row) => !/^\s*\|[\s:|-]*-{3,}[\s:|-]*\|?\s*$/.test(row))
        .map((row) => row.trim().replace(/^\||\|$/g, "").split("|").map((cell) => cell.trim()));
      const [header, ...body] = rows;
      out.push(
        <div key={`p${key++}`} className="my-3 overflow-x-auto">
          <table className="w-full border-collapse text-[13px]">
            <thead>
              <tr>
                {header?.map((cell, c) => (
                  <th key={c} className="border border-line bg-sunk px-2 py-1 text-left font-semibold">
                    {inline(cell, `th${c}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {body.map((row, r) => (
                <tr key={r}>
                  {row.map((cell, c) => (
                    <td key={c} className="border border-line px-2 py-1 align-top">
                      {inline(cell, `td${r}-${c}`)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }

    const bullet = /^\s*([-*+]|\d+\.)\s+/.exec(line);
    if (bullet) {
      const ordered = /\d/.test(bullet[1] ?? "");
      const marker = ordered ? /^\s*\d+\.\s+/ : /^\s*[-*+]\s+/;
      const items: string[] = [];
      // A "loose" list has a blank line between its items, and the engine emits ordered
      // lists that way. Stopping at the first blank line rendered `1. a / 2. b / 3. c` as
      // three one-item lists, every one of them numbered 1.
      while (i < lines.length) {
        const row = lines[i] ?? "";
        if (marker.test(row)) {
          items.push(row.replace(marker, ""));
          i += 1;
        } else if (!row.trim() && marker.test(lines[i + 1] ?? "")) {
          i += 1;
        } else {
          break;
        }
      }
      const first = Number.parseInt(bullet[1] ?? "1", 10);
      const Tag = ordered ? "ol" : "ul";
      out.push(
        <Tag
          key={`l${key++}`}
          className={`my-2 pl-5 ${ordered ? "list-decimal" : "list-disc"}`}
          {...(ordered && first > 1 ? { start: first } : {})}
        >
          {items.map((item, n) => (
            <li key={n} className="my-0.5">
              {inline(item, `li${n}`)}
            </li>
          ))}
        </Tag>,
      );
      continue;
    }

    if (line.startsWith(">")) {
      const start = i;
      while (i < lines.length && (lines[i] ?? "").startsWith(">")) i += 1;
      out.push(
        <blockquote key={`q${key++}`} className="my-3 border-l-2 border-leaf-300 pl-3 text-ink-soft">
          {inline(lines.slice(start, i).map((row) => row.replace(/^>\s?/, "")).join(" "), `q${key}`)}
        </blockquote>,
      );
      continue;
    }

    out.push(
      <p key={`t${key++}`} className="my-2 leading-relaxed">
        {inline(line, `p${key}`)}
      </p>,
    );
    i += 1;
  }

  return out;
}
