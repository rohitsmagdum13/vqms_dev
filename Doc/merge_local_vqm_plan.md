# Plan: Merge local_vqm Backend Into VQMS Codebase

## Context

A separate FastAPI backend (`local_vqm`) built by a teammate handles user auth (JWT login/logout with werkzeug password hashing, token refresh, cache-based blacklist) and Salesforce vendor CRUD (GET/PUT on standard Account objects). It connects to the same RDS PostgreSQL instance but was built outside VQMS coding standards. The goal is to absorb all useful functionality into the main `vqms/` project with zero duplication, following existing patterns.

**What we're NOT merging:** `project_clean_up.py` (PyInstaller artifact cleanup), Flask-style session config, `APScheduler`, `pyfiglet` banner, sync SQLAlchemy engine, in-memory token blacklist, plain-text logging, hardcoded credentials.

---

## Decisions (Confirmed by User)

1. **Schema location:** Keep `tbl_users`/`tbl_user_roles` in `public` schema. Migration file documents them with `CREATE TABLE IF NOT EXISTS`.
2. **Password hashing:** Keep `werkzeug` — matches what was in local_vqm code and compatible with existing hashed passwords.
3. **JWT secret:** Stable value from `.env` — sessions survive restarts.
4. **Security Q&A columns:** Include in UserRecord model as they were in local_vqm's db_models.py (security_q1/a1, q2/a2, q3/a3 as optional fields).

---

## Execution Plan (15 Steps)

### Step 1: Add `werkzeug` dependency
**File:** `pyproject.toml`
- Add `werkzeug>=3.0.0` to `[project.dependencies]`
- Run `uv add werkzeug`
- Use `python-jose[cryptography]` (already in deps) for JWT — NOT PyJWT

### Step 2: Add JWT settings to AppSettings
**File:** `config/settings.py`
- Add after `correlation_id_header` field:
  ```
  jwt_secret_key: str = ""
  jwt_algorithm: str = "HS256"
  session_timeout_seconds: int = 1800      # 30 min JWT lifetime
  token_refresh_threshold_seconds: int = 300  # refresh if <5 min left
  ```

### Step 3: Update `.env.copy` with JWT vars
**File:** `.env.copy`
- Add `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `SESSION_TIMEOUT_SECONDS`, `TOKEN_REFRESH_THRESHOLD_SECONDS`

### Step 4: Add cache key builder for token blacklist
**File:** `src/cache/kv_store.py`
- New constant: `AUTH_BLACKLIST_TTL_SECONDS = 1800`
- New key builder: `auth_blacklist_key(token_jti: str) -> tuple[str, int]`
  - Key pattern: `vqms:auth:blacklist:<jti>` with 30-min TTL (matches JWT lifetime)
- New helper: `exists_key(key: str) -> bool` (check if key exists without fetching value)

### Step 5: Create auth Pydantic models
**New file:** `src/models/auth.py`
- `UserRecord` — maps to `public.tbl_users` (id, user_name, email_id, tenant, status, security_q1/a1, q2/a2, q3/a3 as optional). **Excludes password hash only.**
- `UserRoleRecord` — maps to `public.tbl_user_roles` (slno, first_name, last_name, email_id, user_name, tenant, role)
- `LoginRequest` — `username_or_email: str`, `password: str`
- `LoginResponse` — `token`, `user_name`, `email`, `role`, `tenant`, `vendor_id: str | None`
- `TokenPayload` — `sub` (user_name), `role`, `tenant`, `exp`, `iat`, `jti` (UUID for blacklist)

### Step 6: Document auth tables in migration
**New file:** `src/db/migrations/007_auth_tables_documentation.sql`
- `CREATE TABLE IF NOT EXISTS public.tbl_users (...)` — documents existing schema
- `CREATE TABLE IF NOT EXISTS public.tbl_user_roles (...)` — documents existing schema
- Safe to run (won't modify existing data)
- Comment header: "These tables already exist in RDS. This migration documents their schema."

### Step 7: Create auth service (core logic)
**New file:** `src/services/auth.py`
- `AuthenticationError(Exception)` — domain exception
- `authenticate_user(username_or_email, password, *, correlation_id) -> LoginResponse`
  - Queries `tbl_users` via `get_engine()` + raw SQL + `text()`
  - Verifies password with `werkzeug.security.check_password_hash` (wrapped in `asyncio.to_thread()` — CPU-bound)
  - Queries `tbl_user_roles` for role/tenant
  - Creates JWT, caches session in PostgreSQL cache
- `create_access_token(user_name, role, tenant) -> str`
  - Uses `jose.jwt.encode()` with settings.jwt_secret_key
  - Claims: sub, role, tenant, exp, iat, jti (UUID)
- `validate_token(token) -> TokenPayload | None`
  - Decodes JWT, checks cache blacklist via `auth_blacklist_key(jti)` + `exists_key()`
- `blacklist_token(token) -> None`
  - Extracts jti, stores in cache with `set_with_ttl(*auth_blacklist_key(jti))`
- `refresh_token_if_expiring(payload) -> str | None`
  - If `exp - now < threshold`: create new token, blacklist old jti in cache, return new token
  - Otherwise return None

### Step 8: Create auth middleware
**New dir:** `src/api/middleware/` (with `__init__.py`)
**New file:** `src/api/middleware/auth_middleware.py`
- Single `AuthMiddleware(BaseHTTPMiddleware)` class (combines user context + token refresh)
- **Skip paths:** `/health`, `/auth/login`, `/docs`, `/openapi.json`, `/webhooks/`
- On valid JWT: sets `request.state.username`, `.role`, `.tenant`, `.is_authenticated = True`
- On invalid/missing: returns 401 JSON `{"detail": "Not authenticated"}`
- After response: checks token refresh, adds `X-New-Token` header if refreshed

### Step 9: Replace fake auth route with real login/logout
**File:** `src/api/routes/auth.py` (full rewrite)
- `POST /auth/login` — validates `LoginRequest`, calls `auth_service.authenticate_user()`, returns `LoginResponse`
- `POST /auth/logout` — extracts token from header, calls `auth_service.blacklist_token()`, returns `{"message": "Logged out"}`
- Uses `@log_api_call` decorator, imports models from `src/models/auth.py`

### Step 10: Add vendor CRUD models
**File:** `src/models/vendor.py` (append to existing)
- `VendorAccountData` — Salesforce standard Account fields: Id, Name, Vendor_ID__c, Website, Vendor_Tier__c, Category__c, Payment_Terms__c, AnnualRevenue, SLA_Response_Hours__c, SLA_Resolution_Days__c, Vendor_Status__c, Onboarded_Date__c, BillingCity, BillingState, BillingCountry (all optional except Id, Name)
- `VendorUpdateRequest` — updatable fields with type validation, at least one field required (`model_validator`)
- `VendorUpdateResult` — success, vendor_id, updated_fields, message

### Step 11: Add standard Account methods to Salesforce adapter
**File:** `src/adapters/salesforce.py` (add methods to existing class)
- `get_all_active_vendors(*, correlation_id) -> list[dict]`
  - SOQL on **standard Account** (NOT Vendor_Account__c): `SELECT Id, Name, Vendor_ID__c, ... FROM Account WHERE Vendor_Status__c = 'Active'`
  - Clear docstring: "Queries STANDARD Account object (not custom Vendor_Account__c)"
- `update_vendor_account(vendor_id_field, update_data, *, correlation_id) -> dict`
  - Finds Account by Vendor_ID__c, validates fields against allowlist, updates via `sf.Account.update()`
  - Returns `{success, vendor_id, updated_fields}`

**IMPORTANT:** Existing methods query custom `Vendor_Account__c`. New methods query standard `Account`. Both coexist — different Salesforce objects.

### Step 12: Create vendor routes
**New file:** `src/api/routes/vendors.py`
- `GET /vendors` — requires authenticated user, calls adapter, returns `list[VendorAccountData]`
- `PUT /vendors/{vendor_id}` — requires authenticated user, validates `VendorUpdateRequest`, calls adapter, returns `VendorUpdateResult`
- Both use `@log_api_call`, thin handlers (no business logic in routes)

### Step 13: Wire middleware + vendors router in main.py
**File:** `main.py`
- Import `AuthMiddleware`, add via `app.add_middleware(AuthMiddleware)` after CORS
- Import `vendors_router`, add via `app.include_router(vendors_router)`

### Step 14: Write unit tests
**New files:**
- `tests/unit/test_auth_models.py` — model validation tests
- `tests/unit/test_auth_service.py` — mock DB + cache, test login/logout/refresh/blacklist
- `tests/unit/test_auth_middleware.py` — test skip paths, valid/invalid/expired tokens
- `tests/unit/test_vendor_routes.py` — mock Salesforce adapter, test GET/PUT

### Step 15: Update documentation
- `Flow.md` — Add auth flow (login -> JWT -> middleware validation)
- `README.md` — Add auth endpoints, new env vars
- `.env.copy` — Already done in Step 3

---

## Files Modified/Created Summary

| Action | File | Purpose |
|--------|------|---------|
| Modify | `pyproject.toml` | Add werkzeug |
| Modify | `config/settings.py` | Add JWT settings |
| Modify | `.env.copy` | Add JWT env vars |
| Modify | `src/cache/kv_store.py` | Add blacklist key builder + exists_key |
| **Create** | `src/models/auth.py` | Auth Pydantic models |
| **Create** | `src/db/migrations/007_auth_tables_documentation.sql` | Document existing tables |
| **Create** | `src/services/auth.py` | Auth business logic |
| **Create** | `src/api/middleware/__init__.py` | Package init |
| **Create** | `src/api/middleware/auth_middleware.py` | JWT middleware |
| Modify | `src/api/routes/auth.py` | Replace fake login with real |
| Modify | `src/models/vendor.py` | Add vendor CRUD models |
| Modify | `src/adapters/salesforce.py` | Add standard Account methods |
| **Create** | `src/api/routes/vendors.py` | Vendor CRUD endpoints |
| Modify | `main.py` | Wire middleware + router |
| **Create** | `tests/unit/test_auth_*.py` | Auth tests |
| **Create** | `tests/unit/test_vendor_routes.py` | Vendor route tests |

---

## Zero Duplication Guarantees

- **DB connection:** Uses existing `get_engine()` from `src/db/connection.py`. No new SQLAlchemy engine.
- **Logging:** Uses existing `get_logger()`, `@log_api_call`, `@log_service_call` from `src/utils/logger.py`. No new logger.
- **Cache:** Uses existing `get_pg_cache()`, `set_with_ttl()`, `get_value()`. New key builder follows existing pattern.
- **Salesforce:** Uses existing `SalesforceAdapter` singleton. New methods added to same class.
- **Settings:** Uses existing `AppSettings` via `get_settings()`. No Config class pattern.
- **Route pattern:** Thin handlers call services. No business logic in routes.

---

## Verification

After implementation:
1. `uv run ruff check .` — no lint errors
2. `uv run pytest` — all tests pass
3. Manual test: `POST /auth/login` with real credentials against RDS
4. Manual test: `GET /vendors` returns Salesforce Account data
5. Manual test: Token refresh header appears when token nears expiry
6. Manual test: `POST /auth/logout` + subsequent request returns 401
