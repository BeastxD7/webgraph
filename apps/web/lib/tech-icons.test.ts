import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { GENERIC_PATH, MAPPED_TECH, TECH_ALIASES, techEntry, techIcon } from "./tech-icons.ts";

// The engine is the source of truth for what can be named. Every name it can emit is read
// from its source here, so a rule added there without a mark here fails this test rather
// than falling back to the generic glyph unnoticed.
const ENGINE = join(dirname(fileURLToPath(import.meta.url)), "../../../packages/engine/src/webgraph");

function names(file: string, pattern: RegExp): string[] {
  const source = readFileSync(join(ENGINE, file), "utf8");
  return [...new Set([...source.matchAll(pattern)].map((m) => m[1] ?? ""))].filter(Boolean);
}

const RULE_NAMES = names("profile/technology.py", /\b_rule\(\s*"([^"]+)"/g);
const IMPLIED_NAMES = names("profile/technology.py", /\bImplication\(\s*"([^"]+)"/g);
const RUNTIME_CATEGORY_NAMES = (() => {
  // The keys of `_RUNTIME_CATEGORIES`, the names only a browser run can report.
  const source = readFileSync(join(ENGINE, "profile/technology.py"), "utf8");
  const block = source.slice(source.indexOf("_RUNTIME_CATEGORIES"));
  return [...block.slice(0, block.indexOf("}")).matchAll(/"([^"]+)":\s*"/g)].map((m) => m[1] ?? "").filter(Boolean);
})();
const PROBE_NAMES = names("fetch/js/collect.js", /\bprobe\(\s*'([^']+)'/g);
const FINGERPRINT_NAMES = names("profile/fingerprint.py", /\b_rule\(\s*"([^"]+)"/g);

const ENGINE_NAMES = [
  ...new Set([...RULE_NAMES, ...IMPLIED_NAMES, ...RUNTIME_CATEGORY_NAMES, ...PROBE_NAMES, ...FINGERPRINT_NAMES]),
];

test("the engine's name lists were actually read", () => {
  assert.ok(RULE_NAMES.length > 100, `technology.py rules: ${RULE_NAMES.length}`);
  assert.ok(IMPLIED_NAMES.includes("shadcn/ui"));
  assert.ok(RUNTIME_CATEGORY_NAMES.includes("Preact"));
  assert.ok(PROBE_NAMES.includes("D3"));
  assert.ok(FINGERPRINT_NAMES.includes("wordpress"));
});

test("every name the engine can emit resolves to a mark or an explicit generic", () => {
  const unmapped = ENGINE_NAMES.filter((name) => techEntry(name) === undefined);
  assert.deepEqual(unmapped, [], `add these to ICONS (or ALIASES) in lib/tech-icons.ts: ${unmapped.join(", ")}`);
});

test("the map is not all generic: the common stack has real marks", () => {
  for (const name of ["Next.js", "React", "WordPress", "nginx", "Cloudflare", "Astro", "Webflow", "Tailwind CSS", "jQuery"]) {
    assert.equal(techEntry(name)?.kind, "icon", name);
    assert.equal(techIcon(name).generic, false, name);
    assert.notEqual(techIcon(name).path, GENERIC_PATH, name);
  }
});

test("matching is by name, not by case or spacing", () => {
  assert.equal(techEntry("next.js")?.key, "Next.js");
  assert.equal(techEntry("wordpress")?.key, "WordPress");
  assert.equal(techEntry("Wordpress")?.key, "WordPress");
  assert.equal(techEntry("vue")?.key, "Vue.js");
  assert.equal(techEntry("sveltekit")?.key, "Svelte");
  assert.equal(techEntry("  Tailwind   CSS ")?.key, "Tailwind CSS");
  assert.equal(techEntry("HTML")?.key, "HTML5");
  assert.equal(techEntry("Vanilla JavaScript")?.key, "JavaScript");
  assert.equal(techEntry("Google Analytics 4")?.key, "Google Analytics");
});

test("an unknown name gets the generic glyph, and the map says so", () => {
  assert.equal(techEntry("Some Framework Nobody Wrote"), undefined);
  const mark = techIcon("Some Framework Nobody Wrote");
  assert.equal(mark.generic, true);
  assert.equal(mark.path, GENERIC_PATH);
  // and an explicit generic is a decision, distinguishable from the fallback
  assert.equal(techEntry("HSTS")?.kind, "generic");
  assert.equal(techEntry("Open Graph")?.kind, "generic");
  assert.equal(techIcon("HSTS").generic, true);
});

test("no two names share a mark unless one is declared an alias of the other", () => {
  const bySlug = new Map<string, string[]>();
  for (const { name, slug } of MAPPED_TECH) {
    if (slug) bySlug.set(slug, [...(bySlug.get(slug) ?? []), name]);
  }
  const shared = [...bySlug.entries()].filter(([, owners]) => owners.length > 1);
  assert.deepEqual(shared, [], `these canonical entries share an icon; make one an alias: ${JSON.stringify(shared)}`);
  // Every alias points at a canonical entry (the module throws otherwise, but say it here too).
  const canonical = new Set(MAPPED_TECH.map((entry) => entry.name));
  for (const [alias, target] of Object.entries(TECH_ALIASES)) assert.ok(canonical.has(target), `${alias} -> ${target}`);
});

test("every mark is a path on the 24-unit grid", () => {
  for (const { name } of MAPPED_TECH) {
    const mark = techIcon(name);
    assert.ok(mark.path.length > 10, name);
    assert.match(mark.path, /^[Mm]/, name);
  }
});
