# Demo Review Gates

Demo review gates are human-only checkpoints in the Ralph task loop.
They block the agent from advancing until a human has manually verified
that a feature works end-to-end in the running application.

## How It Works

1. Ralph picks a story with `"type": "demo-review"` in prd.json.
2. Ralph checks whether `scripts/ralph/demo-reviews/[story-id]-approved.md` exists
   and contains `APPROVED` on line 1.
3. If the file is absent: Ralph outputs `BLOCKED: Demo Review Gate [id] requires human approval`
   and stops without marking the story done.
4. If the file exists with `APPROVED`: Ralph marks the story `passes: true` and continues.

## How to Approve a Demo Review Gate

1. Start the full application:
   ```
   cd backend && uv run uvicorn app.main:app --reload --port 8000
   cd frontend && npm run dev
   ```
2. Open http://localhost:5173 in your browser.
3. Work through every step in the story's checklist (see the story description in prd.json).
4. If ALL steps pass, create the approval file:
   ```
   echo "APPROVED" > scripts/ralph/demo-reviews/[story-id]-approved.md
   echo "Reviewed by: [your initials] on [YYYY-MM-DD]" >> scripts/ralph/demo-reviews/[story-id]-approved.md
   git add scripts/ralph/demo-reviews/[story-id]-approved.md
   git commit -m "chore: approve demo review gate [story-id]"
   ```
5. If ANY step fails, fix the underlying story before approving.

## Rules

- Ralph must NEVER create approval files itself.
- Approval files must be created by a human after manually testing the application.
- An approval file with any content other than `APPROVED` on line 1 is invalid.
- Do not approve a gate if any checklist step produced a blank screen, undefined text,
  generic error toast, or stuck spinner.

## Gates

| File | Story | Description |
|------|-------|-------------|
| S53-approved.md | S53 | All 5 features verified on The Time Machine |
