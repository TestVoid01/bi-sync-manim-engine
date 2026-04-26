---
name: Butter Smooth Top5 Fixes
overview: Prioritize the highest-impact architecture fixes that maximize perceived smoothness quickly while preserving source/export correctness.
todos:
  - id: p1-session-pipeline
    content: Unify all rapid interactions into one explicit session state machine
    status: in_progress
  - id: p2-commit-queue
    content: Implement deterministic batch commit queue with watcher barrier
    status: pending
  - id: p3-reload-governor
    content: Block/defer full reload during safe interaction bursts
    status: pending
  - id: p4-idempotent-persistence
    content: Expand no-op and semantic duplicate checks across all persistence paths
    status: pending
  - id: p5-ux-feedback-layer
    content: Synchronize pending/commit/synced/read-only UI feedback across panel and status
    status: pending
isProject: false
---

# Highest Impact 5 Fixes (Priority Order)

## Goal
Get the fastest possible "butter feel" in interaction without breaking source truth and export consistency.

## Priority 1 — Single Interaction Session Pipeline
- Create one canonical interaction session for property controls so rapid `+/-`, key-repeat, and slider drag all route through the same state machine.
- Current issue: multiple callbacks (`value_changed`, `value_released`, transform signals) can still overlap and race.
- Target files:
  - [engine/property_panel.py](/Users/ramkush/dev/cli/Bi-Sync%20Manim%20Engine%20copy%206%20cli%20copy%2013/engine/property_panel.py)
  - [engine/state.py](/Users/ramkush/dev/cli/Bi-Sync%20Manim%20Engine%20copy%206%20cli%20copy%2013/engine/state.py)
- Fix:
  - Introduce explicit session states: `idle -> previewing -> commit_pending -> committing -> settled`.
  - Ensure each control path only updates `preview_value`; only session flusher writes source.

## Priority 2 — Dedicated Commit Queue + Commit Barrier
- Replace ad-hoc coalescing with a dedicated commit queue and atomic flush barrier.
- Current issue: source save, watcher resume, reload decision may still interleave under burst pressure.
- Target files:
  - [engine/property_panel.py](/Users/ramkush/dev/cli/Bi-Sync%20Manim%20Engine%20copy%206%20cli%20copy%2013/engine/property_panel.py)
  - [engine/file_watcher.py](/Users/ramkush/dev/cli/Bi-Sync%20Manim%20Engine%20copy%206%20cli%20copy%2013/engine/file_watcher.py)
  - [main.py](/Users/ramkush/dev/cli/Bi-Sync%20Manim%20Engine%20copy%206%20cli%20copy%2013/main.py)
- Fix:
  - Batch final-intent commits per burst window.
  - Keep watcher paused until batch end.
  - Resume with suppression token and one deterministic post-commit sync.

## Priority 3 — Reload Governor (No Full Reload During Safe Burst)
- Add a reload governor that explicitly blocks full scene reload while interaction burst is active unless a hard safety condition triggers.
- Current issue: partial healthy/unhealthy transitions can still cause visible flicker.
- Target files:
  - [main.py](/Users/ramkush/dev/cli/Bi-Sync%20Manim%20Engine%20copy%206%20cli%20copy%2013/main.py)
  - [engine/state.py](/Users/ramkush/dev/cli/Bi-Sync%20Manim%20Engine%20copy%206%20cli%20copy%2013/engine/state.py)
  - [engine/scene_sync.py](/Users/ramkush/dev/cli/Bi-Sync%20Manim%20Engine%20copy%206%20cli%20copy%2013/engine/scene_sync.py)
- Fix:
  - Introduce `reload_guard_mode` with policies: `allow_full`, `prefer_property_only`, `block_during_burst`.
  - Defer full reload until session settles.

## Priority 4 — Idempotent Persistence (Value + Patch + Transform)
- Extend no-op checks beyond constructor property writes to transform and safe-patch paths with semantic equivalence checks.
- Current issue: reduced churn already, but redundant writes/reloads can still slip through.
- Target files:
  - [engine/ast_mutator.py](/Users/ramkush/dev/cli/Bi-Sync%20Manim%20Engine%20copy%206%20cli%20copy%2013/engine/ast_mutator.py)
- Fix:
  - Skip update when AST effective value unchanged.
  - For safe patches, detect equivalent existing call patterns (`set_color`, `set_stroke`, `set_fill`, `set_width/height`, `move_to`).
  - Add transform idempotence (`scale`, `rotate`) before save.

## Priority 5 — UX Feedback Consistency Layer
- Make interaction feel stable with explicit user feedback that matches engine state.
- Current issue: pending/read-only indicators exist but are not yet globally synchronized with commit/reload lifecycle.
- Target files:
  - [engine/property_panel.py](/Users/ramkush/dev/cli/Bi-Sync%20Manim%20Engine%20copy%206%20cli%20copy%2013/engine/property_panel.py)
  - [main.py](/Users/ramkush/dev/cli/Bi-Sync%20Manim%20Engine%20copy%206%20cli%20copy%2013/main.py)
- Fix:
  - Add global status line states: `Live Preview`, `Committing`, `Synced`, `Read-only target`.
  - Keep toolbar/progress untouched during burst unless playback state truly changes.

## Why this order
- P1/P2 remove core race conditions causing visible glitch.
- P3 removes major flicker source (reload churn).
- P4 minimizes unnecessary writes/reloads and CPU spikes.
- P5 improves perceived smoothness and trust.

## Fast Acceptance Checklist
- Rapid hold/repeat on `+/-` for 3s: no stutter, no oscillating state.
- During burst: immediate visual response; source writes coalesced.
- No cascading watcher-triggered reload loops.
- On session settle: one clean sync; export reflects final state.
- Read-only/no-persist targets never trigger write path.