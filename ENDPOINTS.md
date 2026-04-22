# AISBF Endpoint Documentation

Generated: 2026-04-22T00:00:00+02:00

---

## Access Level Definitions

| Level | Definition |
|-------|------------|
| **Public** | No authentication required |
| **Database user** | User from the database, both role admin or user |
| **user** | User from database with role user |
| **admin** | User from database with role admin |
| **global admin** | Admin user defined in the `aisbf.json` configuration file |
| **global token** | Tokens created by the global admin to access the global API |
| **user token** | Tokens created by and belonging to a specific database user |

---

## Dashboard Endpoints (UI Access)

| Endpoint | Methods | Access Level | Description |
|----------|---------|--------------|-------------|
| `/dashboard` | GET | Database user | Main dashboard index |
| `/dashboard/login` | GET, POST | Public | Login page |
| `/dashboard/logout` | GET | Database user | Logout user |
| `/dashboard/signup` | GET, POST | Public (if enabled) | User registration |
| `/dashboard/forgot-password` | GET, POST | Public | Password reset request |
| `/dashboard/reset-password` | GET, POST | Public | Password reset form |
| `/dashboard/verify` | GET | Public | Email verification |
| `/dashboard/verify-email` | GET | Database user | Resend verification email |
| `/dashboard/change-password` | GET, POST | Database user | Change password |
| `/dashboard/change-email` | GET, POST | Database user | Change email address |
| `/dashboard/delete-account` | GET, POST | Database user | Delete user account |
| `/dashboard/profile` | GET, POST | Database user | User profile management |
| `/dashboard/settings` | GET, POST | Database user | User settings |
| `/dashboard/docs` | GET | Database user | API documentation |
| `/dashboard/license` | GET | Database user | License information |
| `/dashboard/about` | GET | Database user | About page |
| `/dashboard/extension/download` | GET | Database user | Browser extension download |

### Configuration Pages

| Endpoint | Methods | Access Level | Description |
|----------|---------|--------------|-------------|
| `/dashboard/providers` | GET, POST | Database user / Global admin | Provider configuration (auto detects context) |
| `/dashboard/rotations` | GET, POST | Database user / Global admin | Rotation configuration (auto detects context) |
| `/dashboard/autoselect` | GET, POST | Database user / Global admin | Autoselect configuration (auto detects context) |
| `/dashboard/providers/get-models` | POST | Database user / Global admin | Fetch models from provider API |
| `/dashboard/providers/{name}/upload` | POST | Database user / Global admin | Upload provider auth files |
| `/dashboard/providers/{name}/files` | GET | Database user / Global admin | List provider auth files |
| `/dashboard/providers/{name}/files/{file}/download` | GET | Database user / Global admin | Download provider auth file |
| `/dashboard/providers/{name}/auth/check` | GET | Database user / Global admin | Check provider OAuth status |
| `/dashboard/providers/upload-auth-file` | POST | Database user / Global admin | Chunked file upload for provider credentials |
| `/dashboard/providers/upload-auth-file/chunk` | POST | Database user / Global admin | Chunked file upload continuation |
| `/dashboard/user/tokens` | GET, POST, DELETE | Database user | API token management |

### Billing & Subscriptions

| Endpoint | Methods | Access Level | Description |
|----------|---------|--------------|-------------|
| `/dashboard/pricing` | GET | Public | Pricing plans page |
| `/dashboard/subscription` | GET | Database user | Current subscription status |
| `/dashboard/billing` | GET | Database user | Billing history and payment methods |
| `/dashboard/billing/add-method` | GET, POST | Database user | Add payment method |
| `/dashboard/billing/add-method/paypal/oauth` | GET, POST | Database user | PayPal OAuth initiation |
| `/dashboard/billing/add-method/paypal/callback` | GET, POST | Database user | PayPal OAuth callback |
| `/dashboard/billing/payment-methods/{id}/set-default` | POST | Database user | Set default payment method |

### Database Admin (Role=admin)

| Endpoint | Methods | Access Level | Description |
|----------|---------|--------------|-------------|
| `/dashboard/users` | GET, POST | admin | User management |
| `/dashboard/users/add` | POST | admin | Create new user |
| `/dashboard/users/{id}/edit` | POST | admin | Edit user |
| `/dashboard/users/{id}/delete` | POST | admin | Delete user |
| `/dashboard/users/{id}/toggle` | POST | admin | Toggle user active status |
| `/dashboard/users/{id}/tier` | POST | admin | Update user tier |
| `/dashboard/users/bulk` | POST | admin | Bulk user operations |
| `/dashboard/analytics` | GET | admin | Analytics dashboard |

### Global Admin (aisbf.json defined)

| Endpoint | Methods | Access Level | Description |
|----------|---------|--------------|-------------|
| `/dashboard/admin/tiers` | GET | global admin | Pricing tiers management |
| `/dashboard/admin/tiers/create` | GET | global admin | Create new tier |
| `/dashboard/admin/tiers/edit/{id}` | GET | global admin | Edit existing tier |
| `/dashboard/admin/tiers/save` | POST | global admin | Save tier changes |
| `/dashboard/admin/payment-settings` | GET | global admin | Payment system configuration |
| `/dashboard/response-cache/stats` | GET | global admin | Cache statistics |
| `/dashboard/response-cache/clear` | POST | global admin | Clear cache |
| `/dashboard/rate-limits` | GET | global admin | Rate limits dashboard |
| `/dashboard/rate-limits/data` | GET | global admin | Rate limits data API |
| `/dashboard/rate-limits/{provider}/reset` | POST | global admin | Reset provider rate limits |
| `/dashboard/condensation` | GET, POST | global admin | Condensation settings |
| `/dashboard/restart` | POST | global admin | Restart server |
| `/dashboard/test-smtp` | POST | global admin | Test email configuration |

### OAuth2 Authentication

| Endpoint | Methods | Access Level | Description |
|----------|---------|--------------|-------------|
| `/dashboard/claude/auth/start` | POST | Database user / Global admin | Start Claude OAuth flow |
| `/dashboard/claude/auth/complete` | POST | Database user / Global admin | Complete Claude OAuth flow |
| `/dashboard/claude/auth/callback-status` | GET | Database user / Global admin | Check OAuth callback status |
| `/dashboard/kilo/auth/start` | POST | Database user / Global admin | Start Kilo OAuth flow |
| `/dashboard/kilo/auth/poll` | POST | Database user / Global admin | Poll Kilo OAuth status |
| `/dashboard/kilo/auth/status` | POST | Database user / Global admin | Kilo auth status |
| `/dashboard/qwen/auth/start` | POST | Database user / Global admin | Start Qwen OAuth flow |
| `/dashboard/qwen/auth/poll` | POST | Database user / Global admin | Poll Qwen OAuth status |
| `/dashboard/qwen/auth/status` | POST | Database user / Global admin | Qwen auth status |
| `/dashboard/codex/auth/start` | POST | Database user / Global admin | Start Codex OAuth flow |
| `/dashboard/codex/auth/poll` | POST | Database user / Global admin | Poll Codex OAuth status |
| `/dashboard/codex/auth/status` | POST | Database user / Global admin | Codex auth status |
| `/dashboard/codex/auth/logout` | POST | Database user / Global admin | Codex auth logout |
| `/dashboard/kilo/auth/logout` | POST | Database user / Global admin | Kilo auth logout |
| `/dashboard/qwen/auth/logout` | POST | Database user / Global admin | Qwen auth logout |

---

## API Endpoints (Programmatic Access)

### Public API

| Endpoint | Methods | Access Level | Description |
|----------|---------|--------------|-------------|
| `/api/v1/models` | GET | Public | List available models |
| `/api/webhooks/stripe` | POST | Public (signed) | Stripe webhook endpoint |
| `/api/webhooks/paypal` | POST | Public (signed) | PayPal webhook endpoint |

### Global Token / Global Admin

| Endpoint | Methods | Access Level | Description |
|----------|---------|--------------|-------------|
| `/api/v1/chat/completions` | POST | global token | OpenAI-compatible chat completions (global) |
| `/api/v1/completions` | POST | global token | Legacy completions endpoint (global) |
| `/api/v1/embeddings` | POST | global token | Embeddings generation (global) |
| `/api/v1/images/generations` | POST | global token | Image generation (global) |
| `/api/v1/audio/transcriptions` | POST | global token | Audio transcription (global) |
| `/api/v1/audio/speech` | POST | global token | Text-to-speech (global) |
| `/api/chat/completions` | POST | global token | Alias for `/api/v1/chat/completions` (global) |
| `/api/embeddings` | POST | global token | Alias for `/api/v1/embeddings` (global) |
| `/api/images/generations` | POST | global token | Alias for `/api/v1/images/generations` (global) |
| `/api/audio/transcriptions` | POST | global token | Alias for `/api/v1/audio/transcriptions` (global) |
| `/api/audio/speech` | POST | global token | Alias for `/api/v1/audio/speech` (global) |
| `/api/providers` | GET | global token | List global providers |
| `/api/{provider_id}/models` | GET | global token | List models for specific global provider |
| `/api/{provider_id}/chat/completions` | POST | global token | Direct global provider access |
| `/api/rotations` | GET | global token | List global rotations |
| `/api/rotations/models` | GET | global token | List global rotation models |
| `/api/rotations/chat/completions` | POST | global token | Global rotation completions |
| `/api/autoselect` | GET | global token | List global autoselect rules |
| `/api/autoselect/models` | GET | global token | List global autoselect models |
| `/api/autoselect/chat/completions` | POST | global token | Global autoselect completions |

### User Token / Database User

| Endpoint | Methods | Access Level | Description |
|----------|---------|--------------|-------------|
| `/api/u/{username}/models` | GET | user token | List user's available models |
| `/api/u/{username}/providers` | GET | user token | List user's providers |
| `/api/u/{username}/rotations` | GET | user token | List user's rotations |
| `/api/u/{username}/rotations/models` | GET | user token | List user's rotation models |
| `/api/u/{username}/autoselects` | GET | user token | List user's autoselect rules |
| `/api/u/{username}/autoselects/models` | GET | user token | List user's autoselect models |
| `/api/u/{username}/chat/completions` | POST | user token | User-specific completions |
| `/api/u/{username}/{config_type}/models` | GET | user token | User-specific config models |

### Billing API

| Endpoint | Methods | Access Level | Description |
|----------|---------|--------------|-------------|
| `/api/subscriptions` | POST | Database user | Create subscription |
| `/api/subscriptions/status` | GET | Database user | Subscription status |
| `/api/subscriptions/upgrade` | POST | Database user | Upgrade subscription |
| `/api/subscriptions/downgrade` | POST | Database user | Downgrade subscription |
| `/api/subscriptions/cancel` | POST | Database user | Cancel subscription |
| `/api/payment-methods` | GET | Database user | List payment methods |
| `/api/payment-methods/stripe` | POST | Database user | Add Stripe payment method |
| `/api/payment-methods/paypal/initiate` | POST | Database user | Initiate PayPal payment method |
| `/api/payment-methods/paypal/complete` | POST | Database user | Complete PayPal payment method |
| `/api/payment-methods/crypto` | POST | Database user | Add crypto payment method |

### Global Admin API

| Endpoint | Methods | Access Level | Description |
|----------|---------|--------------|-------------|
| `/api/admin/tiers` | GET, POST | global admin | Pricing tiers management |
| `/api/admin/tiers/{id}` | GET, PUT, DELETE | global admin | Tier CRUD operations |
| `/api/admin/config/consolidation` | GET, POST | global admin | Consolidation configuration |
| `/api/admin/config/email` | GET, POST | global admin | Email configuration |
| `/api/admin/config/price-sources` | GET, POST | global admin | Price sources configuration |
| `/api/admin/settings/currency` | GET, POST | global admin | Currency settings |
| `/api/admin/settings/encryption-key` | GET, POST | global admin | Encryption key settings |
| `/api/admin/settings/payment-gateways` | GET, POST | global admin | Payment gateways settings |
| `/api/admin/scheduler/status` | GET | global admin | Scheduler status |
| `/api/admin/scheduler/run-job` | POST | global admin | Run scheduler job manually |
| `/api/admin/payment-system/config` | GET | global admin | Payment system configuration |
| `/api/admin/payment-system/config/price-sources` | PUT | global admin | Update price sources configuration |
| `/api/admin/payment-system/config/consolidation` | PUT | global admin | Update consolidation configuration |
| `/api/admin/payment-system/config/email` | PUT | global admin | Update email configuration |
| `/api/admin/payment-system/config/blockchain` | PUT | global admin | Update blockchain configuration |
| `/api/admin/payment-system/status` | GET | global admin | Payment system status |
| `/api/admin/crypto/prices` | GET | global admin | Crypto prices |
| `/api/admin/crypto/btc-prices` | GET | global admin | BTC prices |
| `/api/users/search` | GET | admin | Search users |

### Legacy/Deprecated Endpoints

| Endpoint | Methods | Access Level | Description |
|----------|---------|--------------|-------------|
| `/api/autoselections/models` | GET | global token | Deprecated alias for `/api/autoselect/models` |
| `/api/u/{username}/autoselections/models` | GET | user token | Deprecated alias for `/api/u/{username}/autoselects/models` |
| `/api/proxy/{content_id}` | GET | Database user | Content proxy endpoint |

---

## Special Auto-Context Endpoints

Endpoints marked with `Database user / Global admin` automatically detect context:
- If accessed by `global admin` → operates on global JSON configuration
- If accessed by `Database user` → operates on user-specific database configuration
- No separate endpoints needed for global vs user configuration

All endpoints enforce proper authentication and authorization checks before processing requests.
