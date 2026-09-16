import type { Metadata } from "next";

import ProductGrid from "@/components/products/ProductGrid";

export const metadata: Metadata = {
  title: "Products",
  description:
    "One engine. The crawler and the CLI run today, WebGraph runs as a preview behind a flag; the rest is what the same output makes possible, and is marked so.",
};

export default function ProductsPage() {
  return (
    <main className="page-col max-md:pb-16 max-md:pt-12 md:pb-24 md:pt-20">
      <header>
        <h1 className="font-display text-h1 text-ink">Products</h1>
        <p className="measure-lede mt-4 text-body text-muted">
          One engine. The crawler and the CLI run today; WebGraph runs as a preview behind a
          flag; the rest is what the same output makes possible, and is marked so.
        </p>
      </header>

      <div className="max-md:mt-10 md:mt-12">
        <ProductGrid />
      </div>

      <p className="mt-8 max-w-prose text-caption text-muted">
        &ldquo;Coming soon&rdquo; is the only future-tense claim on this site. Nothing marked so
        exists yet; the repository today has the crawler, the API, the CLI and WebGraph behind{" "}
        <code className="rounded-sm bg-sunk px-1 py-0.5 font-mono text-[0.9em]">WEBGRAPH_KG=1</code>.
      </p>
    </main>
  );
}
