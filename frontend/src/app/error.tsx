"use client";

import Link from "next/link";

export default function ErrorPage({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return <section className="panel p-8" role="alert">
    <div className="label">RAHAT / Page unavailable</div>
    <h1 className="mt-4">This view could not load.</h1>
    <p className="my-5 text-muted">Try loading it again. Your saved records have not been changed.</p>
    <div className="flex flex-wrap gap-3"><button className="btn btn-primary" onClick={reset}>Try again →</button><Link href="/" className="btn">Return to overview</Link></div>
  </section>;
}
