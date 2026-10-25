"use client";

import * as React from "react";
import clsx from "clsx";
import { Check, Plus, X } from "lucide-react";
import type { Filters } from "@/lib/db";
import { updateFilters } from "@/app/actions";
import { Button, Card, Field, Input } from "@/components/ui/primitives";

export function FiltersView({ initial }: { initial: Filters }) {
  const [draft, setDraft] = React.useState<Filters>(initial);
  const [saved, setSaved] = React.useState(false);
  const [busy, start] = React.useTransition();

  const dirty = JSON.stringify(draft) !== JSON.stringify(initial);

  function set<K extends keyof Filters>(key: K, value: Filters[K]) {
    setDraft((d) => ({ ...d, [key]: value }));
    setSaved(false);
  }

  function save() {
    start(async () => {
      await updateFilters(draft);
      setSaved(true);
    });
  }

  return (
    <div className="space-y-5 pb-20">
      <header>
        <h1 className="text-2xl font-bold sm:text-3xl">Filters</h1>
        <p className="mt-1 text-sm text-muted">
          Applied while scanning, so changes take effect on the next run.
        </p>
      </header>

      <Card className="space-y-5 p-4 sm:p-5">
        <TagField
          label="Role keywords"
          hint="Matched against the job title only. A title must contain one of these."
          values={draft.roles}
          onChange={(v) => set("roles", v)}
          placeholder="e.g. software engineer"
        />

        <TagField
          label="Exclude titles containing"
          hint="Drops a role outright — seniority words, and disciplines that aren't software."
          values={draft.exclude_terms}
          onChange={(v) => set("exclude_terms", v)}
          placeholder="e.g. senior"
          tone="danger"
        />

        <TagField
          label="Locations"
          hint="Matched against the posting's location."
          values={draft.locations}
          onChange={(v) => set("locations", v)}
          placeholder="e.g. bengaluru"
        />
      </Card>

      <Card className="space-y-5 p-4 sm:p-5">
        <div>
          <Field
            label={`Maximum experience: ${draft.max_experience_years} years`}
            hint="Read from the description. Postings that state no requirement are always kept."
          >
            <input
              type="range"
              min={1}
              max={15}
              value={draft.max_experience_years}
              onChange={(e) => set("max_experience_years", Number(e.target.value))}
              className="mt-1 w-full accent-accent"
            />
          </Field>
          <div className="mt-1 flex justify-between text-[11px] text-faint">
            <span>1 yr</span>
            <span>15 yrs</span>
          </div>
        </div>

        <CheckRow
          checked={draft.always_allow_remote}
          onChange={(v) => set("always_allow_remote", v)}
          label="Always allow remote roles"
          hint="Country-locked remote (e.g. “Remote, Canada”) is still excluded unless it lists one of your locations."
        />
      </Card>

      <div className="fixed inset-x-0 bottom-[68px] z-30 border-t border-line bg-surface/95 px-4 py-3 backdrop-blur md:static md:border-0 md:bg-transparent md:p-0 md:backdrop-blur-none">
        <div className="mx-auto flex max-w-6xl items-center gap-3">
          <Button variant="primary" onClick={save} disabled={!dirty || busy}>
            {busy ? "Saving…" : "Save filters"}
          </Button>
          {saved && !dirty ? (
            <span className="flex items-center gap-1 text-xs text-good">
              <Check size={13} /> Saved
            </span>
          ) : dirty ? (
            <span className="text-xs text-muted">Unsaved changes</span>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function TagField({
  label,
  hint,
  values,
  onChange,
  placeholder,
  tone = "accent",
}: {
  label: string;
  hint?: string;
  values: string[];
  onChange: (v: string[]) => void;
  placeholder?: string;
  tone?: "accent" | "danger";
}) {
  const [text, setText] = React.useState("");

  function add() {
    const v = text.trim().toLowerCase();
    if (!v || values.includes(v)) {
      setText("");
      return;
    }
    onChange([...values, v]);
    setText("");
  }

  return (
    <Field label={label} hint={hint}>
      <div className="flex gap-2">
        <Input
          value={text}
          placeholder={placeholder}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
        />
        <Button type="button" onClick={add} aria-label={`Add to ${label}`}>
          <Plus size={15} />
        </Button>
      </div>
      {values.length ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {values.map((v) => (
            <span
              key={v}
              className={clsx(
                "inline-flex items-center gap-1 rounded-full py-1 pr-1.5 pl-2.5 text-xs font-medium",
                tone === "danger"
                  ? "bg-danger-soft text-danger"
                  : "bg-accent-soft text-accent",
              )}
            >
              {v}
              <button
                type="button"
                aria-label={`Remove ${v}`}
                onClick={() => onChange(values.filter((x) => x !== v))}
                className="rounded-full p-0.5 hover:bg-black/5"
              >
                <X size={11} />
              </button>
            </span>
          ))}
        </div>
      ) : (
        <p className="mt-2 text-xs text-faint">None — this filter is off.</p>
      )}
    </Field>
  );
}

function CheckRow({
  checked,
  onChange,
  label,
  hint,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  hint?: string;
}) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="flex w-full items-start gap-2.5 text-left"
    >
      <span
        className={clsx(
          "mt-0.5 grid size-5 shrink-0 place-items-center rounded-md border transition-colors",
          checked ? "border-accent bg-accent text-white" : "border-line",
        )}
      >
        {checked ? <Check size={13} strokeWidth={3} /> : null}
      </span>
      <span>
        <span className="block text-[13px] font-medium">{label}</span>
        {hint ? <span className="mt-0.5 block text-xs text-muted">{hint}</span> : null}
      </span>
    </button>
  );
}
