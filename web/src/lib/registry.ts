import generated from "@/generated/registry.json";

/**
 * The same companies.registry.yaml the Python pipeline reads, so the two
 * halves can never disagree about how a company is fetched. Parsed once per
 * server process.
 */
export type RegistryEntry = {
  name: string;
  domain?: string | null;
  method: string;
  careers_url?: string | null;
};

let cache: RegistryEntry[] | null = null;

export function registryEntries(): RegistryEntry[] {
  if (!cache) {
    cache = (generated as RegistryEntry[])
      .map((e) => ({ ...e, method: e.method ?? "pending" }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }
  return cache;
}

const normalise = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, "");

export function lookupRegistry(name: string): RegistryEntry | undefined {
  const n = normalise(name);
  return registryEntries().find((e) => normalise(e.name) === n);
}

/** Keyless favicon service; the UI falls back to Google, then a lettermark. */
export function logoFor(domain?: string | null): string | null {
  return domain ? `https://icons.duckduckgo.com/ip3/${domain}.ico` : null;
}

/** "greenhouse:databricks" -> "greenhouse"; "pending"/"auto" -> null. */
export function atsOf(method?: string | null): string | null {
  if (!method || method === "pending" || method === "auto") return null;
  return method.split(":")[0] || null;
}
