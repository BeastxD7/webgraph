import type { MDXComponents } from "mdx/types";
import defaultMdxComponents from "fumadocs-ui/mdx";
import { Accordion, Accordions } from "fumadocs-ui/components/accordion";
import { Step, Steps } from "fumadocs-ui/components/steps";
import { Tab, Tabs } from "fumadocs-ui/components/tabs";

/**
 * Components every docs page can use without importing them. The defaults cover
 * headings, links, images, tables, code blocks, `Callout` and `Cards`/`Card`; the rest
 * are listed in `content/docs/_authoring.md`.
 */
export function getMDXComponents(components?: MDXComponents): MDXComponents {
  return {
    ...defaultMdxComponents,
    Tabs,
    Tab,
    Steps,
    Step,
    Accordions,
    Accordion,
    ...components,
  };
}
