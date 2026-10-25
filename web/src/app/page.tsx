import { listCompanies, listJobs } from "@/lib/db";
import { JobsView } from "@/components/JobsView";

// Always read live: the cron writes new roles while this page is cached.
export const dynamic = "force-dynamic";

export default async function JobsPage() {
  const [jobs, companies] = await Promise.all([listJobs(), listCompanies()]);
  return <JobsView jobs={jobs} companies={companies} />;
}
