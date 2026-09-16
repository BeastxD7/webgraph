import type { ReactNode } from "react";

import Chip, { type ChipTone } from "@/components/ui/Chip";
import CopyButton from "@/components/ui/CopyButton";
import EvidenceRow from "@/components/ui/EvidenceRow";
import type { BotAccess, Finding, ReportPage, Severity, SiteReport, SubScore } from "@/lib/api";
import { duration, percent, prettyUrl } from "@/lib/format";

const SEVERITY: Record<Severity, { tone: ChipTone; label: string }> = {
  high: { tone: "refused", label: "High" },
  medium: { tone: "assumed", label: "Medium" },
  low: { tone: "plain", label: "Low" },
  info: { tone: "plain", label: "Note" },
};

const ACCESS: Record<BotAccess, { tone: ChipTone; label: string }> = {
  allowed: { tone: "measured", label: "Allowed" },
  restricted: { tone: "assumed", label: "Restricted" },
  blocked: { tone: "refused", label: "Blocked" },
};

const VIA: Record<string, string> = {
  named: "named",
  wildcard: "via *",
  none: "not mentioned",
};

function Section({ id, title, lede, children }: { id: string; title: string; lede?: ReactNode; children: ReactNode }) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="border-t border-rule py-10">
      <h2 id={`${id}-title`} className="font-display text-h2 text-ink">
        {title}
      </h2>
      {lede && <p className="measure-prose mt-2 text-small text-muted">{lede}</p>}
      <div className="mt-6">{children}</div>
    </section>
  );
}

function pathOf(url: string): string {
  try {
    const parsed = new URL(url);
    return `${parsed.pathname}${parsed.search}` || "/";
  } catch {
    return url;
  }
}

function CodeFile({ name, text, note }: { name: string; text: string; note?: string }) {
  return (
    <figure className="min-w-0">
      <figcaption className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-mono text-code font-semibold text-ink">{name}</span>
        <CopyButton text={text} label={`Copy ${name}`} />
      </figcaption>
      {note && <p className="measure-prose mt-2 text-caption text-muted">{note}</p>}
      <pre className="mt-3 max-h-[32rem] overflow-auto rounded-md border border-rule bg-surface p-4 font-mono text-code leading-relaxed text-ink">
        <code>{text}</code>
      </pre>
    </figure>
  );
}

function ScoreRow({ sub }: { sub: SubScore }) {
  const value =
    sub.score === null ? "unmeasured" : `${sub.score.toLocaleString("en-US", { maximumFractionDigits: 1 })} / ${sub.weight}`;
  return (
    <EvidenceRow
      label={sub.label}
      value={
        <>
          <span className="tabular font-mono text-code font-semibold">{value}</span>
          <span className="text-muted"> — {sub.evidence}</span>
        </>
      }
      source={
        sub.recommendation || sub.source ? (
          <>
            {sub.recommendation && <span className="text-ink">{sub.recommendation}</span>}
            {sub.source && (
              <>
                {sub.recommendation ? " " : null}
                <a href={sub.source} target="_blank" rel="noreferrer" className="text-accent-ink underline underline-offset-2">
                  {pathOf(sub.source)}
                </a>
              </>
            )}
          </>
        ) : undefined
      }
    />
  );
}

function FindingRow({ finding }: { finding: Finding }) {
  const severity = SEVERITY[finding.severity];
  return (
    <li className="grid gap-x-4 gap-y-1 border-b border-rule py-3 sm:grid-cols-[5.5rem_1fr]">
      <div>
        <Chip tone={severity.tone}>{severity.label}</Chip>
      </div>
      <div className="min-w-0">
        <p className="text-small font-semibold text-ink">{finding.title}</p>
        <p className="mt-1 break-words text-small text-muted">{finding.detail}</p>
        {finding.page && (
          <a href={finding.page} target="_blank" rel="noreferrer" className="mt-1 inline-block break-all font-mono text-caption text-accent-ink underline underline-offset-2">
            {prettyUrl(finding.page)}
          </a>
        )}
      </div>
    </li>
  );
}

function PageRowCells({ page }: { page: ReportPage }) {
  if (page.error) {
    return (
      <td colSpan={7} className="py-2 pr-3 text-caption text-bad">
        not read: {page.error}
      </td>
    );
  }
  const hidden = Object.values(page.hidden_words).reduce((a, b) => a + b, 0);
  return (
    <>
      <td className="tabular py-2 pr-3 text-right font-mono text-code">{page.static_words.toLocaleString("en-US")}</td>
      <td className="tabular py-2 pr-3 text-right font-mono text-code">{page.rendered_words.toLocaleString("en-US")}</td>
      <td className="tabular py-2 pr-3 text-right font-mono text-code">
        {page.union_words.toLocaleString("en-US")}
        <span className="text-muted"> ({percent(page.static_coverage)})</span>
      </td>
      <td className="py-2 pr-3">
        {page.wall ? <Chip tone="refused">{page.wall}</Chip> : <span className="text-muted">none</span>}
      </td>
      <td className="tabular py-2 pr-3 text-right font-mono text-code">
        {hidden.toLocaleString("en-US")} w · {page.hidden_links} l
        {page.offscreen_links > 0 && (
          <span className={page.offscreen_external_hosts >= 5 ? "text-bad" : page.offscreen_external_hosts > 0 ? "text-warn" : "text-muted"}>
            {" "}
            · {page.offscreen_links} off-screen, {page.offscreen_external_hosts} foreign hosts
          </span>
        )}
      </td>
      <td className="tabular py-2 pr-3 text-right font-mono text-code">
        {page.dead_count} / {page.links_checked}
      </td>
      <td className="py-2 pr-3 text-caption text-muted">
        {[page.has_schema ? "schema" : null, page.lang ? `lang=${page.lang}` : null, page.description ? "description" : null, page.in_sitemap === true ? "in sitemap" : page.in_sitemap === false ? "not in sitemap" : null]
          .filter(Boolean)
          .join(" · ") || "—"}
      </td>
    </>
  );
}

/**
 * The report, top to bottom: the score with its parts as evidence rows, the integrity
 * findings, the stack, the pages, the bots table, the two suggested files, and how it was
 * measured. Every number sits beside what it was measured on (DESIGN.md §1.4).
 */
export default function ReportView({ report }: { report: SiteReport }) {
  const generated = new Date(report.generated_at);
  const when = Number.isNaN(generated.getTime()) ? report.generated_at : generated.toUTCString();

  if (!report.reachable) {
    return (
      <article>
        <header className="py-8">
          <p className="text-label uppercase tracking-[0.12em] text-muted">Site report</p>
          <h1 className="mt-2 font-display text-h1 text-ink">{report.host || prettyUrl(report.url)}</h1>
          <p className="mt-2 font-mono text-code text-muted">{report.url}</p>
        </header>
        <section role="status" className="border-t border-rule py-8">
          <div>
            <Chip tone="refused">No report</Chip>
          </div>
          <p className="measure-prose mt-4 text-body text-ink">
            The root could not be read, so there is no score. The engine&apos;s own words:
          </p>
          <p className="mt-3 break-words font-mono text-code text-ink">{report.refusal}</p>
          <p className="measure-prose mt-4 text-small text-muted">
            The engine does not disguise itself to get past a refusal. If the site is yours,
            the message above names the rule or the wall; if it is not, that is the site&apos;s answer.
          </p>
        </section>
        {report.measured && <MeasuredFooter report={report} />}
      </article>
    );
  }

  const score = report.score;
  const robots = report.robots;
  const pagesRead = report.pages.filter((p) => !p.error);

  return (
    <article>
      <header className="py-8">
        <p className="text-label uppercase tracking-[0.12em] text-muted">Site report</p>
        <h1 className="mt-2 font-display text-h1 text-ink">{report.host}</h1>
        <p className="mt-2 break-all font-mono text-code text-muted">{report.root}</p>
        <p className="mt-1 text-caption text-muted">
          Generated {when} · {report.pages.length} page{report.pages.length === 1 ? "" : "s"} sampled
        </p>
      </header>

      {score && (
        <Section
          id="score"
          title="AI-readiness"
          lede="Eight sub-scores, each from one measurement, each with its evidence. An unmeasured part is left out and the total is rescaled to what was measured."
        >
          <div className="grid gap-8 lg:grid-cols-[14rem_1fr]">
            <div>
              <p className="tabular font-display text-stat text-ink">
                {score.total}
                <span className="text-h3 text-muted">/100</span>
              </p>
              <p className="mt-2 text-small font-bold text-ink">AI-readiness score</p>
              <p className="mt-1 text-caption text-muted">
                {score.measured_weight < 100
                  ? `${score.measured_weight} of 100 points could be measured; the total is rescaled to them.`
                  : "All 100 points measured."}
              </p>
            </div>
            <dl>
              {score.subscores.map((sub) => (
                <ScoreRow key={sub.key} sub={sub} />
              ))}
            </dl>
          </div>
        </Section>
      )}

      <Section
        id="integrity"
        title="Integrity"
        lede={`Injected links, walls, an old stack. "Likely SEO-spam injection" is said only when five or more foreign hosts are linked from elements parked off the page -- where no reader can scroll -- on one page. A hidden dropdown is not that.`}
      >
        {report.findings.length ? (
          <ul>
            {report.findings.map((finding, index) => (
              <FindingRow key={`${finding.kind}-${index}`} finding={finding} />
            ))}
          </ul>
        ) : (
          <p className="text-small text-muted">Nothing found on the sampled pages.</p>
        )}
      </Section>

      <Section id="stack" title="Stack" lede="What the root page's markup, headers and runtime say it is built with. A version is dated when its branch is in the report's release table; otherwise the version alone.">
        {report.stack.length ? (
          <ul className="flex flex-wrap gap-2">
            {report.stack.map((entry) => (
              <li key={`${entry.name}-${entry.version ?? ""}`} className="rounded-md border border-rule bg-surface px-3 py-1.5 text-small text-ink">
                {entry.name}
                {entry.version && <span className="font-mono text-code"> {entry.version}</span>}
                {entry.released && (
                  <span className={`text-caption ${entry.age_years !== null && entry.age_years >= 3 ? "text-warn" : "text-muted"}`}>
                    {" "}
                    · released {entry.released}
                    {entry.age_years !== null && `, ${entry.age_years} years ago`}
                  </span>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-small text-muted">None detected.</p>
        )}
      </Section>

      <Section
        id="pages"
        title="Pages"
        lede="Words in the plain HTML, words after a real browser ran the page, and the union of the two with the share the plain fetch holds. Hidden is words (w) and links (l) a reader cannot see -- a dropdown menu counts -- and, of those links, the ones parked off the page and the foreign hosts they point at."
      >
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] border-collapse text-small">
            <thead>
              <tr className="border-b border-rule-strong text-left text-caption text-muted">
                <th className="py-2 pr-3 font-medium">Page</th>
                <th className="py-2 pr-3 text-right font-medium">Without JS</th>
                <th className="py-2 pr-3 text-right font-medium">With JS</th>
                <th className="py-2 pr-3 text-right font-medium">Union</th>
                <th className="py-2 pr-3 font-medium">Wall</th>
                <th className="py-2 pr-3 text-right font-medium">Hidden</th>
                <th className="py-2 pr-3 text-right font-medium">Dead links</th>
                <th className="py-2 pr-3 font-medium">Declares</th>
              </tr>
            </thead>
            <tbody>
              {report.pages.map((page) => (
                <tr key={page.requested_url} className="border-b border-rule align-top">
                  <td className="max-w-[16rem] py-2 pr-3">
                    <a href={page.requested_url} target="_blank" rel="noreferrer" className="break-all font-mono text-code text-accent-ink underline underline-offset-2">
                      {pathOf(page.requested_url)}
                    </a>
                    {page.title && <p className="mt-0.5 text-caption text-muted">{page.title}</p>}
                  </td>
                  <PageRowCells page={page} />
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {pagesRead.some((p) => p.render_error || p.static_error) && (
          <ul className="mt-4 flex flex-col gap-1 text-caption text-muted">
            {pagesRead
              .filter((p) => p.render_error || p.static_error)
              .map((p) => (
                <li key={p.requested_url} className="break-words">
                  <span className="font-mono">{pathOf(p.requested_url)}</span>: {p.static_error ?? p.render_error}
                </li>
              ))}
          </ul>
        )}
      </Section>

      {robots && (
        <Section
          id="bots"
          title="What robots.txt declares per bot"
          lede={
            robots.found
              ? "Read as each bot would read the file: the group naming it, else the * group. Blocked means the root is disallowed; restricted means some paths are. Nothing here was fetched as any of these bots."
              : "No robots.txt was found, so by the convention every crawler follows, every bot is allowed everywhere. Nothing here was fetched as any of these bots."
          }
        >
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] border-collapse text-small">
              <thead>
                <tr className="border-b border-rule-strong text-left text-caption text-muted">
                  <th className="py-2 pr-3 font-medium">Bot</th>
                  <th className="py-2 pr-3 font-medium">Operator</th>
                  <th className="py-2 pr-3 font-medium">Purpose</th>
                  <th className="py-2 pr-3 font-medium">Declared</th>
                  <th className="py-2 pr-3 font-medium">Via</th>
                  <th className="py-2 pr-3 text-right font-medium">Disallowed paths</th>
                  <th className="py-2 pr-3 text-right font-medium">Crawl-delay</th>
                </tr>
              </thead>
              <tbody>
                {robots.bots.map((bot) => (
                  <tr key={bot.token} className="border-b border-rule align-top">
                    <td className="py-2 pr-3 font-mono text-code text-ink">{bot.token}</td>
                    <td className="py-2 pr-3 text-muted">{bot.operator}</td>
                    <td className="py-2 pr-3 text-muted">{bot.purpose}</td>
                    <td className="py-2 pr-3">
                      <Chip tone={ACCESS[bot.access].tone}>{ACCESS[bot.access].label}</Chip>
                    </td>
                    <td className="py-2 pr-3 text-muted">{VIA[bot.via] ?? bot.via}</td>
                    <td className="tabular py-2 pr-3 text-right font-mono text-code">{bot.disallowed}</td>
                    <td className="tabular py-2 pr-3 text-right font-mono text-code">{bot.crawl_delay === null ? "—" : `${bot.crawl_delay}s`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <dl className="mt-6">
            <EvidenceRow
              label="For this client"
              value={robots.found ? (robots.allows_us_root ? "the root is allowed" : "the root is disallowed") : "no file"}
              source={robots.rules_for_us.length ? `User-agent: ${robots.group_for_us} — ${robots.rules_for_us.join(" · ")}` : robots.found ? "no group applies to webgraph" : undefined}
            />
            <EvidenceRow
              label="Sitemap"
              value={report.sitemap_found ? `found, ${report.sitemap_urls.toLocaleString("en-US")} URLs` : "not found"}
              source={report.sitemap_attempts.map((a) => `${a.status} ${a.url}`).join(" · ") || undefined}
              mono={false}
            />
            <EvidenceRow
              label="llms.txt"
              value={report.llms_txt?.found ? `present: ${report.llms_txt.sections} sections, ${report.llms_txt.links} links${report.llms_full_txt?.found ? "; llms-full.txt present too" : ""}` : "not found"}
              source={report.llms_txt_note}
            />
          </dl>
        </Section>
      )}

      <Section
        id="suggested"
        title="Suggested files"
        lede="The robots.txt keeps the site's existing rules byte for byte; everything added is a comment, offering two variants the owner chooses between. Neither is a recommendation to block."
      >
        <div className="grid gap-8 xl:grid-cols-2">
          {report.suggested_robots_txt && <CodeFile name="robots.txt" text={report.suggested_robots_txt} />}
          {report.suggested_llms_txt && <CodeFile name="llms.txt" text={report.suggested_llms_txt} note={report.llms_txt_note} />}
        </div>
      </Section>

      {report.notes.length > 0 && (
        <Section id="notes" title="Notes">
          <ul className="flex flex-col gap-1 text-small text-muted">
            {report.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </Section>
      )}

      {report.measured && <MeasuredFooter report={report} />}
    </article>
  );
}

function MeasuredFooter({ report }: { report: SiteReport }) {
  const how = report.measured;
  if (!how) return null;
  return (
    <footer className="border-t border-rule-strong py-8 text-caption text-muted">
      <p className="text-label uppercase tracking-[0.12em]">How it was measured</p>
      <p className="mt-2">
        webgraph {how.engine_version} at <code className="font-mono">{how.commit}</code> · {how.pages_sampled} of{" "}
        {how.pages_requested} requested pages sampled · one request per {how.request_interval_seconds}s per host ·{" "}
        {duration(how.duration_seconds)} in all · browser render {how.render_available ? "available" : "unavailable"}.
      </p>
      <p className="measure-prose mt-2">{how.statement}</p>
      <p className="mt-2 break-all">
        User-Agent: <code className="font-mono">{how.user_agent}</code>
      </p>
    </footer>
  );
}
