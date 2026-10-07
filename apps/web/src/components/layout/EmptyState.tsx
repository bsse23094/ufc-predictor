import React from "react";

interface EmptyStateProps {
  title?: string;
  message?: string;
  actionText?: string;
  onAction?: () => void;
  style?: React.CSSProperties;
}

export function EmptyState({
  title = "No results found",
  message = "No matching records were discovered for the specified filters or criteria.",
  actionText,
  onAction,
  style = {},
}: EmptyStateProps) {
  return (
    <div
      style={{
        padding: "3rem 1.5rem",
        borderRadius: "var(--radius-lg, 12px)",
        border: "1px dashed rgba(255, 255, 255, 0.15)",
        backgroundColor: "rgba(255, 255, 255, 0.02)",
        textAlign: "center",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: "0.75rem",
        margin: "1.5rem 0",
        ...style,
      }}
    >
      <div
        style={{
          width: "48px",
          height: "48px",
          borderRadius: "50%",
          backgroundColor: "rgba(255, 255, 255, 0.05)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "rgba(255, 255, 255, 0.4)",
          fontSize: "1.25rem",
        }}
      >
        ∅
      </div>
      <h3 style={{ margin: 0, fontSize: "1.125rem", color: "rgba(255, 255, 255, 0.85)", fontWeight: 600 }}>
        {title}
      </h3>
      <p style={{ margin: 0, fontSize: "0.875rem", color: "rgba(255, 255, 255, 0.5)", maxWidth: "420px" }}>
        {message}
      </p>
      {actionText && onAction && (
        <button
          onClick={onAction}
          style={{
            marginTop: "0.75rem",
            padding: "0.5rem 1.25rem",
            fontSize: "0.875rem",
            fontWeight: 600,
            color: "var(--color-primary-text, #fff)",
            backgroundColor: "rgba(255, 255, 255, 0.1)",
            border: "1px solid rgba(255, 255, 255, 0.2)",
            borderRadius: "var(--radius-md, 8px)",
            cursor: "pointer",
            transition: "all 0.2s ease",
          }}
          onMouseOver={(e) => (e.currentTarget.style.backgroundColor = "rgba(255, 255, 255, 0.18)")}
          onMouseOut={(e) => (e.currentTarget.style.backgroundColor = "rgba(255, 255, 255, 0.1)")}
        >
          {actionText}
        </button>
      )}
    </div>
  );
}
