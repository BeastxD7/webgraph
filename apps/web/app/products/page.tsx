import type { Metadata } from "next";

import ProductGrid from "@/components/products/ProductGrid";

export const metadata: Metadata = {
  title: "Products",
  description:
    "One engine. The crawler, the CLI, the Site Truth Report and Watch are what run today; WebGraph is what the same output makes possible next, and is marked so.",
};

export default function ProductsPage() {
  return (
    <main className="page-col max-md:pb-16 max-md:pt-12 md:pb-24 md:pt-20">
      <header>
        <h1 className="font-display text-h1 text-ink">Products</h1>
        <p className="measure-lede mt-4 text-body text-muted">
          One engine. The crawler, the CLI, the Site Truth Report and Watch are what run today;
          WebGraph is what the same output makes possible next, and is marked so.
        </p>
      </header>

      <div className="max-md:mt-10 md:mt-12">
        <ProductGrid />
      </div>

      <p className="mt-8 max-w-prose text-caption text-muted">
        &ldquo;Coming soon&rdquo; is the only future-tense claim on this site. Nothing marked so
        exists yet; the repository today has the crawler, the API, the CLI, the Site Truth
        Report and Watch.
      </p>
    </main>
  );
}
