/**
 * Copies the shared company registry into the app as JSON at build time.
 *
 * companies.registry.yaml lives at the repo root because the Python
 * pipeline reads it too, and it must stay the single source of truth.
 * Reading it from here at runtime via fs does not survive deployment:
 * a serverless bundle only includes files traced from the app directory,
 * so "../companies.registry.yaml" is simply absent in production and the
 * company list silently comes up empty. Bundling a generated JSON copy
 * makes it a module import, which the bundler always includes.
 */
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { parse } from "yaml";

const here = dirname(fileURLToPath(import.meta.url));
const source = join(here, "..", "..", "companies.registry.yaml");
const target = join(here, "..", "src", "generated", "registry.json");

let companies = [];
try {
  companies = (parse(readFileSync(source, "utf8"))?.companies ?? []).filter(
    (e) => e?.name,
  );
} catch (err) {
  // A missing registry must not fail the build; the UI degrades to "no
  // known companies" rather than refusing to deploy.
  console.warn(`[sync-registry] could not read ${source}: ${err.message}`);
}

mkdirSync(dirname(target), { recursive: true });
writeFileSync(target, JSON.stringify(companies, null, 1));
console.log(`[sync-registry] wrote ${companies.length} companies`);
