const id = "[a-fA-F0-9-]{36}";
const source = "[a-z0-9][a-z0-9_-]{0,63}";
const getPaths = [
  new RegExp(`^outbound/calls/${id}/intelligence$`),
  /^outbound\/(availability|calls|leads)$/,
  new RegExp(`^outbound/(calls|requests)/${id}$`),
  /^intelligence\/(providers|sources|listings|agents|runs|reviews)$/,
  new RegExp(`^intelligence/reviews/${id}$`),
  /^intelligence\/workspace\/(dashboard|activity|jobs|attempts|reviews)$/,
  new RegExp(`^intelligence/workspace/listings/${id}(/history)?$`),
  new RegExp(`^intelligence/workspace/agents/${id}$`),
  /^crm\/providers$/,
  /^crm\/(ghl|hubspot)\/(status|agents|jobs)$/, new RegExp(`^crm/(ghl|hubspot)/jobs/${id}/audit$`),
  /^crm\/admin\/destination$/, new RegExp(`^crm/admin/exports/${id}$`),
];
const postPaths = [
  /^outbound\/transcripts\/purge$/,
  new RegExp(`^outbound/calls/${id}/analyze$`),
  /^outbound\/(calls|preflight|controls|suppress)$/,
  new RegExp(`^outbound/calls/${id}/(refresh|bind|stop|carrier-ended)$`),
  /^crm\/hubspot\/properties\/create$/,
  /^intelligence\/workspace\/(jobs|demo\/setup)$/,
  new RegExp(`^intelligence/workspace/jobs/${id}/run$`),
  new RegExp(`^intelligence/agents/${id}/suppress$`),
  new RegExp(`^intelligence/reviews/${id}/resolve$`),
  /^crm\/(ghl|hubspot)\/(setup|agents\/queue|jobs\/process)$/,
  new RegExp(`^crm/(ghl|hubspot)/jobs/${id}/(retry|reconcile)$`),
  new RegExp(`^crm/(ghl|hubspot)/agents/${id}/bind$`),
];
export function bridgeAllowed(method: string, path: string, extensionsEnabled = false): boolean {
  if (!extensionsEnabled && (!path.startsWith("outbound/") || path === "outbound/leads")) return false;
  if (path.includes("..") || path.includes("%") || path.includes("\\")) return false;
  return method === "GET" ? getPaths.some(p => p.test(path)) : method === "POST" ? postPaths.some(p => p.test(path)) : method === "PUT" && (new RegExp(`^intelligence/workspace/jobs/${id}$`).test(path) || new RegExp(`^intelligence/sources/${source}$`).test(path));
}
