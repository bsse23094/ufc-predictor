"use client";

import { useFreshness } from "@/lib/query/hooks";

export default function DataTransparencyPage() {
  const freshness = useFreshness();
  return (
    <main className="container" style={{ paddingTop: "2rem", paddingBottom: "4rem" }}>
      <h1>Data transparency</h1>
      <p style={{ color: "var(--color-text-secondary)" }}>
        Source counts and statuses reflect data available to the API now. An accepted historical
        generation does not imply a current upcoming schedule.
      </p>
      {freshness.isLoading && <p role="status">Loading source status…</p>}
      {freshness.isError && <p role="alert">Source status unavailable: {freshness.error.message}</p>}
      {freshness.data && (
        <>
          <p>Accepted generation: <code>{freshness.data.accepted_dataset_generation_id}</code></p>
          <p>Prediction data cutoff: {freshness.data.prediction_cutoff_date}</p>
          <div style={{ overflowX: "auto" }}>
            <table className="tott-table">
              <caption>Available data sources</caption>
              <thead><tr><th>Source</th><th>License</th><th>Records</th><th>Status</th><th>Last published</th></tr></thead>
              <tbody>{freshness.data.sources.map((source) => (
                <tr key={source.stable_key}>
                  <td>{source.display_name}</td>
                  <td>{source.dataset_license || "Unspecified"}</td>
                  <td>{source.published_records_count}</td>
                  <td>{source.status}</td>
                  <td>{source.last_published_timestamp || "Not available"}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
          {freshness.data.limitations.map((limitation) => <p key={limitation}>{limitation}</p>)}
        </>
      )}
    </main>
  );
}
