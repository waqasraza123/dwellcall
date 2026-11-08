import Link from "next/link";
export function Brand() {
  return <Link aria-label="DwellCall home" className="brand-link" href="/"><svg aria-hidden="true" width="36" height="36" viewBox="0 0 36 36"><rect width="36" height="36" rx="8" fill="var(--ink)"/><path d="m8 17 10-8 10 8M11 15v12h14V15M16 27v-8h5v8" fill="none" stroke="var(--bronze-light)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/></svg><span>Dwell<span className="brand-line">Call</span><small>OUTBOUND VOICE AGENT</small></span></Link>;
}
export function GitHubLink() {
  if (process.env.DWELLCALL_GITHUB_LINK_ENABLED === "false") return null;
  return <a className="icon-link" href="https://github.com/waqasraza123/dwellcall" target="_blank" rel="noopener noreferrer" aria-label="DwellCall on GitHub (opens in a new tab)" title="DwellCall on GitHub"><svg aria-hidden="true" width="21" height="21" viewBox="0 0 24 24" fill="currentColor"><path d="M12 .8a11.4 11.4 0 0 0-3.6 22.2c.6.1.8-.3.8-.6v-2.1c-3.3.7-4-1.4-4-1.4-.5-1.4-1.3-1.8-1.3-1.8-1.1-.8.1-.8.1-.8 1.2.1 1.8 1.2 1.8 1.2 1.1 1.8 2.8 1.3 3.5 1 .1-.8.4-1.3.8-1.6-2.7-.3-5.5-1.4-5.5-6a4.7 4.7 0 0 1 1.3-3.2c-.1-.3-.6-1.6.1-3.3 0 0 1.1-.4 3.4 1.2a11.7 11.7 0 0 1 6.2 0C18 4 19.1 4.4 19.1 4.4c.7 1.7.2 3 .1 3.3a4.7 4.7 0 0 1 1.3 3.2c0 4.6-2.8 5.7-5.5 6 .5.4.8 1.1.8 2.2v3.3c0 .3.2.7.8.6A11.4 11.4 0 0 0 12 .8Z"/></svg></a>;
}
