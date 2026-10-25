"use client";

import * as React from "react";
import clsx from "clsx";
import { Monitor, Moon, Sun } from "lucide-react";

type Theme = "system" | "light" | "dark";

const OPTIONS: { value: Theme; label: string; icon: typeof Sun }[] = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
];

/** Applied to <html>; the CSS reads it. "system" removes the attribute so
 *  the prefers-color-scheme media query takes over again. */
function apply(theme: Theme) {
  const root = document.documentElement;
  if (theme === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", theme);
  localStorage.setItem("theme", theme);
}

export function ThemeToggle() {
  // Starts as null so the first render matches the server's HTML; the real
  // value is read from localStorage after mount, avoiding a hydration
  // mismatch on an attribute the server can't know.
  const [theme, setTheme] = React.useState<Theme | null>(null);

  React.useEffect(() => {
    const stored = localStorage.getItem("theme") as Theme | null;
    setTheme(stored ?? "system");
  }, []);

  function choose(next: Theme) {
    setTheme(next);
    apply(next);
  }

  return (
    <div
      role="radiogroup"
      aria-label="Colour theme"
      className="inline-flex gap-1 rounded-lg bg-canvas p-1"
    >
      {OPTIONS.map(({ value, label, icon: Icon }) => {
        const active = theme === value;
        return (
          <button
            key={value}
            role="radio"
            aria-checked={active}
            onClick={() => choose(value)}
            className={clsx(
              "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors",
              active
                ? "bg-surface text-ink shadow-sm"
                : "text-muted hover:text-ink",
            )}
          >
            <Icon size={13} />
            {label}
          </button>
        );
      })}
    </div>
  );
}

/**
 * Applies the saved theme before first paint. Rendered in <head> as a
 * blocking inline script: doing this in an effect would let the default
 * palette paint first and flash on every navigation.
 */
export function ThemeScript() {
  const js = `(function(){try{var t=localStorage.getItem('theme');
if(t==='dark'||t==='light')document.documentElement.setAttribute('data-theme',t);}catch(e){}})();`;
  return <script dangerouslySetInnerHTML={{ __html: js }} />;
}
