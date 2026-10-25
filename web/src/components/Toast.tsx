"use client";

import * as React from "react";
import clsx from "clsx";
import { Check, X } from "lucide-react";

export type ToastAction = { label: string; onClick: () => void };

/**
 * A confirmation that stays put long enough to read, with an optional way
 * to act on it. The add flow previously wrote a line of grey caption text
 * under the search box and left the new row 28 entries further down the
 * page, so a successful add was indistinguishable from nothing happening.
 */
export function Toast({
  message,
  action,
  onDismiss,
}: {
  message: string;
  action?: ToastAction;
  onDismiss: () => void;
}) {
  React.useEffect(() => {
    // Long enough to read a sentence and reach the action; auto-dismiss so
    // it never needs managing.
    const t = setTimeout(onDismiss, 6000);
    return () => clearTimeout(t);
  }, [onDismiss, message]);

  return (
    <div
      role="status"
      aria-live="polite"
      className={clsx(
        "fixed inset-x-3 z-50 mx-auto max-w-md sm:inset-x-auto sm:right-6 sm:mx-0",
        // Clear of the mobile tab bar, which is fixed to the bottom.
        "bottom-24 md:bottom-6",
      )}
    >
      <div className="flex items-center gap-3 rounded-xl border border-line bg-surface px-3.5 py-3 shadow-lg">
        <span className="grid size-5 shrink-0 place-items-center rounded-full bg-good-soft text-good">
          <Check size={13} strokeWidth={3} />
        </span>
        <p className="min-w-0 flex-1 text-[13px] leading-snug">{message}</p>
        {action ? (
          <button
            onClick={() => {
              action.onClick();
              onDismiss();
            }}
            className="shrink-0 rounded-md px-2 py-1 text-[13px] font-semibold text-accent hover:bg-accent-soft"
          >
            {action.label}
          </button>
        ) : null}
        <button
          onClick={onDismiss}
          aria-label="Dismiss"
          className="shrink-0 text-faint hover:text-ink"
        >
          <X size={14} />
        </button>
      </div>
    </div>
  );
}
