"use client";
import Link from "next/link";
export default function ErrorPage({ reset }: { reset: () => void }) { return <main className="ops-card error-boundary"><h1>This view is unavailable.</h1><p>Your saved work remains on the backend. Refresh history before repeating an action.</p><button className="primary" onClick={reset}>Try loading again</button><Link href="/dashboard">Return to dashboard</Link></main>; }
