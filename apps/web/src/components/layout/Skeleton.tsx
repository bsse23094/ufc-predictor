import React from "react";

interface SkeletonProps {
  className?: string;
  width?: string | number;
  height?: string | number;
  borderRadius?: string | number;
  style?: React.CSSProperties;
}

export function Skeleton({
  className = "",
  width = "100%",
  height = "1.25rem",
  borderRadius = "var(--radius-sm, 6px)",
  style = {},
}: SkeletonProps) {
  return (
    <div
      className={`skeleton-pulse ${className}`}
      style={{
        width,
        height,
        borderRadius,
        backgroundColor: "rgba(255, 255, 255, 0.06)",
        backgroundImage:
          "linear-gradient(90deg, rgba(255, 255, 255, 0.03) 0%, rgba(255, 255, 255, 0.08) 50%, rgba(255, 255, 255, 0.03) 100%)",
        backgroundSize: "200% 100%",
        animation: "skeleton-shimmer 1.8s infinite ease-in-out",
        ...style,
      }}
    />
  );
}

export function CardSkeleton({ height = "180px" }: { height?: string }) {
  return (
    <div
      style={{
        padding: "1.25rem",
        borderRadius: "var(--radius-md, 12px)",
        border: "1px solid rgba(255, 255, 255, 0.08)",
        backgroundColor: "rgba(18, 18, 20, 0.6)",
        backdropFilter: "blur(8px)",
        display: "flex",
        flexDirection: "column",
        gap: "0.75rem",
        height,
      }}
    >
      <Skeleton width="40%" height="1.25rem" />
      <Skeleton width="75%" height="0.875rem" />
      <div style={{ flex: 1 }} />
      <Skeleton width="100%" height="2rem" borderRadius="8px" />
    </div>
  );
}
