"use server";

import { revalidatePath } from "next/cache";
import {
  addCompany,
  removeCompany,
  saveFilters,
  setCompanyEnabled,
  setJobDone,
  type Filters,
} from "@/lib/db";
import { lookupRegistry, logoFor } from "@/lib/registry";

export async function toggleJobDone(id: string, done: boolean) {
  await setJobDone(id, done);
  revalidatePath("/");
}

export async function toggleCompany(id: number, enabled: boolean) {
  await setCompanyEnabled(id, enabled);
  revalidatePath("/companies");
}

export async function deleteCompany(id: number) {
  await removeCompany(id);
  revalidatePath("/companies");
}

/**
 * Adding takes a name and nothing else. A name the registry knows arrives
 * fully configured; anything else is stored as `pending` — skipped by the
 * pipeline and never counted as broken — so adding can never fail.
 */
export async function addCompanyByName(name: string) {
  const trimmed = name.trim();
  if (!trimmed) return { ok: false, name: null, message: "Enter a company name." };

  const entry = lookupRegistry(trimmed);
  const canonical = entry?.name ?? trimmed;

  await addCompany(canonical, {
    url: entry?.careers_url ?? "",
    method: entry?.method ?? "pending",
    logo: (entry ? logoFor(entry.domain) : null) ?? undefined,
  });
  revalidatePath("/companies");

  return {
    ok: true,
    // The canonical name, so the caller can locate the row it just created:
    // the registry decides spelling, e.g. "amazon" is stored as "Amazon".
    name: canonical,
    message: entry
      ? `Added ${canonical}.`
      : `Saved ${canonical} to the upcoming list — it won't be scanned until a fetch method is added.`,
  };
}

export async function updateFilters(filters: Filters) {
  await saveFilters(filters);
  revalidatePath("/filters");
  revalidatePath("/");
}
