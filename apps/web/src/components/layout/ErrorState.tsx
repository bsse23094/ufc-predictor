"use client";

import React from "react";

interface ErrorStateProps {
  title?: string;
  message?: string;
  requestId?: string;
  onRetry?: () => void;
  style?: React.CSSProperties;
}

export function ErrorState({
  title = "Failed to load data",
  message = "A problem occurred while communicating with the analytics service. Please try again.",
  requestId,
  onRetry,
  style = {},
}: ErrorStateProps) {
  return (
    <div
      role="alert"
      style={{
        padding: "2rem",
        borderRadius: "var(--radius-lg, 12px)",
        border: "1px solid rgba(239, 68, 68, 0.25)",
        backgroundColor: "rgba(239, 68, 68, 0.05)",
        backdropFilter: "blur(12px)",
        textAlign: "center",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: "0.875rem",
        margin: "1.5rem 0",
        ...style,
      }}
    >
      <div
        style={{
          width: "44px",
          height: "44px",
          borderRadius: "50%",
          backgroundColor: "rgba(239, 68, 68, 0.15)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "#f87171",
          fontSize: "1.25rem",
          fontWeight: 700,
        }}
      >
        !
      </div>
      <h3 style={{ margin: 0, fontSize: "1.125rem", color: "#fca5a5", fontWeight: 600 }}>{title}</h3>
      <p style={{ margin: 0, fontSize: "0.875rem", color: "rgba(255, 255, 255, 0.7)", maxWidth: "480px" }}>
        {message}
      </p>
      {requestId && (
        <code
          style={{
            fontSize: "0.75rem",
            color: "rgba(255, 255, 255, 0.4)",
            backgroundColor: "rgba(0, 0, 0, 0.3)",
            padding: "0.25rem 0.5rem",
            borderRadius: "4px",
          }}
        >
          Request ID: {requestId}
        </code>
      )}
      {onRetry && (
        <button
          onClick={onRetry}
          style={{
            marginTop: "0.5rem",
            padding: "0.5rem 1.25rem",
            fontSize: "0.875rem",
            fontWeight: 600,
            color: "#fff",
            backgroundColor: "rgba(239, 68, 68, 0.8)",
            border: "none",
            borderRadius: "var(--radius-md, 8px)",
            cursor: "pointer",
            transition: "all 0.2s ease",
          }}
          onMouseOver={(e) => (e.currentTarget.style.backgroundColor = "rgba(239, 68, 68, 1)")}
          onMouseOut={(e) => (e.currentTarget.style.backgroundColor = "rgba(239, 68, 68, 0.8)")}
        >
          Retry Request
        </button>
      )}
    </div>
  );
}
