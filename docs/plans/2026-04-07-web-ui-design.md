# AutoPapers Web UI Design

## Goal

Turn the original CLI-first harness into a local front-end/back-end application with two primary surfaces:

1. A task dialog for assigning work to the LLM.
2. A hierarchical directory for browsing, previewing, and deleting papers.

## Chosen approach

The project keeps the existing Python workflow modules and adds a lightweight stdlib-based web layer:

- `web/server.py` exposes JSON APIs plus static assets.
- `web/jobs.py` runs long paper tasks in a background queue.
- `web/static/` contains a single-page UI.

This avoids introducing a heavy JS toolchain or extra backend framework while keeping the architecture decoupled.

## UI structure

- Left panel: research atlas directory with search, counts, topic nesting, and a paper preview dock.
- Right panel: task console with a conversation feed and a dispatch box.
- Delete is intentionally placed in the paper preview dock rather than directly in the list, to reduce accidental removals.

## Data flow

1. Frontend loads `/api/library`.
2. User selects a paper, frontend loads `/api/papers/{arxiv_id}`.
3. User submits a task to `/api/tasks`.
4. Backend enqueues the task and polls via `/api/tasks/{job_id}`.
5. On completion, frontend refreshes the directory and focuses the first relevant paper.

## Error handling

- Missing or invalid MiniMax keys do not prevent the UI from loading.
- Task failures surface in the conversation panel.
- Deletion returns the refreshed directory snapshot so the UI can update immediately.
