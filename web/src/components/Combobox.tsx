"use client";

import * as React from "react";
import clsx from "clsx";
import { Search, X } from "lucide-react";
import { Logo } from "@/components/ui/primitives";

export type ComboItem = {
  value: string;
  label: string;
  meta?: string;
  logo?: string | null;
  disabled?: boolean;
};

/**
 * Type-ahead with a logo and a line of metadata per result — the shape a
 * company picker needs. Filtering happens in the browser on every
 * keystroke, so results appear as you type with no round-trip.
 */
export function Combobox({
  items,
  onPick,
  placeholder = "Search…",
  emptyLabel = "No match",
  onEmptyAction,
  autoFocus,
}: {
  items: ComboItem[];
  onPick: (item: ComboItem) => void;
  placeholder?: string;
  emptyLabel?: string;
  onEmptyAction?: (query: string) => React.ReactNode;
  autoFocus?: boolean;
}) {
  const [query, setQuery] = React.useState("");
  const [open, setOpen] = React.useState(false);
  const [active, setActive] = React.useState(0);
  const boxRef = React.useRef<HTMLDivElement>(null);

  const results = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    return items
      .filter((i) => i.label.toLowerCase().includes(q))
      // Prefix matches first: typing "goo" should surface Google above
      // anything that merely contains those letters mid-word.
      .sort((a, b) => {
        const ap = a.label.toLowerCase().startsWith(q) ? 0 : 1;
        const bp = b.label.toLowerCase().startsWith(q) ? 0 : 1;
        return ap - bp || a.label.localeCompare(b.label);
      })
      .slice(0, 8);
  }, [items, query]);

  React.useEffect(() => setActive(0), [query]);

  React.useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (!boxRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  function pick(item: ComboItem) {
    if (item.disabled) return;
    onPick(item);
    setQuery("");
    setOpen(false);
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (!open || !results.length) return;
    if (e.key === "ArrowDown") {
      setActive((a) => Math.min(a + 1, results.length - 1));
      e.preventDefault();
    } else if (e.key === "ArrowUp") {
      setActive((a) => Math.max(a - 1, 0));
      e.preventDefault();
    } else if (e.key === "Enter") {
      pick(results[active]);
      e.preventDefault();
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  const showPanel = open && query.trim().length > 0;

  return (
    <div ref={boxRef} className="relative">
      <div className="flex h-11 items-center gap-2 rounded-xl border border-line bg-surface px-3 focus-within:border-accent">
        <Search size={15} className="shrink-0 text-faint" />
        <input
          value={query}
          autoFocus={autoFocus}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          placeholder={placeholder}
          aria-label={placeholder}
          autoComplete="off"
          role="combobox"
          aria-expanded={showPanel}
          className="min-w-0 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-faint"
        />
        {query ? (
          <button
            type="button"
            onClick={() => setQuery("")}
            aria-label="Clear search"
            className="text-faint hover:text-ink"
          >
            <X size={15} />
          </button>
        ) : null}
      </div>

      {showPanel ? (
        <div
          role="listbox"
          className="absolute inset-x-0 top-[calc(100%+6px)] z-50 overflow-hidden rounded-xl border border-line bg-surface shadow-lg"
        >
          {results.length ? (
            results.map((item, i) => (
              <button
                key={item.value}
                role="option"
                aria-selected={i === active}
                disabled={item.disabled}
                onMouseEnter={() => setActive(i)}
                onMouseDown={(e) => {
                  e.preventDefault();
                  pick(item);
                }}
                className={clsx(
                  "flex w-full items-center gap-2.5 px-3 py-2 text-left",
                  i === active && "bg-canvas",
                  item.disabled && "opacity-50",
                )}
              >
                <Logo src={item.logo} name={item.label} size={22} />
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium">
                    {item.label}
                  </span>
                  {item.meta ? (
                    <span className="block truncate text-xs text-muted">
                      {item.meta}
                    </span>
                  ) : null}
                </span>
              </button>
            ))
          ) : (
            <div className="px-3 py-2.5 text-sm text-muted">
              {emptyLabel}
              {onEmptyAction ? (
                <div className="mt-2">{onEmptyAction(query.trim())}</div>
              ) : null}
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}
