import { createClient, type Client } from "@libsql/client";

/**
 * Same Turso database the Python pipeline writes to. The cron run is the
 * only writer for jobs and companies' fetch status; this app writes the
 * things a person changes — filters, done flags, the company watchlist.
 */
let client: Client | null = null;

export function db(): Client {
  if (!client) {
    const url = process.env.TURSO_DATABASE_URL;
    const authToken = process.env.TURSO_AUTH_TOKEN;
    if (!url) throw new Error("TURSO_DATABASE_URL is not set");
    client = createClient({ url, authToken });
  }
  return client;
}

/**
 * libSQL returns Row objects with non-enumerable helpers attached, which
 * React refuses to pass from a Server Component to a Client Component
 * ("Only plain objects can be passed"). Copy each row into a plain object.
 */
function plain<T>(rows: unknown[]): T[] {
  return rows.map((r) => ({ ...(r as Record<string, unknown>) })) as T[];
}

export type Company = {
  id: number;
  name: string;
  url: string | null;
  enabled: number;
  ats_type: string | null;
  last_checked_at: string | null;
  last_status: string | null;
  last_error: string | null;
  last_job_count: number | null;
  last_match_count: number | null;
  logo_url: string | null;
  method: string | null;
};

export type Job = {
  id: string;
  company_id: number;
  company_name: string;
  title: string;
  location: string | null;
  url: string;
  description: string | null;
  first_seen_at: string;
  notified_at: string | null;
  closed_at: string | null;
  done_at: string | null;
  /** When the company published the role, where the source reports it. */
  posted_at: string | null;
  /** Dismissed by the user -- distinct from closed_at, which means the
   *  company removed the listing. */
  dismissed_at: string | null;
};

export type Filters = {
  roles: string[];
  experience_terms: string[];
  exclude_terms: string[];
  locations: string[];
  always_allow_remote: boolean;
  max_experience_years: number;
};

const DEFAULT_FILTERS: Filters = {
  roles: [],
  experience_terms: [],
  exclude_terms: [],
  locations: [],
  always_allow_remote: true,
  max_experience_years: 5,
};

export async function listCompanies(): Promise<Company[]> {
  const res = await db().execute("SELECT * FROM companies ORDER BY name");
  return plain<Company>(res.rows);
}

/** Open jobs: still listed by the company and not ticked off. */
export async function listJobs(): Promise<Job[]> {
  const res = await db().execute(
    `SELECT id, company_id, company_name, title, location, url, description,
            first_seen_at, notified_at, closed_at, done_at,
            posted_at, dismissed_at
     FROM jobs ORDER BY first_seen_at DESC LIMIT 1000`,
  );
  return plain<Job>(res.rows);
}

export async function getFilters(): Promise<Filters> {
  const res = await db().execute(
    "SELECT value FROM settings WHERE key = 'filters'",
  );
  if (!res.rows.length) return DEFAULT_FILTERS;
  try {
    const raw = JSON.parse(String(res.rows[0].value));
    return { ...DEFAULT_FILTERS, ...raw };
  } catch {
    return DEFAULT_FILTERS;
  }
}

export async function saveFilters(filters: Filters): Promise<void> {
  await db().execute({
    sql: `INSERT INTO settings (key, value) VALUES ('filters', ?)
          ON CONFLICT(key) DO UPDATE SET value = excluded.value`,
    args: [JSON.stringify(filters)],
  });
}

export async function setJobDone(id: string, done: boolean): Promise<void> {
  await db().execute({
    sql: "UPDATE jobs SET done_at = ? WHERE id = ?",
    args: [done ? new Date().toISOString().slice(0, 19).replace("T", " ") : null, id],
  });
}

export async function setCompanyEnabled(id: number, enabled: boolean) {
  await db().execute({
    sql: "UPDATE companies SET enabled = ? WHERE id = ?",
    args: [enabled ? 1 : 0, id],
  });
}

export async function addCompany(
  name: string,
  opts: { url?: string; method?: string; logo?: string } = {},
): Promise<void> {
  await db().execute({
    sql: `INSERT INTO companies (name, url, logo_url, method)
          VALUES (?, ?, ?, ?) ON CONFLICT(name) DO NOTHING`,
    args: [name, opts.url ?? "", opts.logo ?? null, opts.method ?? "pending"],
  });
}

export async function removeCompany(id: number): Promise<void> {
  await db().execute({ sql: "DELETE FROM companies WHERE id = ?", args: [id] });
}

export type Run = {
  id: number;
  started_at: string;
  finished_at: string | null;
  duration_seconds: number | null;
  companies_checked: number | null;
  companies_ok: number | null;
  new_jobs_count: number | null;
  triggered_by: string | null;
};

export async function listRuns(limit = 10): Promise<Run[]> {
  const res = await db().execute({
    sql: `SELECT id, started_at, finished_at, duration_seconds, companies_checked,
                 companies_ok, new_jobs_count, triggered_by
          FROM runs ORDER BY id DESC LIMIT ?`,
    args: [limit],
  });
  return plain<Run>(res.rows);
}
