# ADR-0010: Frontend state management

Status: Accepted  
Date: 2026-07-17

## Context

The web app has server-fetched catalog/prediction data, shareable filters/comparisons, complex simulator forms, job polling, and ephemeral presentation state. A universal client store would duplicate server caches and obscure URL behavior.

## Decision

Use:

- React Server Components for appropriate initial/static data;
- TanStack Query for interactive server state, caching, mutation, and job polling;
- validated URL search parameters for shareable filters/comparisons;
- React Hook Form/schema integration for forms;
- local React state for ephemeral UI.

Do not add Redux/Zustand in the MVP. Generate API types/client from OpenAPI and wrap the component primitive library in packages/ui.

## Rationale

Each state type has one clear owner. TanStack Query handles asynchronous cache lifecycles; URLs make analysis shareable; local state avoids global coupling. This matches Next.js rather than fighting it.

## Consequences

Positive:

- smaller mental model and less duplicated state;
- predictable deep links/history;
- typed cache invalidation and job polling;
- server rendering can limit client JavaScript.

Negative:

- URL parsing/schema work;
- server/client hydration boundaries need care;
- TanStack Query adds client dependency;
- a future long client workflow might require another store.

## Alternatives

- Redux/Zustand for all state: powerful but duplicates server state and encourages global coupling.
- Server Components only: minimal client JS but inadequate simulator/job interactions.
- Hand-written fetch/effects: fewer dependencies but error/retry/cache races multiply.

## Revisit

Add a client store only after a concrete cross-route state need cannot live in URL/server/query/form state. Document it in a superseding ADR.

