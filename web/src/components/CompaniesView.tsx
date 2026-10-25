"use client";

import * as React from "react";
import clsx from "clsx";
import { CheckCircle2, CircleSlash, Plus, Trash2, TriangleAlert } from "lucide-react";
import type { Company } from "@/lib/db";
import { addCompanyByName, deleteCompany, toggleCompany } from "@/app/actions";
import { Button, Card, Chip, Logo } from "@/components/ui/primitives";
import { Combobox, type ComboItem } from "@/components/Combobox";
import { Toast } from "@/components/Toast";
import { useRouter } from "next/navigation";

export type RegistryItem = {
  name: string;
  domain?: string | null;
  method: string;
  ats: string | null;
};

export function CompaniesView({
  companies,
  registry,
}: {
  companies: Company[];
  registry: RegistryItem[];
}) {
  const [notice, setNotice] = React.useState<string | null>(null);
  // Name of the company just added, so its row can be scrolled to and
  // highlighted once the refreshed server data includes it.
  const [justAdded, setJustAdded] = React.useState<string | null>(null);
  const [busy, startTransition] = React.useTransition();
  const router = useRouter();
  const tracked = React.useMemo(
    () => new Set(companies.map((c) => c.name)),
    [companies],
  );

  const items: ComboItem[] = registry.map((e) => ({
    value: e.name,
    label: e.name,
    logo: e.domain ? `https://icons.duckduckgo.com/ip3/${e.domain}.ico` : null,
    meta: tracked.has(e.name)
      ? "already tracked"
      : (e.ats ?? (e.method === "auto" ? "page fetch" : "needs setup")),
    disabled: tracked.has(e.name),
  }));

  function add(name: string) {
    startTransition(async () => {
      const res = await addCompanyByName(name);
      setNotice(res.message);
      if (res.ok) {
        setJustAdded(res.name ?? name);
        // revalidatePath alone did not refresh the already-mounted client
        // component, so the counts and the new row stayed stale.
        router.refresh();
      }
    });
  }

  // Scroll to the new row once it exists in the refreshed data -- the list
  // it belongs to can sit well below the fold.
  const scrollToAdded = React.useCallback((name: string) => {
    const el = document.getElementById(`company-${name}`);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.classList.add("ring-2", "ring-accent");
    setTimeout(() => el.classList.remove("ring-2", "ring-accent"), 2200);
  }, []);

  React.useEffect(() => {
    if (justAdded && companies.some((c) => c.name === justAdded)) {
      scrollToAdded(justAdded);
    }
  }, [companies, justAdded, scrollToAdded]);

  const live = companies.filter((c) => c.method !== "pending");
  const upcoming = companies.filter((c) => c.method === "pending");

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-2xl font-bold sm:text-3xl">Companies</h1>
        <p className="mt-1 text-sm text-muted">
          {live.length} fetching · {upcoming.length} awaiting setup
        </p>
      </header>

      <Card className="space-y-3 p-3 sm:p-4">
        <Combobox
          items={items}
          onPick={(i) => add(i.value)}
          placeholder="Add a company — type a name…"
          emptyLabel="Not in the known list yet."
          onEmptyAction={(q) =>
            q ? (
              <Button size="sm" variant="primary" onClick={() => add(q)} disabled={busy}>
                <Plus size={13} /> Save &ldquo;{q}&rdquo; to upcoming
              </Button>
            ) : null
          }
        />

      </Card>

      {notice ? (
        <Toast
          message={notice}
          action={
            justAdded && companies.some((c) => c.name === justAdded)
              ? { label: "Show me", onClick: () => scrollToAdded(justAdded) }
              : undefined
          }
          onDismiss={() => setNotice(null)}
        />
      ) : null}

      <Section title="Fetching" count={live.length}>
        {live.map((c) => (
          <CompanyRow key={c.id} company={c} busy={busy} start={startTransition} />
        ))}
      </Section>

      {upcoming.length ? (
        <Section
          title="Upcoming"
          count={upcoming.length}
          hint="Saved, but no fetch method yet — skipped by the daily scan, never counted as broken."
        >
          {upcoming.map((c) => (
            <CompanyRow key={c.id} company={c} busy={busy} start={startTransition} />
          ))}
        </Section>
      ) : null}
    </div>
  );
}

function Section({
  title,
  count,
  hint,
  children,
}: {
  title: string;
  count: number;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <div className="mb-2 flex items-baseline gap-2">
        <h2 className="text-sm font-semibold">{title}</h2>
        <span className="text-xs text-faint">{count}</span>
      </div>
      {hint ? <p className="mb-2 text-xs text-muted">{hint}</p> : null}
      <ul className="space-y-2">{children}</ul>
    </section>
  );
}

function CompanyRow({
  company: c,
  busy,
  start,
}: {
  company: Company;
  busy: boolean;
  start: React.TransitionStartFunction;
}) {
  const [enabled, setEnabled] = React.useState(Boolean(c.enabled));
  const ats = c.method && !["pending", "auto"].includes(c.method)
    ? c.method.split(":")[0]
    : null;

  return (
    <li>
      <Card
        id={`company-${c.name}`}
        className="flex flex-wrap items-center gap-x-3 gap-y-2 p-3 transition-shadow"
      >
        <Logo src={c.logo_url} name={c.name} size={28} />

        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold">{c.name}</div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            {c.method === "pending" ? (
              <Chip tone="warn">
                <TriangleAlert size={10} /> needs setup
              </Chip>
            ) : c.last_status === "error" ? (
              <Chip tone="danger">failing</Chip>
            ) : c.last_status === "ok" ? (
              <Chip tone="good">
                <CheckCircle2 size={10} /> healthy
              </Chip>
            ) : (
              <Chip>never run</Chip>
            )}
            {ats ? <Chip tone="accent">{ats}</Chip> : null}
            {c.last_status === "ok" ? (
              <>
                <Chip tone={c.last_match_count ? "good" : "neutral"}>
                  {c.last_match_count ?? 0} matching
                </Chip>
                <span className="text-[11px] text-faint">
                  of {c.last_job_count ?? 0} scanned
                </span>
              </>
            ) : null}
          </div>
          {c.last_error ? (
            <p className="mt-1 truncate text-[11px] text-danger" title={c.last_error}>
              {c.last_error}
            </p>
          ) : null}
        </div>

        <div className="flex items-center gap-1.5">
          <button
            role="switch"
            aria-checked={enabled}
            aria-label={enabled ? `Pause ${c.name}` : `Resume ${c.name}`}
            disabled={busy}
            onClick={() => {
              const next = !enabled;
              setEnabled(next);
              start(() => void toggleCompany(c.id, next));
            }}
            className={clsx(
              "relative h-6 w-10 shrink-0 rounded-full transition-colors",
              enabled ? "bg-accent" : "bg-line",
            )}
          >
            <span
              className={clsx(
                "absolute top-0.5 size-5 rounded-full bg-white shadow transition-[left]",
                enabled ? "left-[18px]" : "left-0.5",
              )}
            />
          </button>

          <Button
            size="sm"
            variant="ghost"
            aria-label={`Remove ${c.name}`}
            disabled={busy}
            onClick={() => {
              if (confirm(`Stop tracking ${c.name}? Saved roles stay.`)) {
                start(() => void deleteCompany(c.id));
              }
            }}
          >
            <Trash2 size={14} />
          </Button>
        </div>
      </Card>
    </li>
  );
}

export { CircleSlash };
