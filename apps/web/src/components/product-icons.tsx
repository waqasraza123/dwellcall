export type IconName = "arrow" | "check" | "home" | "shield" | "clock" | "close" | "logout";
const paths: Record<IconName, string> = {
  "arrow": "M5 12h14m-6-6 6 6-6 6",
  "check": "m5 12 4 4L19 6",
  "home": "m3 10 9-7 9 7M5 9v12h14V9M9 21v-8h6v8",
  "shield": "m12 3 8 3v6c0 4-4 7-8 9-4-2-8-5-8-9V6l8-3Zm-4 9 3 3 5-6",
  "clock": "M12 8v5l3 2M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0Z",
  "close": "m6 6 12 12M6 18 18 6",
  "logout": "M9 4H4v16h5m5-12 4 4-4 4m-6-4h12"
};
export function ProductIcon({ name, className }: { name: IconName; className?: string }) {
  return <svg className={className} width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]}/></svg>;
}
