import { listCompanies } from "@/lib/db";
import { registryEntries, atsOf } from "@/lib/registry";
import { CompaniesView } from "@/components/CompaniesView";

export const dynamic = "force-dynamic";

export default async function CompaniesPage() {
  const companies = await listCompanies();
  const registry = registryEntries().map((e) => ({
    name: e.name,
    domain: e.domain ?? null,
    method: e.method,
    ats: atsOf(e.method),
  }));
  return <CompaniesView companies={companies} registry={registry} />;
}
