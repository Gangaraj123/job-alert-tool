"use client";

import * as React from "react";
import clsx from "clsx";
import { Check, ExternalLink, Filter, X } from "lucide-react";
import type { Company, Job } from "@/lib/db";
import { toggleJobDone } from "@/app/actions";
import { Button, Card, Chip, Logo } from "@/components/ui/primitives";
import { Combobox, type ComboItem } from "@/components/Combobox";

const WINDOWS = [
  { key: "any", label: "Any time", days: null },
  { key: "1", label: "Today", days: 0 },
  { key: "3", label: "3 days", days: 2 },
  { key: "7", label: "7 days", days: 6 },
  { key: "30", label: "30 days", days: 29 },
] as const;

/** IST calendar day, so "Today" means today where the user is. */
function istDate(value: string): string {
  const d = new Date(value.replace(" ", "T") + (value.endsWith("Z") ? "" : "Z"));
  return new Date(d.getTime() + 5.5 * 3600 * 1000).toISOString().slice(0, 10);
}

function relative(value: string): string {
  const then = new Date(value.replace(" ", "T") + (value.endsWith("Z") ? "" : "Z"));
  const mins = Math.max(0, (Date.now() - then.getTime()) / 60000);
  if (mins < 60) return `${Math.round(mins)}m ago`;
  if (mins < 60 * 24) return `${Math.round(mins / 60)}h ago`;
  const days = Math.round(mins / (60 * 24));
  return days === 1 ? "yesterday" : `${days}d ago`;
}

export function JobsView({
  jobs,
  companies,
}: {
  jobs: Job[];
  companies: Company[];
}) {
  const [picked, setPicked] = React.useState<string[]>([]);
  const [windowKey, setWindowKey] = React.useState<string>("any");
  const [hideClosed, setHideClosed] = React.useState(true);
  const [hideDone, setHideDone] = React.useState(false);
  const [text, setText] = React.useState("");
  const [pending, startTransition] = React.useTransition();
  const [doneOverride, setDoneOverride] = React.useState<Record<string, boolean>>({});

  const logoOf = React.useMemo(() => {
    const map = new Map(companies.map((c) => [c.name, c.logo_url]));
    return (name: string) => map.get(name) ?? null;
  }, [companies]);

  const counts = React.useMemo(() => {
    const m = new Map<string, number>();
    for (const j of jobs) {
      if (j.closed_at) continue;
      m.set(j.company_name, (m.get(j.company_name) ?? 0) + 1);
    }
    return m;
  }, [jobs]);

  const comboItems: ComboItem[] = React.useMemo(
    () =>
      companies.map((c) => {
        const n = counts.get(c.name) ?? 0;
        return {
          value: c.name,
          label: c.name,
          meta:
            c.method === "pending"
              ? "needs setup"
              : `${n} open role${n === 1 ? "" : "s"}`,
          logo: c.logo_url,
          disabled: picked.includes(c.name),
        };
      }),
    [companies, counts, picked],
  );

  const visible = React.useMemo(() => {
    const days = WINDOWS.find((w) => w.key === windowKey)?.days ?? null;
    const cutoff =
      days === null
        ? null
        : new Date(Date.now() + 5.5 * 3600 * 1000 - days * 86400000)
            .toISOString()
            .slice(0, 10);
    const q = text.trim().toLowerCase();

    return jobs.filter((j) => {
      const done = doneOverride[j.id] ?? Boolean(j.done_at);
      if (picked.length && !picked.includes(j.company_name)) return false;
      if (hideClosed && j.closed_at) return false;
      if (hideDone && done) return false;
      if (cutoff && istDate(j.first_seen_at) < cutoff) return false;
      if (q && !`${j.title} ${j.company_name} ${j.location ?? ""}`.toLowerCase().includes(q))
        return false;
      return true;
    });
  }, [jobs, picked, windowKey, hideClosed, hideDone, text, doneOverride]);

  function markDone(job: Job, done: boolean) {
    // Flip locally first so the checkbox responds instantly; the server
    // action reconciles and the row settles on the real value.
    setDoneOverride((d) => ({ ...d, [job.id]: done }));
    startTransition(() => void toggleJobDone(job.id, done));
  }

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold sm:text-3xl">Jobs</h1>
          <p className="mt-1 text-sm text-muted">
            {visible.length} of {jobs.length} roles across {companies.length} companies
          </p>
        </div>
      </header>

      <Card className="space-y-3 p-3 sm:p-4">
        <Combobox
          items={comboItems}
          onPick={(i) => setPicked((p) => [...p, i.value])}
          placeholder="Filter by company…"
          emptyLabel="No tracked company matches that."
        />

        {picked.length ? (
          <div className="flex flex-wrap gap-1.5">
            {picked.map((name) => (
              <button
                key={name}
                onClick={() => setPicked((p) => p.filter((x) => x !== name))}
                className="inline-flex items-center gap-1.5 rounded-full bg-accent-soft py-1 pr-2 pl-1.5 text-xs font-medium text-accent"
              >
                <Logo src={logoOf(name)} name={name} size={16} />
                {name}
                <X size={12} />
              </button>
            ))}
            <button
              onClick={() => setPicked([])}
              className="rounded-full px-2 py-1 text-xs text-muted hover:text-ink"
            >
              Clear all
            </button>
          </div>
        ) : null}

        <div className="flex flex-wrap items-center gap-2">
          <div className="scroll-x flex gap-1 rounded-lg bg-canvas p-1">
            {WINDOWS.map((w) => (
              <button
                key={w.key}
                onClick={() => setWindowKey(w.key)}
                className={clsx(
                  "rounded-md px-2.5 py-1.5 text-xs font-medium whitespace-nowrap transition-colors",
                  windowKey === w.key
                    ? "bg-surface text-ink shadow-sm"
                    : "text-muted hover:text-ink",
                )}
              >
                {w.label}
              </button>
            ))}
          </div>

          <Toggle checked={hideClosed} onChange={setHideClosed} label="Hide closed" />
          <Toggle checked={hideDone} onChange={setHideDone} label="Hide done" />

          <div className="ms-auto flex h-9 min-w-[150px] flex-1 items-center gap-2 rounded-lg border border-line bg-surface px-2.5 sm:flex-none">
            <Filter size={13} className="shrink-0 text-faint" />
            <input
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Search titles…"
              aria-label="Search titles"
              className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-faint"
            />
          </div>
        </div>
      </Card>

      {visible.length === 0 ? (
        <Card className="p-8 text-center">
          <p className="text-sm font-medium">No roles match these filters.</p>
          <p className="mt-1 text-sm text-muted">
            Try a wider date range, or clear the company filter.
          </p>
        </Card>
      ) : (
        <ul className="space-y-2">
          {visible.map((job) => {
            const done = doneOverride[job.id] ?? Boolean(job.done_at);
            return (
              <li key={job.id}>
                <Card
                  className={clsx(
                    "flex items-start gap-3 p-3 transition-opacity sm:p-4",
                    done && "opacity-60",
                  )}
                >
                  <button
                    role="checkbox"
                    aria-checked={done}
                    aria-label={done ? "Mark as not done" : "Mark as done"}
                    onClick={() => markDone(job, !done)}
                    disabled={pending}
                    className={clsx(
                      "mt-0.5 grid size-5 shrink-0 place-items-center rounded-md border transition-colors",
                      done
                        ? "border-accent bg-accent text-white"
                        : "border-line hover:border-accent",
                    )}
                  >
                    {done ? <Check size={13} strokeWidth={3} /> : null}
                  </button>

                  <div className="min-w-0 flex-1">
                    <div className="flex items-start gap-2">
                      <Logo src={logoOf(job.company_name)} name={job.company_name} size={20} />
                      <h2
                        className={clsx(
                          "text-[15px] leading-snug font-semibold",
                          done && "line-through",
                        )}
                      >
                        {job.title}
                      </h2>
                    </div>
                    <p className="mt-1 text-[13px] text-muted">
                      <span className="font-medium text-ink">{job.company_name}</span>
                      {job.location ? ` · ${job.location}` : ""}
                    </p>
                    <div className="mt-2 flex flex-wrap items-center gap-1.5">
                      {job.closed_at ? (
                        <Chip tone="warn">Closed</Chip>
                      ) : (
                        <Chip tone="good">Open</Chip>
                      )}
                      {done ? <Chip tone="accent">Done</Chip> : null}
                      <span className="text-[11px] text-faint">
                        found {relative(job.first_seen_at)}
                      </span>
                    </div>
                  </div>

                  <a
                    href={job.url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="shrink-0"
                  >
                    <Button size="sm" variant="secondary" className="gap-1">
                      Open <ExternalLink size={13} />
                    </Button>
                  </a>
                </Card>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={clsx(
        "inline-flex h-9 items-center gap-1.5 rounded-lg border px-2.5 text-xs font-medium transition-colors",
        checked
          ? "border-accent bg-accent-soft text-accent"
          : "border-line bg-surface text-muted hover:text-ink",
      )}
    >
      <span
        className={clsx(
          "grid size-3.5 place-items-center rounded-[4px] border",
          checked ? "border-accent bg-accent text-white" : "border-line",
        )}
      >
        {checked ? <Check size={10} strokeWidth={3.5} /> : null}
      </span>
      {label}
    </button>
  );
}
