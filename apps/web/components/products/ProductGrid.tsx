import ProductCard from "./ProductCard";
import { PRODUCTS } from "./products";

/**
 * The cards as one object (DESIGN.md §4b): a shared rule border and radius on the outer
 * element, a 1px gap that reads as the inner rules, equal heights from the grid. One column
 * below 768px. With an odd count the last card takes the full row, so the object has no
 * empty cell showing the rule colour through it.
 */
export default function ProductGrid() {
  return (
    <div className="grid gap-px overflow-hidden rounded-md border border-rule bg-rule md:grid-cols-2 md:[&>*:last-child:nth-child(odd)]:col-span-2">
      {PRODUCTS.map((product) => (
        <ProductCard key={product.id} product={product} />
      ))}
    </div>
  );
}
