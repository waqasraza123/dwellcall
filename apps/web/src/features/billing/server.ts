import { backendOrigin } from "@/lib/backend";
import { parseCatalog, type PricingCatalog } from "./contracts";

export async function publicCatalog(): Promise<PricingCatalog | null> {
  try {
    const response = await fetch(`${backendOrigin()}/api/v1/billing/plans`, { cache: "no-store", redirect: "error", signal: AbortSignal.timeout(5000) });
    return response.ok ? parseCatalog(await response.json()) : null;
  } catch { return null; }
}
