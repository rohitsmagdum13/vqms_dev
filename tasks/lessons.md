# VQMS Lessons Learned

## 2026-04-06 — MSAL validation fails with placeholder tenant ID in tests
**Mistake:** After rewriting `graph_api.py` to use real MSAL authentication, email intake tests failed because `fetch_email_by_resource()` tried to create a real MSAL app with the placeholder `<your-azure-tenant-id>` from `.env.copy`, causing a ValueError from MSAL.
**Correction:** Mock `fetch_email_by_resource` at the service level (`@patch("src.services.email_intake.fetch_email_by_resource")`) instead of trying to mock MSAL internals. Service-level tests should mock their dependencies, not the dependencies' internals.
**Rule:** When testing services that call external APIs (Graph API, Salesforce, etc.), always mock the adapter function at the import point in the service module, not the adapter's internal implementation.

## 2026-04-06 — Keyword args vs positional args in mock assertions
**Mistake:** Test `test_publishes_email_ingested_event` asserted `call_args.args[0] == "EmailIngested"` but the service calls `publish_event(detail_type="EmailIngested", ...)` using keyword arguments, so `call_args.args` was empty.
**Correction:** Check both `call_args.kwargs.get("detail_type")` and `call_args.args[0]` to handle either calling convention.
**Rule:** When asserting on mock call_args, always check kwargs first (or use `assert_called_once_with()`) since Python functions can be called with either positional or keyword arguments.

## 2026-04-06 — Enum serialization: `.value` vs string comparison
**Mistake:** Compared `QuerySource.PORTAL` directly to string `"PORTAL"` which failed because Pydantic str enums serialize as lowercase (`"portal"`).
**Correction:** Use `.upper()` when comparing enum values to uppercase strings, or compare against the enum member directly.
**Rule:** Always use `.upper()` or compare against enum members when checking enum values — don't assume case.

## 2026-04-07 — Python LogRecord reserves "filename" attribute
**Mistake:** Used `"filename"` as a key in logger `extra={"filename": attachment.file_name}` dict. Python's `logging.LogRecord` has a built-in `filename` attribute and raises `KeyError: "Attempt to overwrite 'filename' in LogRecord"`.
**Correction:** Renamed the key to `"attachment_name"` in all logger extra dicts. Data dictionaries (S3 JSON, SQL bind params) can still use `"filename"` as a key — the restriction is only on logger extra dicts.
**Rule:** Never use Python LogRecord reserved attribute names (filename, lineno, funcName, module, name, etc.) as keys in logger `extra={}` dicts.

## 2026-04-07 — Edit replace_all changes unintended occurrences
**Mistake:** Used `replace_all=True` with `old_string='"filename"'` to fix logger extra dicts, but it also changed `"filename"` in non-logger contexts (S3 JSON dict keys and SQL bind parameters) where it was correct.
**Correction:** Had to manually revert the S3 JSON dict and SQL bind parameter keys back to `"filename"`. Should have used targeted edits on specific lines instead of `replace_all`.
**Rule:** When using Edit with `replace_all=True`, verify the string only appears in the intended contexts. For strings that appear in multiple contexts with different meanings, use targeted edits instead.

## 2026-04-07 — paramiko 4.0.0 breaks sshtunnel (DSSKey removed)
**Mistake:** `sshtunnel 0.4.0` references `paramiko.DSSKey` which was removed in `paramiko 4.0.0`, causing `AttributeError: module 'paramiko' has no attribute 'DSSKey'` when opening SSH tunnels.
**Correction:** Pinned `paramiko<4.0.0` in `pyproject.toml`. Paramiko 3.5.1 still has `DSSKey`.
**Rule:** When using `sshtunnel`, always pin `paramiko<4.0.0` until `sshtunnel` releases a version compatible with paramiko 4.x.
