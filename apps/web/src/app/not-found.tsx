import Link from "next/link";
export default function NotFound() { return <main className="ops-card error-boundary"><h1>That page isn’t here.</h1><p>Open your workspace to find listings, agents and discovery activity.</p><Link href="/dashboard">Open dashboard →</Link></main>; }
