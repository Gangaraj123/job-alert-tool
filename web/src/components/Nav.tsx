"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Briefcase, Building2, SlidersHorizontal } from "lucide-react";
import clsx from "clsx";

/**
 * Desktop gets a quiet left rail; phones get a bottom tab bar rather than a
 * collapsing drawer. A drawer costs a tap and can be shut with no obvious
 * way back — which is exactly how the previous UI stranded people.
 */
const LINKS = [
  { href: "/", label: "Jobs", icon: Briefcase },
  { href: "/companies", label: "Companies", icon: Building2 },
  { href: "/filters", label: "Filters", icon: SlidersHorizontal },
];

export function Nav() {
  const path = usePathname();
  const isActive = (href: string) =>
    href === "/" ? path === "/" : path.startsWith(href);

  return (
    <>
      <aside className="sticky top-0 hidden h-dvh w-56 shrink-0 border-r border-line px-3 py-7 md:block">
        <div className="mb-7 px-2">
          <div className="font-display text-[17px] font-bold tracking-tight">
            Job Alerts
          </div>
          <div className="text-xs text-muted">SDE-II · Bangalore &amp; remote</div>
        </div>
        <nav className="space-y-0.5">
          {LINKS.map(({ href, label, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              aria-current={isActive(href) ? "page" : undefined}
              className={clsx(
                "flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-colors",
                isActive(href)
                  ? "bg-accent-soft font-medium text-accent"
                  : "text-muted hover:bg-surface hover:text-ink",
              )}
            >
              <Icon size={16} strokeWidth={2} />
              {label}
            </Link>
          ))}
        </nav>
      </aside>

      <nav className="fixed inset-x-0 bottom-0 z-40 flex border-t border-line bg-surface/95 backdrop-blur md:hidden">
        {LINKS.map(({ href, label, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            aria-current={isActive(href) ? "page" : undefined}
            className={clsx(
              "flex flex-1 flex-col items-center gap-1 py-2.5 pb-[calc(0.625rem+env(safe-area-inset-bottom))] text-[11px]",
              isActive(href) ? "text-accent" : "text-muted",
            )}
          >
            <Icon size={19} strokeWidth={isActive(href) ? 2.4 : 1.9} />
            {label}
          </Link>
        ))}
      </nav>
    </>
  );
}
