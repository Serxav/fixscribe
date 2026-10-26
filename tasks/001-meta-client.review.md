# Review 001: meta-client

Good work: retries, Retry-After, atomic spend file, lock and test isolation are all right.
Fix these 3 points, then run `.venv/bin/pytest -q`, `.venv/bin/ruff check .` and
`.venv/bin/ruff format --check .` again (`tasks/` is now formatted, it will pass).

1. `app/meta_client.py:195`, `respond` accepts `sam-3.1` and `muse-image-1.0` because it only
   checks `model not in PRICES`. The paid call runs, then `token_cost` raises `ValueError` and
   the spend is never recorded. Fix: check `"input_per_m" not in PRICES.get(model, {})` before
   calling, with the same `ValueError`. Test: `respond(model="sam-3.1", ...)` → `ValueError`
   and `fake.responses.calls == 0`.

2. `app/meta_client.py:208`, if `response.usage` is `None` the code crashes **after** a paid
   call. Fix: if `usage` is `None`, log a warning ("response without usage, spend not counted")
   and return the response without calling `spend.add`. Test: fake response with `usage=None`
   → the response is returned and `spend.json` does not exist.

3. Small cleanups: move `import fcntl` (`app/meta_client.py:112`) to the top imports, and
   delete the line `status = status` (`app/meta_client.py:230`).
