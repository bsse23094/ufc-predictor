"use client";

import Link from "next/link";
import { useModels, useModelMetrics } from "@/lib/query/hooks";

export default function ModelsPage() {
  const models = useModels();
  const champion = models.data?.[0];
  const evaluation = useModelMetrics(champion?.model_id || "");

  return (
    <main className="container" style={{ paddingTop: "2rem", paddingBottom: "4rem" }}>
      <h1>Model performance</h1>
      <p style={{ color: "var(--color-text-secondary)" }}>
        Evaluation values below come from the accepted local champion bundle.
        Only the winner model is available for production inference.
      </p>
      {models.isLoading && <p role="status">Loading model card…</p>}
      {models.isError && <p role="alert">Model card unavailable: {models.error.message}</p>}
      {models.data?.length === 0 && <p>No accepted model card is available.</p>}
      {champion && (
        <section className="card" style={{ padding: "1.5rem", margin: "1.5rem 0" }}>
          <h2>{champion.model_id}</h2>
          <dl>
            <dt>Model family</dt><dd>{champion.family}</dd>
            <dt>Training cutoff</dt><dd>{champion.training_cutoff_date}</dd>
            <dt>Feature schema</dt><dd>{champion.feature_schema_version}</dd>
            <dt>Bundle hash</dt><dd><code>{champion.bundle_hash}</code></dd>
          </dl>
          {evaluation.isLoading && <p role="status">Loading evaluation…</p>}
          {evaluation.isError && <p role="alert">Evaluation unavailable: {evaluation.error.message}</p>}
          {evaluation.data?.metrics && (
            <dl>
              <dt>Out-of-time ROC AUC</dt><dd>{evaluation.data.metrics.roc_auc.toFixed(3)}</dd>
              <dt>Brier score</dt><dd>{evaluation.data.metrics.brier_score.toFixed(3)}</dd>
              <dt>Log loss</dt><dd>{evaluation.data.metrics.log_loss.toFixed(3)}</dd>
              <dt>Evaluated rows</dt><dd>{evaluation.data.metrics.evaluated_row_count}</dd>
            </dl>
          )}
        </section>
      )}
      <Link href="/data-transparency">View data provenance and freshness</Link>
    </main>
  );
}
