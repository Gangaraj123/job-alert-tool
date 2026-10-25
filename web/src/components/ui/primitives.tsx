"use client";

import * as React from "react";
import clsx from "clsx";

/** Small status pill. Status is carried by a mark, not a coloured panel. */
export function Chip({
  tone = "neutral",
  children,
  className,
}: {
  tone?: "neutral" | "good" | "warn" | "danger" | "accent";
  children: React.ReactNode;
  className?: string;
}) {
  const tones = {
    neutral: "bg-line/60 text-muted",
    good: "bg-good-soft text-good",
    warn: "bg-warn-soft text-warn",
    danger: "bg-danger-soft text-danger",
    accent: "bg-accent-soft text-accent",
  } as const;
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium whitespace-nowrap",
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function Button({
  variant = "secondary",
  size = "md",
  className,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md";
}) {
  const variants = {
    primary: "bg-accent text-white hover:opacity-90",
    secondary: "bg-surface border border-line text-ink hover:bg-canvas",
    ghost: "text-muted hover:text-ink hover:bg-canvas",
    danger: "bg-danger-soft text-danger hover:brightness-95",
  } as const;
  return (
    <button
      className={clsx(
        "inline-flex items-center justify-center gap-1.5 rounded-lg font-medium",
        "transition-[background,opacity,color] disabled:opacity-45 disabled:cursor-not-allowed",
        size === "sm" ? "h-8 px-2.5 text-[13px]" : "h-10 px-3.5 text-sm",
        variants[variant],
        className,
      )}
      {...props}
    />
  );
}

export function Card({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={clsx(
        "rounded-xl border border-line bg-surface",
        className,
      )}
      {...props}
    />
  );
}

/**
 * Company logo with a two-service fallback: neither free icon provider
 * covers every company, and a missing icon should leave a lettermark
 * rather than a broken-image glyph.
 */
export function Logo({
  src,
  name,
  size = 24,
}: {
  src?: string | null;
  name: string;
  size?: number;
}) {
  const [stage, setStage] = React.useState(0);
  const domainFromDdg = src?.match(/ip3\/(.+)\.ico$/)?.[1];
  const google = domainFromDdg
    ? `https://www.google.com/s2/favicons?domain=${domainFromDdg}&sz=128`
    : null;
  const current = stage === 0 ? src : stage === 1 ? google : null;

  if (!current) {
    return (
      <span
        aria-hidden
        className="grid shrink-0 place-items-center rounded-md border border-line bg-canvas font-semibold text-faint"
        style={{ width: size, height: size, fontSize: size * 0.45 }}
      >
        {name.slice(0, 1).toUpperCase()}
      </span>
    );
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={current}
      alt=""
      width={size}
      height={size}
      onError={() => setStage((s) => s + 1)}
      className="shrink-0 rounded-md border border-line bg-white object-contain p-[1px]"
      style={{ width: size, height: size }}
    />
  );
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[13px] font-medium text-ink">{label}</span>
      {children}
      {hint ? <span className="mt-1 block text-xs text-muted">{hint}</span> : null}
    </label>
  );
}

export function Input({
  className,
  ...props
}: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={clsx(
        "h-10 w-full rounded-lg border border-line bg-surface px-3 text-sm text-ink",
        "placeholder:text-faint focus:border-accent focus:outline-none",
        className,
      )}
      {...props}
    />
  );
}
