"use client";

export default function GlobalError({ reset }: Readonly<{ error: Error; reset: () => void }>) {
  return (
    <main className="foundation-card" role="alert">
      <h1>Something went wrong</h1>
      <p>Retry the request. If this persists, retain the request ID shown by the API for support.</p>
      <button type="button" onClick={reset}>
        Retry
      </button>
    </main>
  );
}
