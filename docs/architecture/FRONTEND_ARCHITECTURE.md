# Frontend architecture

## Product direction

Build a Next.js TypeScript application using the App Router, React Server Components where useful, TanStack Query for server state, a professional accessible component foundation, and Recharts for standard charts with D3 only for interactions Recharts cannot express.

The visual language is a premium sports analytics workspace: near-black/slate surfaces, restrained red accents for selection and emphasis, off-white text, tabular numerals, strong display typography, and generous hierarchy despite dense statistics. Red must not mean both fighter identity and error. Avoid casino imagery, flashing odds, fake urgency, win guarantees, or betting calls to action.

## Information architecture

Primary navigation:

- Upcoming
- Fighters
- Compare
- Simulator
- History
- Model performance
- Methodology
- Data transparency

Secondary/footer:

- About/intended use
- API/data version
- Accessibility
- Privacy/terms
- Admin for authorized roles

URLs contain stable entity IDs plus readable slugs where desired; IDs remain authoritative. Filters, tabs, comparison fighters, and public shareable simulation parameters use validated URL search state. Sensitive/large simulation payloads use stored result IDs.

## Page specifications

### 1. Landing page

Purpose: explain the platform and route users to upcoming analysis.

Sections: upcoming featured card, product capabilities, latest frozen prediction highlights, how uncertainty works, methodology/transparency links, data freshness strip, and no-betting/intended-use statement.

States: if no upcoming card exists, show recent historical analysis and a clear empty message. Do not fabricate featured fights.

### 2. Upcoming events

Route: /events/upcoming

Event groups show scheduled date/time with user timezone, card completeness/freshness, prediction coverage, and status changes. Filters are modest because volume is low. Skeleton cards match final dimensions to avoid layout shifts.

### 3. Event details

Route: /events/[event_id]/[slug]

Header includes event metadata, last observed schedule, and model/data version selection policy. Fight rows show matchup, pure winner range/probabilities, method summary, confidence/quality badge, prediction cutoff, and link to detail. Pure and market views are distinctly labeled and can be compared only when both exist.

### 4. Fight prediction

Route: /fights/[fight_id]/prediction with optional prediction snapshot query

Hierarchy:

1. fighter identities and scheduled context;
2. calibrated win probabilities with both numbers and accessible text;
3. confidence/uncertainty and data-quality warnings adjacent to the estimate;
4. fighter-specific KO/submission/decision paths;
5. round and duration distribution with conditioning label;
6. tale of the tape and recent form;
7. grouped explanation factors with non-causal wording;
8. similar historical matchups;
9. version, cutoff, horizon, source freshness, and methodology.

Never rely on color alone to identify fighters; use names, A/B labels, patterns, and consistent sides.

### 5. Fighter directory

Route: /fighters

Search, division/status filters, keyset pagination/infinite loading with an accessible load-more alternative. Cards show only well-supported summary fields and freshness. Empty, typo, and API-error states are distinct.

### 6. Fighter profile

Route: /fighters/[fighter_id]/[slug]

Verified observation summary, historical fights, rolling performance charts, ratings/rank history, format/method summaries, quality/coverage notes, and compare action. Current profile observations include observed date when relevant; historical charts use point-in-time data.

### 7. Fighter comparison

Route: /compare?fighter_a=...&fighter_b=...

Search selectors, symmetric tale of the tape, signed differences, trends, style interactions, data coverage, and a context form that can request a hypothetical prediction. Swapping fighters must preserve meaning and flip signed displays cleanly.

### 8. Matchup simulator

Route: /simulator and /simulations/[simulation_id]

Base matchup/prediction panel; allow-listed controls grouped by physical/context, form/activity, striking/grappling, and format; observed marker and reset per control; plausibility range and synthetic label; live/debounced or submitted result; probability delta; uncertainty delta; changed-factor explanation; Monte Carlo job progress and distributions.

The form never makes edits look like canonical fighter data. Share URLs use stored immutable simulation IDs.

### 9. Historical fights

Route: /history

Filters by date, division, fighter, event, result method, and format; paginated result table/cards; link to pre-fight frozen predictions where available. It explicitly distinguishes actual outcome from what the model knew before the fight.

### 10. Model performance

Route: /models and /models/[model_id]

Model cards, version timeline, pure/market distinction, intended use, primary metrics, calibration curves, cohort/horizon selector, confusion matrices, coverage/risk curves, limitations, and dataset cutoff. Never collapse performance to accuracy alone.

### 11. Methodology

Route: /methodology

Plain-language data flow, leakage controls, orientation strategy, model hierarchy, calibration, uncertainty, simulations, explainability limitations, and change log/architecture links.

### 12. Data freshness and transparency

Route: /data-transparency

Per-source observed/retrieved/published freshness, known gaps, identity/quality issue summaries safe for public display, coverage caveats, dataset/model versions, correction policy, and status incidents.

### 13. Admin dashboard

Route: /admin, protected and dynamically imported.

Ingestion runs, source freshness, quarantines/identity queues, model candidates, promotion/rollback confirmation, jobs, and audit history. Destructive or state-changing actions require re-auth/confirmation, expected version, reason, and display the audit effect.

## Component system

### Foundations

- design tokens for color, spacing, type scale, radii, shadows, motion, and chart palettes;
- accessible primitive library such as Radix-based components wrapped in packages/ui;
- AppShell, PageHeader, Section, Card, DataTable, Tabs, Drawer, Dialog, Tooltip, Toast;
- StatusMessage, EmptyState, ErrorState, Skeleton, RetryBoundary;
- VisuallyHidden, SkipLink, focus-ring and reduced-motion utilities.

The exact component library is chosen during foundation based on license, Next compatibility, accessibility, and theming. Wrapping primitives prevents vendor APIs from spreading, at the cost of a small maintenance layer.

### Domain components

- FighterCard and FighterAvatar fallback;
- FighterSelector and MatchupHeader;
- ProbabilityBar/Gauge with numeric/accessible alternative;
- ConfidenceBadge plus ConfidenceBreakdown;
- MethodProbabilityChart and FighterPathTable;
- RoundDistributionChart and DurationDistribution;
- TaleOfTheTape and DifferenceCell;
- RadarChart only when axes share interpretable scaling; a table alternative is always present;
- RollingPerformanceChart and RatingHistoryChart;
- OddsMovementChart, visible only for market mode with cutoff;
- ExplanationWaterfall/SHAPGroupChart;
- SimilarFightCard;
- SimulationControls and ObservedModifiedValue;
- DataQualityWarning, FreshnessIndicator, ModelVersionIndicator;
- MetricCard, CalibrationChart, ConfusionMatrix, RiskCoverageChart.

All charts provide text summaries or accessible tables, keyboard tooltips when interactive, and non-color encodings.

## State management

| State type | Owner | Rationale/trade-off |
|---|---|---|
| API/server state | TanStack Query | Cache, retries, invalidation, and request lifecycle; adds client bundle only on interactive surfaces |
| Initial/static SEO data | Server Components | Smaller client bundle and fast content; cannot own rich client interaction |
| Shareable filters/comparison | URL search params | Deep links and browser history; requires schema parsing |
| Form/validation | React Hook Form plus generated/Zod-compatible schema | Efficient complex simulator forms; dual-schema drift must be CI checked |
| Ephemeral UI | Local React state | Avoids global-state coupling |
| Auth session | Secure httpOnly cookie/BFF-compatible session boundary | Reduces token exposure; needs server mediation |

Do not introduce Redux/Zustand for the MVP. If cross-page client-only workflow state emerges and cannot live in URL/server, document the need in an ADR. This keeps the mental model small, at the cost of deliberate URL/schema work.

## Data fetching

- Generate a typed client from versioned OpenAPI into packages/shared-types/client.
- Server-render public catalog/detail shells when it improves discovery and first content.
- Hydrate only interactive queries; avoid fetching the same resource independently in many widgets.
- Query keys include entity and snapshot/version selectors.
- Historical immutable data uses long stale times; upcoming/freshness uses short refetch intervals; job status polls with backoff and stops at terminal state.
- Mutations carry request ID/idempotency key and map typed field errors to controls.
- Abort stale fighter searches and simulator requests.

## Visualization semantics

- Fighter sides use a neutral A/B palette; controlled red is brand emphasis, not automatic winner encoding.
- Show exact probability text alongside bars; 50% receives no moral/positive treatment.
- Show calibration/uncertainty near predictions, not hidden in a tooltip.
- Method paths are joint probabilities labeled by fighter and method; do not confuse conditional versus unconditional.
- Duration and finishing-round charts label whether conditioned on a finish.
- Odds charts are analytical provenance for Model B, not a wagering prompt.
- SHAP text says contributes to/associated with, never causes.

## Responsive behavior

- 360-599 px: stacked fighter header, compact probability bar, tabbed/accordion secondary panels, scrollable chart with table alternative.
- 600-1023 px: two-column comparisons where readable, collapsible filters.
- 1024 px and above: persistent analysis rail, two/three-column dense grid, wider tables.

Touch targets are at least 44 by 44 CSS pixels where practical. Dense desktop tables transform into labeled cards or controlled horizontal regions; critical identities/probabilities never require horizontal scrolling.

## Accessibility

Target WCAG 2.2 AA:

- semantic headings, landmarks, lists, tables, and form labels;
- visible focus and logical focus order;
- dialogs trap/restore focus correctly;
- contrast checked for text, focus, and charts;
- no information conveyed by color alone;
- reduced motion and no gratuitous animation;
- live regions only for job/error updates to avoid noise;
- chart summaries/tables and downloadable accessible metric data where allowed;
- time shown with timezone and machine-readable element;
- probability spoken as percent with context.

Automated axe tests are necessary but do not replace keyboard and screen-reader passes.

## Error, empty, stale, and loading states

Every data surface distinguishes:

- loading skeleton;
- no matching data;
- source not yet available;
- unsupported/insufficient model input;
- stale but usable cached data with timestamp;
- dependency failure with retry;
- forbidden/internal-only content;
- job queued/running/failed/expired.

Errors display request IDs for support but no internals. A stale prediction remains tied to its immutable cutoff; it is not relabeled current.

## Performance budgets

Initial targets:

- keep landing route client JavaScript minimal through Server Components;
- lazy-load advanced charts/admin/simulation panels;
- avoid shipping full model feature data;
- image optimization and fixed aspect ratios;
- Web Vitals targets reviewed in CI/production;
- bundle-size budgets established after the foundation build and treated as gates.

Exact kilobyte numbers are set from the implemented baseline rather than fabricated now.

## Frontend testing

- unit/component tests for semantics and state variants;
- Mock Service Worker contract fixtures generated from OpenAPI;
- axe tests for every major component/page;
- viewport screenshots at mobile/tablet/desktop;
- Playwright journeys for discovery, fight prediction, compare, counterfactual, Monte Carlo job, error/stale states, and admin authorization;
- swap symmetry UI test and pure/market labeling test;
- no-betting-copy and version-metadata assertions.

