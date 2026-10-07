"use client";

import { useState, useRef, useEffect, useMemo } from "react";
import { useFighters } from "@/lib/query/hooks";

interface FighterOption {
  id: string;
  name: string;
  division?: string;
  record?: string;
}

interface FighterSearchSelectProps {
  label: string;
  corner: "a" | "b";
  selectedId: string;
  selectedName?: string;
  onSelect: (fighterId: string, fighterName: string) => void;
  disabledId?: string;
}

export function FighterSearchSelect({
  label,
  corner,
  selectedId,
  selectedName,
  onSelect,
  disabledId,
}: FighterSearchSelectProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [search, setSearch] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);

  // Search query with debounce
  const { data: searchResults, isLoading } = useFighters(search, undefined, 40);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // Compute matched options
  const options = useMemo(() => {
    const list: FighterOption[] = [];
    const seen = new Set<string>();

    if (searchResults?.items && searchResults.items.length > 0) {
      for (const item of searchResults.items) {
        const id = item.id;
        if (!seen.has(id)) {
          seen.add(id);
          list.push({
            id,
            name: item.display_name || `${item.first_name || ""} ${item.last_name || ""}`.trim() || id,
            division: item.division || item.weight_class || "UFC",
          });
        }
      }
    }

    return list;
  }, [searchResults]);

  const cornerColor = corner === "a" ? "#f24949" : "#6caae9";
  const cornerBg = corner === "a" ? "rgba(242, 73, 73, 0.12)" : "rgba(108, 170, 233, 0.12)";
  const cornerBorder = corner === "a" ? "rgba(242, 73, 73, 0.3)" : "rgba(108, 170, 233, 0.3)";

  const currentDisplay = selectedName || selectedId;

  return (
    <div ref={containerRef} style={{ position: "relative", width: "100%" }}>
      <label
        style={{
          display: "flex",
          alignItems: "center",
          gap: "0.5rem",
          fontSize: "0.75rem",
          fontWeight: 700,
          letterSpacing: "0.06em",
          textTransform: "uppercase",
          color: cornerColor,
          marginBottom: "0.4rem",
        }}
      >
        <span
          style={{
            width: "8px",
            height: "8px",
            borderRadius: "50%",
            backgroundColor: cornerColor,
            boxShadow: `0 0 8px ${cornerColor}`,
          }}
        />
        {label}
      </label>

      {/* Main trigger button */}
      <button
        type="button"
        aria-label={`${label}: ${currentDisplay || "select a fighter"}`}
        aria-expanded={isOpen}
        onClick={() => setIsOpen((prev) => !prev)}
        style={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "0.625rem 0.875rem",
          borderRadius: "8px",
          backgroundColor: "rgba(15, 23, 42, 0.8)",
          border: `1px solid ${isOpen ? cornerColor : "rgba(255, 255, 255, 0.12)"}`,
          cursor: "pointer",
          transition: "all 0.15s ease",
          boxShadow: isOpen ? `0 0 0 2px ${cornerBg}` : "none",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", overflow: "hidden" }}>
          <span
            style={{
              padding: "0.15rem 0.45rem",
              borderRadius: "4px",
              fontSize: "0.6875rem",
              fontWeight: 800,
              backgroundColor: cornerBg,
              color: cornerColor,
              border: `1px solid ${cornerBorder}`,
            }}
          >
            {corner.toUpperCase()}
          </span>
          <span style={{ fontWeight: 700, color: "#fff", fontSize: "0.9375rem", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            {currentDisplay}
          </span>
        </div>
        <span style={{ fontSize: "0.75rem", color: "var(--color-text-muted, #64748b)" }}>
          {isOpen ? "▲" : "▼"}
        </span>
      </button>

      {/* Dropdown panel */}
      {isOpen && (
        <div
          style={{
            position: "absolute",
            top: "calc(100% + 4px)",
            left: 0,
            right: 0,
            zIndex: 100,
            borderRadius: "8px",
            backgroundColor: "#0d131f",
            border: "1px solid rgba(255, 255, 255, 0.15)",
            boxShadow: "0 10px 25px -5px rgba(0, 0, 0, 0.6), 0 8px 10px -6px rgba(0, 0, 0, 0.6)",
            padding: "0.5rem",
            maxHeight: "340px",
            overflow: "hidden",
            display: "flex",
            flexDirection: "column",
          }}
        >
          {/* Search box inside dropdown */}
          <div style={{ padding: "0.25rem", marginBottom: "0.35rem" }}>
            <input
              type="text"
              autoFocus
              placeholder="Type fighter name (e.g. Jones, Pereira)..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={{
                width: "100%",
                padding: "0.5rem 0.75rem",
                borderRadius: "6px",
                backgroundColor: "rgba(255, 255, 255, 0.06)",
                border: "1px solid rgba(255, 255, 255, 0.12)",
                color: "#fff",
                fontSize: "0.875rem",
                outline: "none",
              }}
            />
          </div>

          <div
            style={{
              overflowY: "auto",
              flex: 1,
              display: "flex",
              flexDirection: "column",
              gap: "2px",
            }}
          >
            {isLoading && (
              <div style={{ padding: "0.75rem", fontSize: "0.8125rem", color: "var(--color-text-muted)", textAlign: "center" }}>
                Searching roster...
              </div>
            )}

            {!isLoading && options.length === 0 && (
              <div style={{ padding: "0.75rem", fontSize: "0.8125rem", color: "var(--color-text-muted)", textAlign: "center" }}>
                No fighters found matching &quot;{search}&quot;
              </div>
            )}

            {!search.trim() && (
              <div
                style={{
                  fontSize: "0.6875rem",
                  fontWeight: 700,
                  textTransform: "uppercase",
                  color: "var(--color-text-muted, #64748b)",
                  padding: "0.25rem 0.5rem",
                  letterSpacing: "0.05em",
                }}
              >
                Featured Fighters
              </div>
            )}

            {options.map((opt) => {
              const isSelected = opt.id === selectedId;
              const isDisabled = opt.id === disabledId;

              return (
                <button
                  key={opt.id}
                  disabled={isDisabled}
                  onClick={() => {
                    onSelect(opt.id, opt.name);
                    setIsOpen(false);
                    setSearch("");
                  }}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    padding: "0.5rem 0.65rem",
                    borderRadius: "6px",
                    backgroundColor: isSelected ? cornerBg : "transparent",
                    border: "none",
                    textAlign: "left",
                    color: isDisabled ? "rgba(255, 255, 255, 0.25)" : "#fff",
                    cursor: isDisabled ? "not-allowed" : "pointer",
                    transition: "background-color 0.1s ease",
                  }}
                  onMouseEnter={(e) => {
                    if (!isDisabled && !isSelected) {
                      e.currentTarget.style.backgroundColor = "rgba(255, 255, 255, 0.05)";
                    }
                  }}
                  onMouseLeave={(e) => {
                    if (!isSelected) {
                      e.currentTarget.style.backgroundColor = "transparent";
                    }
                  }}
                >
                  <div>
                    <div style={{ fontWeight: 600, fontSize: "0.875rem" }}>
                      {opt.name}
                    </div>
                    {opt.division && (
                      <div style={{ fontSize: "0.75rem", color: "var(--color-text-muted, #64748b)" }}>
                        {opt.division}
                      </div>
                    )}
                  </div>
                  {opt.record && (
                    <span className="badge badge-subtle" style={{ fontSize: "0.6875rem" }}>
                      {opt.record}
                    </span>
                  )}
                  {isSelected && (
                    <span style={{ color: cornerColor, fontSize: "0.875rem", fontWeight: 800 }}>
                      ✓
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
