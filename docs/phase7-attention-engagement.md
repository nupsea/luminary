# Phase 7: Attention & Engagement

Theme: Transform Luminary from a passive knowledge store into an active learning companion that helps users sustain attention, build habits, and enter flow states.

Dependency chain: S208 -> S209 -> S210 -> S211/S212/S213 (parallel) -> S214 -> S215

---

## S208: Study Streaks and XP Foundation

The backbone of the engagement system. Without this, nothing else has a reward signal to hook into.

### What to build

**Backend:**
- New models in models.py:
  - `StudyStreakModel`: user_id (default "local"), current_streak (int), longest_streak (int), last_study_date (date), streak_freezes_available (int, default 2), streak_freezes_used_this_week (int)
  - `XPLedgerModel`: id, action (enum: flashcard_review, note_created, document_read, focus_session_completed, streak_bonus), xp_amount (int), detail_json (text, nullable), created_at
  - `XPSummaryModel`: total_xp (int), level (int), xp_to_next_level (int), updated_at
- XP weighting rules (in a new `services/engagement_service.py`):
  - Flashcard review: base 10 XP. Multiply by FSRS difficulty factor: easy=1x, good=1.5x, hard=2.5x, again=0.5x. This rewards struggling through hard cards, not speed-running easy ones.
  - Note created: 15 XP. +5 bonus if note has 2+ tags (encourages organization).
  - Document section read (scroll-tracked): 5 XP per section, max 50 XP per document per day (prevents gaming).
  - Focus session completed (from S209): 20 XP per completed session.
  - Streak bonus: current_streak * 5 XP awarded once daily on first study action.
- Streak logic:
  - Any qualifying action (flashcard review, focus session) on a calendar day extends the streak.
  - If last_study_date is yesterday: increment current_streak. If today: no-op. If older: check streak_freezes_available > 0, auto-apply freeze for each missed day (max gap = freezes available), otherwise reset to 1.
  - Award 2 fresh streak freezes every Monday (reset streak_freezes_used_this_week).
  - Level formula: level = floor(sqrt(total_xp / 100)). Level 1 = 100 XP, Level 5 = 2500 XP, Level 10 = 10000 XP.
- New endpoints in a `routers/engagement.py`:
  - `GET /engagement/streak` -- returns current streak, longest streak, freezes available, today's study status
  - `GET /engagement/xp` -- returns total XP, level, XP to next level, today's XP earned
  - `GET /engagement/xp/history?days=30` -- daily XP totals for charting
- Hook XP awards into existing service methods:
  - `flashcard_service.py` review method: after persisting the review, call `engagement_service.award_xp("flashcard_review", detail={"difficulty": rating, "card_id": id})`
  - `note_service.py` create method: call `engagement_service.award_xp("note_created")`
  - Streak check: call `engagement_service.record_study_activity()` from both flashcard review and focus session completion

**Frontend:**
- Streak widget in the sidebar (below nav items, above the bottom): flame icon + streak count + "N days". Subtle -- not flashy. Gray when no streak, warm amber when active, bright orange at 7+ days.
- XP bar in the sidebar below streak: thin progress bar showing XP toward next level. "Lv.3 -- 240/400 XP". Click expands a tooltip showing today's XP breakdown.
- On the Progress tab: add a "Study Habits" section with a streak calendar heatmap (like GitHub contributions) and XP history line chart (daily XP over last 30 days).

**Tests:**
- Unit: streak increments correctly, streak freeze auto-applies, streak resets after freeze exhaustion, XP weights match difficulty
- Unit: level calculation at boundary values
- Integration: flashcard review triggers XP award and streak update

---

## S209: Focus Timer (Pomodoro)

Gives users a structured way to study. Completed sessions feed XP (S208) and generate the session data needed for analytics (S214).

### What to build

**Backend:**
- New model: `FocusSessionModel`: id, started_at, ended_at (nullable), planned_duration_minutes (int), actual_duration_seconds (int, nullable), session_type (enum: study, notes, reading, chat), completed (bool), xp_awarded (int, default 0)
- Endpoints in `routers/engagement.py`:
  - `POST /engagement/focus/start` -- body: {duration_minutes, session_type}. Creates a FocusSessionModel row. Returns session ID + started_at.
  - `POST /engagement/focus/{id}/complete` -- marks completed=true, calculates actual_duration_seconds, awards XP via engagement_service. Returns XP earned.
  - `POST /engagement/focus/{id}/cancel` -- marks completed=false, records actual_duration_seconds. No XP.
  - `GET /engagement/focus/today` -- returns today's sessions (for display and preventing double-starts).
  - `GET /engagement/focus/stats?days=7` -- total sessions, total focus minutes, completion rate, avg duration.

**Frontend:**
- `components/FocusTimer.tsx`: a compact timer component that can be embedded in Study, Notes, and Chat tabs.
  - States: idle, running, break, paused.
  - Default intervals: 25 min work / 5 min break. After 4 cycles, 15 min long break. User can adjust in a small settings popover (15/20/25/30/45/50 min presets).
  - Visual: circular progress ring (not a bar) with minutes:seconds countdown. Subtle pulse animation in last 60 seconds.
  - On completion: gentle chime sound (optional, toggle in settings), brief "Session complete! +20 XP" toast, auto-start break timer.
  - On cancel: confirm dialog "End session early? No XP will be awarded."
  - Persists timer state in sessionStorage so page refresh does not lose an active session.
- Position: floating bottom-right corner of the content area on Study/Notes/Chat tabs. Collapsible to a minimal pill showing "12:34" when user wants more screen space.
- Progress tab: add "Focus Time" chart -- daily minutes focused over last 7/30 days, completion rate percentage.

**Tests:**
- Unit: session lifecycle (start -> complete awards XP, start -> cancel does not)
- Unit: timer state transitions
- Integration: completing a focus session increments streak and awards XP

---

## S210: Micro-break Prompts and Gentle Focus Nudges

Low-effort, high-evidence interventions. Two separate triggers, one lightweight system.

### What to build

**Frontend only (no backend needed):**

- `components/AttentionNudge.tsx`: a reusable nudge overlay component.
  - Props: message (string), type ("break" | "refocus"), onDismiss, onAccept.
  - Renders as a subtle slide-in card from the bottom-right, above the focus timer. Not a modal -- does not block interaction. Auto-dismisses after 15 seconds if ignored.
  - Break prompt: "You have been studying for 20 minutes. Take a 60-second breather?" with Accept (starts a 60s countdown overlay) and Dismiss buttons.
  - Refocus prompt: "Still with us? Pick up where you left off." with a single "I'm here" dismiss button.

- `hooks/useAttentionMonitor.ts`:
  - Tracks two things: (1) continuous active time on Study/Notes/Chat tabs, (2) idle time (no mouse/keyboard events).
  - Break trigger: after 20 minutes of continuous activity (mouse moves, key presses, scrolls), show break prompt. Reset timer after break accepted or dismissed. Configurable interval stored in localStorage (default 20 min). Disabled when focus timer is in break state.
  - Refocus trigger: after 3 minutes of zero interaction events on a study-related tab, show refocus prompt. Reset on any interaction. Do not trigger if focus timer is paused (user explicitly stepped away).
  - Rate limit: max 1 nudge per 10 minutes to avoid annoyance.
  - User can disable nudges entirely via a toggle in a small preferences popover on the focus timer.

- Wire into Study.tsx, Notes.tsx, Chat.tsx: mount `useAttentionMonitor()` hook. The hook renders the nudge via a portal so it does not affect page layout.

**Tests:**
- Unit: useAttentionMonitor fires break nudge after configured interval
- Unit: idle detection fires refocus nudge after 3 min
- Unit: rate limiting prevents rapid-fire nudges

---

## S211: Focus Mode UI

A distraction-free toggle. Can be built in parallel with S212 and S213 since they are independent.

### What to build

**Frontend only:**

- `hooks/useFocusMode.ts` + Zustand store field `focusMode: boolean`:
  - Toggle via keyboard shortcut (Cmd/Ctrl+Shift+F) or a button on the focus timer.
  - When active: hide sidebar nav, hide top header/breadcrumb, expand content area to full width. Subtle transition (200ms ease). Slightly warmer background tone (e.g., shift from slate-950 to slate-900 or add a 2% warm tint).
  - Exit: press Escape, or hover left edge of screen to reveal a slim "Exit Focus Mode" strip, or click the focus timer's focus-mode toggle.
  - Persist preference in localStorage (last used state, not auto-activate).

- Modify `App.tsx` layout: conditionally hide Sidebar and GlobalLoadingBar when focusMode is true. Content area takes full width.
- Modify `FocusTimer.tsx`: add a small eye/expand icon that toggles focus mode.
- Focus mode only activates on Study, Notes, and Chat tabs. Navigating to Learning, Viz, or Progress auto-exits focus mode (those tabs need the full chrome).

**Tests:**
- Unit: focus mode toggle hides sidebar, restores on exit
- Unit: Escape key exits focus mode
- Unit: navigating to non-focus tab auto-exits

---

## S212: Session Progress Indicators

Clear "where am I" signals that reduce cognitive uncertainty. Parallel with S211 and S213.

### What to build

**Frontend:**

- **Study tab**: already shows card count during review. Enhance with a thin progress bar at the top of the review area: "Card 7 of 15" with a colored fill bar. Color shifts from blue to green as completion approaches. Show estimated time remaining based on average seconds per card in this session.

- **Notes tab**: when in a collection view, show "Note 3 of 12" navigation at the top of the note editor/reader with prev/next arrows. Not for the list view -- only when reading through notes sequentially.

- **Document reader**: add a reading progress bar at the very top of the reader pane (1px height, nearly invisible until you notice it). Shows percentage of sections scrolled through. Persist per-document reading progress in localStorage so it survives page reloads. On return, show "Continue from Section 5 of 12?" prompt.

- **Chat tab**: during an active Q&A exchange, show a subtle indicator of how many questions the user has asked in this session and how many documents are in scope. "3 questions asked -- 2 documents in scope". Informational, not gamified.

**Backend:**
- `GET /documents/{id}/reading-progress` and `PUT /documents/{id}/reading-progress` -- body: {sections_read: int[], last_section_index: int, total_sections: int}. Store in a new `ReadingProgressModel` table. This allows progress to sync if the user clears localStorage.

**Tests:**
- Unit: progress bar renders correct percentage
- Unit: reading progress persists and restores
- Integration: reading progress endpoint round-trips correctly

---

## S213: Achievement System

Milestone badges that celebrate learning progress. Builds on streak and XP data from S208. Parallel with S211/S212.

### What to build

**Backend:**
- New model: `AchievementModel`: id, key (unique string), title, description, icon_name, category (enum: streak, mastery, exploration, consistency), unlocked_at (datetime, nullable), progress_current (int), progress_target (int)
- Achievement definitions (hardcoded list in `services/engagement_service.py`):
  - **Streak category**: "First Flame" (3-day streak), "Week Warrior" (7-day), "Monthly Master" (30-day), "Century Club" (100-day)
  - **Mastery category**: "First Card" (1 flashcard reviewed), "Card Centurion" (100 cards), "Card Thousand" (1000 cards), "Bloom Climber" (review a card at each Bloom level)
  - **Exploration category**: "Bookworm" (3 documents ingested), "Library Builder" (10 documents), "Note Taker" (10 notes), "Knowledge Weaver" (50 notes with 2+ tags each), "Graph Explorer" (view Viz tab with 50+ entities)
  - **Consistency category**: "Early Bird" (study before 8am), "Night Owl" (study after 10pm), "Focus Master" (complete 10 focus sessions), "Deep Work" (complete a 50-min focus session)
- Achievement check runs after each XP award -- lightweight scan of unlocked=null achievements to see if any threshold is met. Newly unlocked achievements returned in the XP award response.
- Endpoints:
  - `GET /engagement/achievements` -- returns all achievements with unlock status and progress
  - `GET /engagement/achievements/recent` -- returns achievements unlocked in the last 7 days

**Frontend:**
- When an achievement unlocks: show a celebratory toast at the top of the screen with the achievement icon, title, and a brief description. Toast auto-dismisses after 5 seconds. No confetti, no modal -- dignified, not childish.
- Progress tab: "Achievements" section -- grid of achievement cards. Unlocked ones are full color with unlock date. Locked ones are grayed with a progress bar (e.g., "47/100 cards reviewed"). Group by category.
- Sidebar: small badge count indicator next to the Progress nav item when new achievements are unlocked (clears on visiting Progress tab).

**Tests:**
- Unit: achievement threshold detection for each category
- Unit: duplicate unlock prevention
- Integration: reviewing a flashcard that crosses the 100-card threshold unlocks "Card Centurion"

---

## S214: Attention Analytics Dashboard

Requires session data from S209 (focus timer) and S208 (XP/streaks). This is where the data turns into actionable insight.

### What to build

**Backend:**
- New service method `engagement_service.compute_attention_analytics(days=30)` that aggregates:
  - Daily focus minutes (from FocusSessionModel)
  - Session completion rate (completed vs cancelled)
  - Average session duration
  - Cards reviewed per minute (from XPLedgerModel flashcard actions + session timestamps)
  - Focus score per session: `(actual_duration / planned_duration) * completion_rate_factor`. Ranges 0-100.
  - Best time of day: bucket sessions into morning (6-12), afternoon (12-18), evening (18-24), night (0-6). Report which bucket has highest avg focus score.
  - Optimal session length: correlate planned_duration with completion rate. Report which duration has highest completion %.
- Endpoint: `GET /engagement/analytics?days=30` -- returns the full analytics payload.

**Frontend:**
- Progress tab: new "Attention Insights" section (below Study Habits from S208):
  - **Focus Score trend**: line chart of daily average focus score over 30 days.
  - **Best study time**: card showing "Your focus peaks in the morning (avg score: 82)" with an icon for the time-of-day.
  - **Optimal session length**: card showing "You complete 92% of 25-min sessions vs 64% of 50-min sessions. Consider shorter bursts."
  - **Weekly summary**: "This week: 4h 20m focused, 12 sessions completed, 87% completion rate. Up 15% from last week."
  - All insights only appear after the user has at least 5 completed focus sessions (cold-start guard). Before that, show "Complete a few more focus sessions to unlock your attention insights."

**Tests:**
- Unit: focus score calculation
- Unit: time-of-day bucketing
- Unit: cold-start guard returns empty insights below threshold
- Integration: analytics endpoint returns correct aggregation over sample data

---

## S215: Challenge-Skill Balancing (Adaptive Difficulty)

The capstone. Uses FSRS data already in the system to dynamically compose study sessions that keep users in the flow channel -- not bored, not anxious.

### What to build

**Backend:**
- New method `flashcard_service.compose_adaptive_session(document_ids, target_count=15)`:
  - Pull all due cards for the given documents.
  - Bucket by FSRS difficulty: easy (d < 3), medium (3 <= d < 6), hard (d >= 6).
  - Compose session: 60% at the user's current performance level (the bucket where their recent accuracy is 70-85%), 20% from one bucket harder, 20% review from one bucket easier.
  - If not enough cards in a bucket, fill from adjacent buckets.
  - Return ordered list of card IDs with the mix rationale.
- New method `flashcard_service.get_performance_profile(document_ids)`:
  - Calculates recent accuracy (last 50 reviews) per difficulty bucket.
  - Returns: {easy: {accuracy: 0.95, count: 20}, medium: {accuracy: 0.78, count: 45}, hard: {accuracy: 0.52, count: 12}}.
- Endpoints:
  - `POST /flashcards/adaptive-session` -- body: {document_ids, target_count}. Returns ordered card list + session metadata.
  - `GET /flashcards/performance-profile?document_ids=...` -- returns the performance profile.

**Frontend:**
- Study tab: new "Adaptive Session" button alongside existing review. Starts a review session with the composed card mix. During review, show a subtle indicator of the card's difficulty tier (color dot: green/amber/red).
- After session completion: brief summary showing accuracy by tier. "Easy: 5/5, Medium: 7/8, Hard: 1/3. Your medium-tier accuracy is strong -- next session will include more hard cards."
- Performance profile visible on Study tab as a small 3-bar chart (easy/medium/hard accuracy) so the user understands their current level.

**Tests:**
- Unit: session composition respects 60/20/20 ratio
- Unit: performance profile calculation from review history
- Unit: fallback when insufficient cards in a bucket
- Integration: adaptive session endpoint returns correctly mixed cards

---

## Implementation Notes

**New files to create:**
- `backend/app/services/engagement_service.py` -- streaks, XP, achievements, analytics
- `backend/app/routers/engagement.py` -- all engagement endpoints
- `backend/tests/test_engagement.py` -- comprehensive tests
- `frontend/src/components/FocusTimer.tsx`
- `frontend/src/components/AttentionNudge.tsx`
- `frontend/src/hooks/useAttentionMonitor.ts`
- `frontend/src/hooks/useFocusMode.ts`

**Existing files to modify:**
- `backend/app/models.py` -- add StudyStreakModel, XPLedgerModel, XPSummaryModel, FocusSessionModel, AchievementModel, ReadingProgressModel
- `backend/app/db_init.py` -- CREATE TABLE for new models
- `backend/main.py` -- register engagement router
- `backend/app/services/flashcard_service.py` -- hook XP award into review, add adaptive session methods
- `backend/app/services/note_service.py` -- hook XP award into create
- `frontend/src/App.tsx` -- focus mode layout toggle, sidebar streak/XP widget
- `frontend/src/pages/Study.tsx` -- progress indicator, adaptive session button, performance profile
- `frontend/src/pages/Notes.tsx` -- sequential note navigation
- `frontend/src/pages/Progress.tsx` -- study habits, achievements, attention insights sections
- `frontend/src/store/useAppStore.ts` -- focusMode, activeTimerSession fields

**Design principles to enforce:**
- Quality over quantity: XP must weight by difficulty. Never reward speed-running easy cards.
- Gentle over intrusive: every nudge is dismissible, rate-limited, and can be turned off.
- Local-first: all data stays in SQLite. No external analytics services.
- Insights over metrics: don't just show numbers -- tell the user what to do differently.
