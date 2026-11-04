# Muse Code tasks

FixScribe's first days were built with Muse Code, Meta's coding agent, from small written tasks.
This folder is the full record.

- `NNN-<name>.md`: one task, written from [TEMPLATE.md](TEMPLATE.md): one goal, the exact files to
  touch and not to touch, function signatures, the Meta docs pages and fields, and testable
  "done when" checks.
- `NNN-<name>.review.md`: the corrections after a review against a fixed checklist.

Muse Code ran headless in its own git worktree: it could edit files and run tests, but never
commit, push or reach the network. Each of its 16 commits says "Written by Muse Code (task <id>)".
From Oct 27 the code was written with other AI coding assistants.
