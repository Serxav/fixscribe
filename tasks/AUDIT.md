# Code audit — 2026-10-26

Two independent read-only audits of `main` at 173 passing tests, then cross-checked:

- **Wonder audit**: Muse Code running `muse-wonder-1.0` (read-only, `--disable-write`), 16 model
  calls, about 1.14 $. Full prompt: what to look for (stage contracts, Meta API usage, money,
  failures, security, concurrency, tests, demo risks), with a concrete failure scenario for each finding.
- **Claude Code audit**: same scope, done in parallel without seeing the Wonder report.

Wonder reviewed code mostly written by Muse Code on `muse-spark-1.3`; Claude Code reviewed both.

## Cross-checked findings

| ID | Severity | Found by | Where | Problem | Decision |
|---|---|---|---|---|---|
| C1 | HIGH | Claude | `app/schemas.py` | Strict JSON schema has no numeric bounds, but `Analysis` rejects out-of-range values (confidence 85, screw_count -1): one bad number fails the whole job. | Fix now (Claude): clamp instead of reject. |
| C2 / W8 | HIGH | both | `meta_client.py`, `analyze.py` | Video analysis shares the 120 s timeout and timeouts are retried 4×: a long video can be billed several times, then fail. | Fix now (task 009): 600 s timeout, no retry of analysis timeouts. |
| W4 | HIGH | Wonder | `meta_client.py` `SpendCounter` | A corrupt `spend.json` raises after a paid call: answer lost, spend not counted, every job fails. | Fix now (task 009): append-only `spend.log` to rebuild the total. |
| W5 | MEDIUM | Wonder | `meta_client.py` `_with_retries` | `Retry-After` is not capped: a large value can freeze a job for hours. | Fix now (task 009): cap at 30 s. |
| W7 | MEDIUM | Wonder | `meta_client.transcribe` | ASR connection errors (not timeouts) escape without retry. | Fix now (task 009). |
| C6 / W6 | MEDIUM | both | `meta_client.transcribe`, `transcribe.py` | Missing `audioDurationMs` / `startMs` crashes after a paid call; spend not counted. | Fix now (task 009). |
| C7 | LOW | Claude | `meta_client.transcribe` | 120 s timeout for up to 10 minutes of audio. | Fix now (task 009): 300 s. |
| C3 | MEDIUM | Claude | `runner.py` | A frames failure throws away a valid `guide.json`. | Next (Claude): frames optional. |
| C4 | MEDIUM | Claude | `runner.py`, `scenes.py` | An ASR failure fails the whole job although the video alone can give a guide. | Next (Claude): transcribe optional, silent fallback. |
| C5 / W12 | MEDIUM | both | `runner.py`, `routes/jobs.py` | A dead runner leaves the job "running" forever. | Next (Claude): report stale jobs as failed. |
| W9 | MEDIUM | Wonder | `jobs.py` `jobs_created_today` | One corrupt `status.json` makes every upload return 500. | Next (Claude): skip unreadable folders. |
| W11 | MEDIUM | Wonder | `routes/upload.py` | An interrupted upload leaves a "queued" job forever. | Next (Claude): mark failed and clean up. |
| W10 | MEDIUM | Wonder | `jobs.py` `update_status` | Unlocked read-modify-write between web and runner. | Next (Claude), with W11. |
| W1 | HIGH | Wonder | `routes/guides.py` | The "Open the guide" link leads to a 404 (page not built yet). | Next: guide page before SAM. |
| W2 | HIGH | Wonder | `runner.py` | SAM, inspector and Ask are not built yet. | Planned tasks (not a bug). |
| W13 | MEDIUM | Wonder | `routes/upload.py` | Job folders are never cleaned: the disk fills up. | Before deployment. |
| W3 | HIGH→LOW | Wonder | `SpendCounter` | Two jobs at once can both pass the budget check. | Accepted: at most one call over a 120 $ cap, with 25 $ reserve. |
| W14–W16 | LOW | Wonder | `guide.py`, `analyze.py`, `frames.py` | Raw `KeyError` messages on damaged files; non-atomic step images. | Later, small. |
| W17 | LOW | Wonder | `tests/test_pipeline_full.py` | The full-pipeline test fakes the whole client, so it skips the real spend code. | Later: use the real client with fake transports. |
| W18 | — | Wonder (UNSURE) | `analyze.py` | Doubt about the `text.format` nesting. | Rejected: checked in the Responses API schema docs, `text={"format": {...}}` is correct. The first real call confirms it. |
| C8 | — | Claude (UNSURE) | `analyze.py` | Structured output together with a video `input_file` is not shown in the docs. | Checked by the first real call (`scripts/run_video.py`). |

## What both audits found correct
Job-id path traversal is blocked; subprocess calls never use a shell; secrets stay out of logs;
the budget is checked before every paid call; stage files and units line up from ingest to frames.
