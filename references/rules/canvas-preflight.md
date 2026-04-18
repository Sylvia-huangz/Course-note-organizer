# Canvas Preflight Rules

Check [`capability-boundaries.md`](./capability-boundaries.md), [`error-codes.md`](./error-codes.md), and [`agent-response-templates.md`](./agent-response-templates.md) before attempting live Canvas access.

Run Canvas preflight before intake only when one of these is available:

- a Canvas course or lesson link
- copied course-page text
- exported HTML or JSON from Canvas pages
- screenshots from Canvas pages
- a usable logged-in browser session

## Read Order

Inspect these sources in order:

1. course home page or module overview
2. announcements
3. assignments

## Extract Only Actionable Course Context

Capture:

- upcoming exams or quizzes
- near-term assignments and due dates
- instructor emphasis that changes how the lesson should be read
- week or module labels that tie course expectations to the current lesson

Do not pull unrelated course clutter into the note.

## Matching Rule

Canvas context may change note emphasis only when both conditions are satisfied:

1. the assignment or announcement topic matches the lecture topic
2. the week, module, release timing, or explicit instructor wording confirms the match

If only the first condition is true, add a short `Course Context (Canvas)` note near the start of the document and leave the body structure unchanged.

## Failure and Downgrade

If Canvas access fails, the page requires login you cannot complete, or the extracted data is too weak to trust:

- state the limitation clearly
- continue the note workflow with the available lecture materials
- do not block the task

If the failure is effectively a `401`, login redirect, or missing browser session:

- do not ask for credentials
- ask the user to use their own logged-in browser session or provide exported page artifacts
- continue without Canvas weighting when the rest of the lesson material is sufficient
