import type { ReactNode } from "react";

import Button from "@/components/ui/Button";
import Chip from "@/components/ui/Chip";

import type { Cta, Product } from "./products";

/** Backtick spans become inline code; nothing else is interpreted. */
function inline(text: string): ReactNode[] {
  return text.split(/(`[^`]+`)/g).map((part, index) =>
    part.startsWith("`") && part.endsWith("`") ? (
      <code key={index} className="rounded-sm bg-sunk px-1 py-0.5 font-mono text-[0.9em]">
        {part.slice(1, -1)}
      </code>
    ) : (
      part
    ),
  );
}

function CtaLink({ cta, primary }: { cta: Cta; primary: boolean }) {
  const variant = primary ? "primary" : "secondary";
  if (cta.external) {
    return (
      <Button href={cta.href} external variant={variant}>
        {cta.label}
      </Button>
    );
  }
  return (
    <Button href={cta.href} variant={variant}>
      {cta.label}
    </Button>
  );
}

/**
 * One cell of the composed grid. No border of its own: the grid draws the rules. The title
 * stays `ink` whatever the availability; the chip carries the state.
 */
export default function ProductCard({ product }: { product: Product }) {
  const available = product.availability === "available";
  return (
    <article
      id={product.id}
      aria-labelledby={`${product.id}-title`}
      className="flex min-w-0 flex-col bg-surface p-6"
    >
      <div>
        <Chip tone={available ? "available" : "coming"}>
          {available ? (product.note ? `Available — ${product.note}` : "Available") : "Coming soon"}
        </Chip>
      </div>
      <h2 id={`${product.id}-title`} className="mt-4 text-h3 font-bold text-ink">
        {product.name}
      </h2>
      <div className="mt-3 flex flex-col gap-3 text-small text-muted">
        {product.body.map((paragraph, index) => (
          <p key={index} className="measure-prose">
            {inline(paragraph)}
          </p>
        ))}
      </div>
      <div className="mt-auto flex flex-wrap gap-2 pt-6">
        {product.ctas.map((cta, index) => (
          <CtaLink key={cta.label} cta={cta} primary={available && index === 0} />
        ))}
      </div>
    </article>
  );
}
