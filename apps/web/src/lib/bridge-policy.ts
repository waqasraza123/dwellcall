const id = "[a-fA-F0-9-]{36}";
const source = "[a-z0-9][a-z0-9_-]{0,63}";
const getPaths = [
  /^intelligence\/(providers|sources|listings|agents|runs|reviews)$/,
  new RegExp(`^intelligence/reviews/${id}$`),
  /^intelligence\/workspace\/(dashboard|activity|jobs|attempts|reviews)$/,
  new RegExp(`^intelligence/workspace/listings/${id}(/history)?$`),
  new RegExp(`^intelligence/workspace/agents/${id}$`),
  /^crm\/ghl\/(status|agents|jobs)$/, new RegExp(`^crm/ghl/jobs/${id}/audit$`),
];
const postPaths = [
  /^intelligence\/workspace\/(jobs|demo\/setup)$/,
  new RegExp(`^intelligence/workspace/jobs/${id}/run$`),
  new RegExp(`^intelligence/agents/${id}/suppress$`),
  new RegExp(`^intelligence/reviews/${id}/resolve$`),
  /^crm\/ghl\/(setup|agents\/queue|jobs\/process)$/,
  new RegExp(`^crm/ghl/jobs/${id}/(retry|reconcile)$`),
  new RegExp(`^crm/ghl/agents/${id}/bind$`),
];
export function bridgeAllowed(method: string, path: string): boolean {
  if (path.includes("..") || path.includes("%") || path.includes("\\")) return false;
  return method === "GET" ? getPaths.some(p => p.test(path)) : method === "POST" ? postPaths.some(p => p.test(path)) : method === "PUT" && (new RegExp(`^intelligence/workspace/jobs/${id}$`).test(path) || new RegExp(`^intelligence/sources/${source}$`).test(path));
}
