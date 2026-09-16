import Link from "next/link";
import type { Route } from "next";
import type { ComponentPropsWithoutRef, ReactNode } from "react";

/**
 * The three buttons (DESIGN.md §6).
 *
 * primary   ink fill, inverse text -- one per view, the thing to do next
 * secondary transparent with a rule-strong border -- the other thing
 * quiet     no border, muted text -- toggles, menus, small controls
 *
 * 36px tall; 44px where the pointer is coarse, because a thumb is not a cursor. Focus is the
 * global `:focus-visible` ring and is never removed here.
 */
export type ButtonVariant = "primary" | "secondary" | "quiet";

const BASE =
  "inline-flex h-9 shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-md px-3.5 " +
  "text-small font-semibold transition-[color,background-color,opacity,border-color] duration-(--dur-fast) " +
  "ease-(--ease) pointer-coarse:min-h-11 disabled:pointer-events-none disabled:opacity-45 " +
  "aria-disabled:pointer-events-none aria-disabled:opacity-45";

const VARIANT: Record<ButtonVariant, string> = {
  primary: "bg-ink text-inverse hover:opacity-88 active:opacity-100 active:translate-y-[0.5px]",
  secondary: "border border-rule-strong bg-transparent text-ink hover:bg-sunk",
  quiet: "text-muted hover:text-ink active:bg-sunk",
};

export function buttonClass(variant: ButtonVariant = "primary", className = ""): string {
  return `${BASE} ${VARIANT[variant]} ${className}`.trim();
}

type Common = {
  variant?: ButtonVariant;
  className?: string;
  children: ReactNode;
};

type AsLink = Common & { href: Route; external?: false } & Omit<
    ComponentPropsWithoutRef<typeof Link>,
    "href" | "className" | "children"
  >;

type AsAnchor = Common & { href: string; external: true } & Omit<
    ComponentPropsWithoutRef<"a">,
    "href" | "className" | "children"
  >;

type AsButton = Common & { href?: undefined; external?: undefined } & Omit<
    ComponentPropsWithoutRef<"button">,
    "className" | "children"
  >;

export type ButtonProps = AsLink | AsAnchor | AsButton;

export default function Button(props: ButtonProps) {
  const { variant = "primary", className = "" } = props;
  const classes = buttonClass(variant, className);

  if (props.href !== undefined && props.external) {
    const { variant: _v, className: _c, external: _e, children, href, ...rest } = props;
    return (
      <a href={href} target="_blank" rel="noreferrer" className={classes} {...rest}>
        {children}
        <span aria-hidden>↗</span>
      </a>
    );
  }

  if (props.href !== undefined) {
    const { variant: _v, className: _c, external: _e, children, href, ...rest } = props;
    return (
      <Link href={href} className={classes} {...rest}>
        {children}
      </Link>
    );
  }

  const { variant: _v, className: _c, external: _e, children, type = "button", ...rest } = props;
  return (
    <button type={type} className={classes} {...rest}>
      {children}
    </button>
  );
}
