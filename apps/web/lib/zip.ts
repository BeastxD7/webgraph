/**
 * A zip archive of text files, written in the browser with no library.
 *
 * Stored, not deflated: the entries are Markdown a few kilobytes each, the archive is
 * downloaded once, and a dependency for the sake of a smaller file would be the wrong
 * trade. The format is the minimum a reader needs -- local headers, a central directory,
 * the end record -- with UTF-8 names (general-purpose bit 11) and the CRC-32 every reader
 * checks. Dates are the moment of writing, in the DOS form the format asks for.
 */

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

function crc32(bytes: Uint8Array): number {
  let crc = 0xffffffff;
  for (let i = 0; i < bytes.length; i++) crc = CRC_TABLE[(crc ^ bytes[i]!) & 0xff]! ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

function dosDateTime(date: Date): { time: number; date: number } {
  const time = (date.getHours() << 11) | (date.getMinutes() << 5) | (date.getSeconds() >> 1);
  const day = ((date.getFullYear() - 1980) << 9) | ((date.getMonth() + 1) << 5) | date.getDate();
  return { time, date: day };
}

export interface ZipEntry {
  /** The path inside the archive, forward slashes, no leading slash. */
  name: string;
  content: string;
}

/** The archive as bytes, ready for a Blob. */
export function zipText(entries: readonly ZipEntry[], now: Date = new Date()): Uint8Array<ArrayBuffer> {
  const encoder = new TextEncoder();
  const stamp = dosDateTime(now);
  const locals: Uint8Array[] = [];
  const central: Uint8Array[] = [];
  let offset = 0;

  for (const entry of entries) {
    const name = encoder.encode(entry.name);
    const data = encoder.encode(entry.content);
    const crc = crc32(data);

    const local = new DataView(new ArrayBuffer(30 + name.length));
    local.setUint32(0, 0x04034b50, true);
    local.setUint16(4, 20, true); // version needed: 2.0
    local.setUint16(6, 0x0800, true); // UTF-8 names
    local.setUint16(8, 0, true); // stored
    local.setUint16(10, stamp.time, true);
    local.setUint16(12, stamp.date, true);
    local.setUint32(14, crc, true);
    local.setUint32(18, data.length, true);
    local.setUint32(22, data.length, true);
    local.setUint16(26, name.length, true);
    local.setUint16(28, 0, true);
    const localBytes = new Uint8Array(local.buffer);
    localBytes.set(name, 30);

    const dir = new DataView(new ArrayBuffer(46 + name.length));
    dir.setUint32(0, 0x02014b50, true);
    dir.setUint16(4, 20, true); // version made by
    dir.setUint16(6, 20, true); // version needed
    dir.setUint16(8, 0x0800, true);
    dir.setUint16(10, 0, true);
    dir.setUint16(12, stamp.time, true);
    dir.setUint16(14, stamp.date, true);
    dir.setUint32(16, crc, true);
    dir.setUint32(20, data.length, true);
    dir.setUint32(24, data.length, true);
    dir.setUint16(28, name.length, true);
    dir.setUint16(30, 0, true); // extra
    dir.setUint16(32, 0, true); // comment
    dir.setUint16(34, 0, true); // disk
    dir.setUint16(36, 0, true); // internal attributes
    dir.setUint32(38, 0, true); // external attributes
    dir.setUint32(42, offset, true);
    const dirBytes = new Uint8Array(dir.buffer);
    dirBytes.set(name, 46);

    locals.push(localBytes, data);
    central.push(dirBytes);
    offset += localBytes.length + data.length;
  }

  const directorySize = central.reduce((sum, part) => sum + part.length, 0);
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true);
  end.setUint16(4, 0, true);
  end.setUint16(6, 0, true);
  end.setUint16(8, entries.length, true);
  end.setUint16(10, entries.length, true);
  end.setUint32(12, directorySize, true);
  end.setUint32(16, offset, true);
  end.setUint16(20, 0, true);

  const parts = [...locals, ...central, new Uint8Array(end.buffer)];
  const out = new Uint8Array(new ArrayBuffer(parts.reduce((sum, part) => sum + part.length, 0)));
  let at = 0;
  for (const part of parts) {
    out.set(part, at);
    at += part.length;
  }
  return out;
}

/**
 * A file name for a page inside the archive: the host and path, as Firecrawl and most
 * exporters name them, so a folder of them sorts by site and section.
 * `https://lakshx.in/docs/sign-in` -> `lakshx.in/docs/sign-in.md`; the root -> `lakshx.in/index.md`.
 */
export function pageFileName(url: string): string {
  try {
    const u = new URL(url);
    const path = u.pathname.replace(/\/+$/, "");
    const stem = path ? path.replace(/^\//, "") : "index";
    return `${u.hostname}/${stem.replace(/[^A-Za-z0-9._\-/]+/g, "_")}.md`;
  } catch {
    return `${url.replace(/[^A-Za-z0-9._-]+/g, "_")}.md`;
  }
}

/** Front matter naming the page, so a file opened alone still says where it came from. */
export function withFrontMatter(url: string, title: string, markdown: string): string {
  const quote = (value: string) => JSON.stringify(value);
  return `---\nurl: ${quote(url)}\ntitle: ${quote(title)}\n---\n\n${markdown}`;
}
