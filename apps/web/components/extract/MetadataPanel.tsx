"use client";

import type { ReactNode } from "react";

import type { PageMetadata } from "@/lib/api";
import { prettyUrl } from "@/lib/format";

/**
 * What the page declares about itself -- its `<head>`, as a crawler, a search engine or a
 * share card reads it -- shown beside the technology profile, since it is the same kind of
 * fact: what the site *says*, before what it is.
 *
 * The contradictions come first. `declared_elsewhere` lists the declarations that name a
 * different site from the one that served the page; a site that moved domains and kept its
 * old `metadataBase` in its framework config does exactly this, nothing on the page shows
 * it, and every crawler that trusts a canonical trips on it. Then the share card as it
 * would render, then the rest as a plain list.
 *
 * `heading` is the panel's name in its context: a site run says "Site metadata", a single
 * page "Page metadata".
 */
export default function MetadataPanel({ metadata, heading = "Site metadata" }: { metadata: PageMetadata; heading?: string }) {
  const og = metadata.open_graph;
  const card = {
    title: og["og:title"] ?? metadata.twitter["twitter:title"] ?? metadata.title,
    description: og["og:description"] ?? metadata.twitter["twitter:description"] ?? metadata.description,
    image: og["og:image"] ?? metadata.twitter["twitter:image"] ?? null,
    site: og["og:site_name"] ?? null,
    type: og["og:type"] ?? null,
    twitterCard: metadata.twitter["twitter:card"] ?? null,
  };
  const hasCard = Boolean(card.title || card.description || card.image);
  const declared = Object.keys(og).length + Object.keys(metadata.twitter).length;

  return (
    <section className="rounded-2xl border border-line bg-surface p-6 shadow-card">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 className="text-[15px] font-extrabold tracking-tight">{heading}</h2>
        <p className="text-caption text-ink-faint">
          what <span className="font-mono">{prettyUrl(metadata.url)}</span> declares in its{" "}
          <code className="font-mono">&lt;head&gt;</code>
        </p>
      </div>

      {metadata.declared_elsewhere.length > 0 && (
        <div className="mt-4 rounded-xl border border-flag-warn/30 bg-flag-warn/10 px-4 py-3">
          <p className="text-small font-bold text-flag-warn">Declares another site as its own</p>
          <ul className="mt-1 space-y-0.5">
            {metadata.declared_elsewhere.map((line) => (
              <li key={line} className="font-mono text-small text-ink-soft">
                {line}
              </li>
            ))}
          </ul>
          <p className="mt-1.5 text-small text-ink-soft">
            Nothing on the page shows this. Search engines and share previews follow the declared
            address; a crawler that resolves links against it leaves the site. Usually a framework&apos;s
            base URL left at a previous host.
          </p>
        </div>
      )}

      <div className="mt-4 grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        {/* The share card, as a link to this page would render it. */}
        <div>
          <p className="text-label font-bold uppercase tracking-[0.1em] text-ink-faint">Share card</p>
          {hasCard ? (
            <div className="mt-2 overflow-hidden rounded-xl border border-line bg-haze">
              {card.image && (
                // Arbitrary remote host, so next/image's optimiser is not usable here.
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={card.image}
                  alt=""
                  loading="lazy"
                  referrerPolicy="no-referrer"
                  className="aspect-[1.91/1] w-full object-cover"
                  // A declared image that does not load (the old host, a hotlink block) is
                  // itself a finding; the card shows its text without a grey block.
                  onError={(e) => { e.currentTarget.style.display = "none"; }}
                />
              )}
              <div className="px-4 py-3">
                <p className="text-label font-bold uppercase tracking-[0.1em] text-ink-faint">
                  {card.site ?? prettyUrl(metadata.url).split("/")[0]}
                </p>
                {card.title && <p className="mt-0.5 text-small font-bold text-ink">{card.title}</p>}
                {card.description && (
                  <p className="mt-0.5 line-clamp-3 text-small text-ink-soft">{card.description}</p>
                )}
              </div>
            </div>
          ) : (
            <p className="mt-2 text-small text-ink-faint">
              No Open Graph or Twitter card declared: a link to this page previews as its bare URL.
            </p>
          )}
          <p className="mt-2 text-caption text-ink-faint">
            {declared} share {declared === 1 ? "property" : "properties"}
            {card.type ? ` · og:type ${card.type}` : ""}
            {card.twitterCard ? ` · twitter:card ${card.twitterCard}` : ""}
          </p>
        </div>

        <dl className="self-start">
          <Row label="Title" value={metadata.title} />
          <Row label="Description" value={metadata.description} />
          <Row
            label="Canonical"
            value={metadata.canonical}
            tone={metadata.declared_elsewhere.some((d) => d.startsWith("canonical")) ? "warn" : undefined}
          />
          <Row label="Language" value={metadata.language} />
          <Row label="Robots" value={metadata.robots} />
          <Row label="Generator" value={metadata.generator} />
          <Row label="Author" value={metadata.author} />
          <Row
            label="Icon"
            value={
              metadata.icons.length ? (
                <span className="inline-flex items-center gap-2">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={metadata.icons[0]} alt="" width={16} height={16} loading="lazy" referrerPolicy="no-referrer" className="size-4 rounded-sm" onError={(e) => { e.currentTarget.style.display = "none"; }} />
                  <span>{metadata.icons.length === 1 ? prettyUrl(metadata.icons[0]!) : `${metadata.icons.length} icons`}</span>
                </span>
              ) : null
            }
          />
          <Row label="Theme colour" value={metadata.theme_color ? <span className="inline-flex items-center gap-2"><span className="size-3 rounded-sm border border-line" style={{ background: metadata.theme_color }} />{metadata.theme_color}</span> : null} />
          <Row label="Schema.org types" value={metadata.schema_types.length ? metadata.schema_types.join(", ") : null} />
          <Row label="Feeds" value={metadata.feeds.length ? metadata.feeds.map(prettyUrl).join(", ") : null} />
          <Row label="Languages offered" value={metadata.alternate_count ? `${metadata.alternate_count} (${metadata.alternates.map((a) => a.hreflang).slice(0, 8).join(", ")}${metadata.alternate_count > 8 ? ", …" : ""})` : null} />
          <Row label="Manifest" value={metadata.manifest ? prettyUrl(metadata.manifest) : null} />
          <Row label="Keywords" value={metadata.keywords} />
          <Row label="Charset · viewport" value={[metadata.charset, metadata.viewport].filter(Boolean).join(" · ") || null} />
        </dl>
      </div>
    </section>
  );
}

/** One declaration. A missing one is shown as missing, in the faint colour, rather than
 * dropped: "no description" is a finding, and a list that only names what exists hides it. */
function Row({ label, value, tone }: { label: string; value: ReactNode | null | undefined; tone?: "warn" }) {
  const missing = value === null || value === undefined || value === "";
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-line-soft py-1.5 last:border-b-0">
      <dt className="shrink-0 text-caption text-ink-faint">{label}</dt>
      <dd
        className={`min-w-0 break-words text-right font-mono text-caption ${
          missing ? "text-ink-faint" : tone === "warn" ? "text-flag-warn" : "text-ink-soft"
        }`}
      >
        {missing ? "—" : value}
      </dd>
    </div>
  );
}
