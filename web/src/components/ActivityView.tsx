"use client";

import * as React from "react";
import clsx from "clsx";
import { AlertTriangle, CheckCircle2 } from "lucide-react";
import type { Company, Job, Run } from "@/lib/db";
import { Card, Chip } from "@/components/ui/primitives";
import { ThemeToggle } from "@/components/ThemeToggle";

/** The scheduled run is daily; past this, something has stopped running. */
const STALE_AFTER_HOURS = 30;

function parseUtc(value: string): Date {
  return new Date(value.replace(" ", "T") + (value.endsWith("Z") ? "" : "Z"));
}

function hoursSince(value: string): number {
  return (Date.now() - parseUtc(value).getTime()) / 3_600_000;
}

function ist(value: string): string {
  return parseUtc(value).toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function ActivityView({
  runs,
  companies,
  jobs,
}: {
  runs: Run[];
  companies: Company[];
  jobs: Job[];
}) {
  // Only runs that finished count as evidence the pipeline is alive; a row
  // with no finished_at is a crashed or interrupted run.
  const lastComplete = runs.find((r) => r.finished_at);
  const staleHours = lastComplete ? hoursSince(lastComplete.started_at) : null;
  const stale = staleHours === null || staleHours > STALE_AFTER_HOURS;

  const openJobs = jobs.filter(
    (j) => !j.closed_at && !j.done_at && !j.dismissed_at,
  ).length;
  const fetching = companies.filter((c) => c.method !== "pending").length;

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-2xl font-bold sm:text-3xl">Activity</h1>
        <p className="mt-1 text-sm text-muted">
          Every scan, and what each one found.
        </p>
      </header>

      {/* The one thing worth alarming on: nothing ran. A stopped scheduler
          can't report itself, so absence is the only available signal. */}
      <Card
        className={clsx(
          "flex items-start gap-3 p-4",
          stale && "border-warn/40 bg-warn-soft",
        )}
      >
        {stale ? (
          <AlertTriangle size={18} className="mt-0.5 shrink-0 text-warn" />
        ) : (
          <CheckCircle2 size={18} className="mt-0.5 shrink-0 text-good" />
        )}
        <div className="min-w-0">
          <p className="text-sm font-semibold">
            {stale ? "No recent scan" : "Scans are running"}
          </p>
          <p className="mt-0.5 text-sm text-muted">
            {lastComplete ? (
              <>
                Last completed {ist(lastComplete.started_at)} IST
                {staleHours !== null && ` — ${Math.round(staleHours)}h ago`}.
                {stale &&
                  " The daily scan should run every 24 hours; check that the GitHub Actions workflow is still enabled."}
              </>
            ) : (
              "No completed scan on record yet."
            )}
          </p>
        </div>
      </Card>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Open roles" value={openJobs} />
        <Stat label="Tracked" value={companies.length} />
        <Stat label="Fetching" value={fetching} />
        <Stat label="Scans kept" value={runs.length} />
      </div>

      <div>
        <h2 className="mb-2 text-sm font-semibold">Scan history</h2>
        {runs.length === 0 ? (
          <Card className="p-6 text-center text-sm text-muted">
            No scans recorded yet.
          </Card>
        ) : (
          <Card className="divide-y divide-line overflow-hidden">
            {runs.map((run) => {
              const incomplete = !run.finished_at;
              const checked = run.companies_checked ?? 0;
              const ok = run.companies_ok ?? 0;
              const broken = checked - ok;
              return (
                <div
                  key={run.id}
                  className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3 py-2.5 sm:px-4"
                >
                  <span className="w-[8.5rem] shrink-0 text-[13px] text-muted">
                    {ist(run.started_at)}
                  </span>

                  {incomplete ? (
                    <Chip tone="warn">did not finish</Chip>
                  ) : broken > 0 ? (
                    <Chip tone="danger">{broken} failed</Chip>
                  ) : (
                    <Chip tone="good">{ok}/{checked} ok</Chip>
                  )}

                  <span className="text-[13px]">
                    <strong className="font-semibold">
                      {run.new_jobs_count ?? 0}
                    </strong>{" "}
                    <span className="text-muted">new</span>
                  </span>

                  <span className="ms-auto text-[11px] text-faint">
                    {run.duration_seconds
                      ? `${Math.round(run.duration_seconds)}s`
                      : "—"}
                    {run.triggered_by ? ` · ${run.triggered_by}` : ""}
                  </span>
                </div>
              );
            })}
          </Card>
        )}
      </div>

      <div>
        <h2 className="mb-2 text-sm font-semibold">Appearance</h2>
        <Card className="flex flex-wrap items-center justify-between gap-3 p-4">
          <p className="text-sm text-muted">
            Choose a theme, or follow your device.
          </p>
          <ThemeToggle />
        </Card>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <Card className="p-3">
      <div className="font-display text-2xl font-bold">{value}</div>
      <div className="mt-0.5 text-xs text-muted">{label}</div>
    </Card>
  );
}
