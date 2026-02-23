# Frontend Conventions — Luminary

## Directory Structure

```
src/
  components/   # Reusable UI components (shadcn/ui + custom)
  pages/        # One file per top-level tab route
  lib/          # Utility functions (cn(), etc.)
  store.ts      # Zustand global state (useAppStore)
```

## State Management

- **Zustand** (`useAppStore` in `src/store.ts`): global UI state — active document, LLM mode
- **TanStack Query** (`@tanstack/react-query`): all server state — API fetches, mutations, caching
- Never use `useState` for data that comes from the API; always use TanStack Query

## Runtime Validation

- **Zod** schemas for all API responses at the boundary
- Never trust raw API response shapes without validation
- Define Zod schemas in `src/lib/schemas.ts` (one per API resource)

## TypeScript Rules

- `strict: true` in `tsconfig.app.json` — always
- No `any` types without a comment explaining why it is unavoidable
- Prefer `unknown` over `any` when the type is truly unknown
- All component props must have explicit TypeScript interfaces

## Component Patterns

- Use shadcn/ui components as the base layer; extend with Tailwind classes
- Compose with `cn()` from `src/lib/utils.ts` for conditional classes
- Page components live in `src/pages/` and are route-level only (no reuse)
- Reusable UI elements live in `src/components/`
- Use `lucide-react` for all icons

## Routing

- React Router v6 with declarative `<Routes>` and `<Route>` in `App.tsx`
- Navigation tab routes: `/` (Learning), `/chat`, `/viz`, `/study`, `/monitoring`
- Use `<NavLink>` for sidebar navigation (active state via `isActive` callback)

## Performance

- Use TanStack Query's `staleTime` and `gcTime` appropriately — avoid over-fetching
- Large lists use virtualization (TanStack Virtual or react-window)
- Knowledge graph visualization uses Sigma.js v3 + Graphology (WebGL, handles 10K+ nodes)
- Flashcard animations use Framer Motion
