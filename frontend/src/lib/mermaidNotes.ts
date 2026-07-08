export const MERMAID_TEMPLATES = [
  {
    label: "Flow",
    markdown: "```mermaid\nflowchart TD\n  User[User] --> App[App]\n  App --> API[API]\n  API --> DB[(Database)]\n```",
  },
  {
    label: "Sequence",
    markdown: "```mermaid\nsequenceDiagram\n  participant User\n  participant App\n  participant API\n  User->>App: Save note\n  App->>API: PATCH /notes/{id}\n  API-->>App: Updated note\n```",
  },
  {
    label: "Architecture",
    markdown: "```mermaid\nflowchart LR\n  UI[Frontend] --> API[Backend API]\n  API --> Store[(SQLite)]\n  API --> Search[Search index]\n  API --> Graph[Knowledge graph]\n```",
  },
  {
    label: "State",
    markdown: "```mermaid\nstateDiagram-v2\n  [*] --> Draft\n  Draft --> Saved\n  Saved --> Edited\n  Edited --> Saved\n```",
  },
] as const
