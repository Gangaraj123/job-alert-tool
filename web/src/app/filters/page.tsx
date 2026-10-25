import { getFilters } from "@/lib/db";
import { FiltersView } from "@/components/FiltersView";

export const dynamic = "force-dynamic";

export default async function FiltersPage() {
  const filters = await getFilters();
  return <FiltersView initial={filters} />;
}
