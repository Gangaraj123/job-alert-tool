import { listRuns, listCompanies, listJobs } from "@/lib/db";
import { ActivityView } from "@/components/ActivityView";

export const dynamic = "force-dynamic";

export default async function ActivityPage() {
  const [runs, companies, jobs] = await Promise.all([
    listRuns(30),
    listCompanies(),
    listJobs(),
  ]);
  return <ActivityView runs={runs} companies={companies} jobs={jobs} />;
}
