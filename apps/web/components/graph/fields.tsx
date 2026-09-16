import type { ComponentPropsWithoutRef, ReactNode } from "react";

/** Form pieces shared by the WebGraph panels: the same rule, radius and focus ring as the URL prompt. */

export const INPUT =
  "h-9 w-full min-w-0 rounded-md border border-rule bg-surface px-3 text-small text-ink outline-none " +
  "transition-[border-color,box-shadow] duration-(--dur-fast) ease-(--ease) placeholder:text-faint " +
  "focus:border-rule-strong focus:ring-2 focus:ring-focus/30 disabled:opacity-45 pointer-coarse:min-h-11";

export function Field({
  label,
  hint,
  children,
  className = "",
}: {
  label: string;
  hint?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <label className={`flex flex-col gap-1.5 ${className}`}>
      <span className="text-label font-bold uppercase text-muted">{label}</span>
      {children}
      {hint && <span className="text-caption text-muted">{hint}</span>}
    </label>
  );
}

export function TextInput(props: ComponentPropsWithoutRef<"input">) {
  const { className = "", ...rest } = props;
  return <input {...rest} className={`${INPUT} ${className}`} />;
}

export function Select(props: ComponentPropsWithoutRef<"select">) {
  const { className = "", children, ...rest } = props;
  return (
    <select {...rest} className={`${INPUT} appearance-auto pr-8 ${className}`}>
      {children}
    </select>
  );
}

export function Panel({
  title,
  lede,
  aside,
  children,
  className = "",
}: {
  title: string;
  lede?: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`border-t border-rule pt-5 ${className}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 className="text-h3 font-bold text-ink">{title}</h2>
        {aside}
      </div>
      {lede && <p className="mt-1 max-w-prose text-caption text-muted">{lede}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

export function Note({ tone = "plain", children }: { tone?: "plain" | "bad" | "warn" | "good"; children: ReactNode }) {
  const color = { plain: "text-muted", bad: "text-bad", warn: "text-warn", good: "text-good" }[tone];
  return (
    <p role={tone === "bad" ? "alert" : undefined} className={`text-caption font-medium ${color}`}>
      {children}
    </p>
  );
}
