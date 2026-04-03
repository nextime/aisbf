# OAuth2 Device Authorization Implementation Prompt for Kilo Gateway

You are implementing OAuth2 Device Authorization Grant flow for authenticating with the Kilo Gateway API. Follow these precise instructions:

## Overview

Implement the OAuth 2.0 Device Authorization Grant (RFC 8628) to authenticate CLI/desktop applications with Kilo Gateway at `https://api.kilo.ai`.

## Required Components

### 1. Device Authorization Initiation

Create a function `initiateDeviceAuth()` that:

**Endpoint:** `POST https://api.kilo.ai/api/device-auth/codes`

**Request:**
```typescript
{
  method: "POST",
  headers: {
    "Content-Type": "application/json"
  }
}
```

**Response (200 OK):**
```typescript
{
  code: string              // User verification code (e.g., "ABC-DEF")
  verificationUrl: string   // URL for user to visit (e.g., "https://kilo.ai/device")
  expiresIn: number        // Expiration time in seconds (e.g., 600)
}
```

**Error Handling:**
- `429 Too Many Requests` → Throw: "Too many pending authorization requests. Please try again later."
- Other errors → Throw: "Failed to initiate device authorization: {status}"

### 2. Authorization Polling

Create a function `pollDeviceAuth(code: string)` that:

**Endpoint:** `GET https://api.kilo.ai/api/device-auth/codes/{code}`

**Response Status Codes:**
- `202 Accepted` → Return `{ status: "pending" }` (continue polling)
- `200 OK` → Return `{ status: "approved", token: string, userEmail: string }`
- `403 Forbidden` → Return `{ status: "denied" }` (user rejected)
- `410 Gone` → Return `{ status: "expired" }` (code expired)
- Other → Throw error

**Polling Configuration:**
- Interval: 3000ms (3 seconds)
- Max attempts: `Math.ceil((expiresIn * 1000) / 3000)`
- Stop polling when status is not "pending"

### 3. Generic Polling Utility

Create a reusable `poll<T>()` function:

```typescript
interface PollOptions<T> {
  interval: number        // Milliseconds between polls
  maxAttempts: number    // Maximum polling attempts
  pollFn: () => Promise<PollResult<T>>
}

interface PollResult<T> {
  continue: boolean      // true = keep polling, false = stop
  data?: T              // Return data on success
  error?: Error         // Error to throw on failure
}

async function poll<T>(options: PollOptions<T>): Promise<T> {
  for (let attempt = 1; attempt <= options.maxAttempts; attempt++) {
    if (attempt > 1) {
      await new Promise(resolve => setTimeout(resolve, options.interval))
    }
    
    const result = await options.pollFn()
    
    if (!result.continue) {
      if (result.error) throw result.error
      if (!result.data) throw new Error("Polling stopped without data")
      return result.data
    }
  }
  
  throw new Error("Polling timeout: Maximum attempts reached")
}
```

### 4. Complete Authentication Flow

Create `authenticateWithDeviceAuth()` that:

1. Calls `initiateDeviceAuth()` to get code and URL
2. Opens browser to `verificationUrl` (use `open` npm package, fail silently if can't open)
3. Returns an object with:
   - `url`: The verification URL
   - `instructions`: User-friendly message with code
   - `method`: "auto" (for automatic polling)
   - `callback`: Async function that polls and returns result

**Callback Implementation:**
```typescript
async callback() {
  const maxAttempts = Math.ceil((expiresIn * 1000) / 3000)
  
  const result = await poll({
    interval: 3000,
    maxAttempts,
    pollFn: async () => {
      const pollResult = await pollDeviceAuth(code)
      
      if (pollResult.status === "approved") {
        return { continue: false, data: pollResult }
      }
      if (pollResult.status === "denied") {
        return { continue: false, error: new Error("Authorization denied by user") }
      }
      if (pollResult.status === "expired") {
        return { continue: false, error: new Error("Authorization code expired") }
      }
      
      return { continue: true }
    }
  })
  
  if (!result.token || !result.userEmail) {
    return { type: "failed" }
  }
  
  return {
    type: "success",
    provider: "kilo",
    refresh: result.token,
    access: result.token,
    expires: Date.now() + (365 * 24 * 60 * 60 * 1000)  // 1 year
  }
}
```

### 5. Auth Storage Format

Store credentials in JSON file at `~/.opencode/auth.json`:

**OAuth Format (with organization):**
```json
{
  "kilo": {
    "type": "oauth",
    "access": "token_value",
    "refresh": "token_value",
    "expires": 1234567890,
    "accountId": "org_id_optional"
  }
}
```

**API Key Format (without organization):**
```json
{
  "kilo": {
    "type": "api",
    "key": "token_value"
  }
}
```

**File Permissions:** Set to `0o600` (user read/write only)

### 6. Plugin Registration

Register the auth plugin:

```typescript
export const KiloAuthPlugin = {
  auth: {
    provider: "kilo",
    
    // Loader: Extract credentials for API requests
    async loader(getAuth, providerInfo) {
      const auth = await getAuth()
      if (!auth) return {}
      
      if (auth.type === "api") {
        return { kilocodeToken: auth.key }
      }
      
      if (auth.type === "oauth") {
        const result = { kilocodeToken: auth.access }
        if (auth.accountId) {
          result.kilocodeOrganizationId = auth.accountId
        }
        return result
      }
      
      return {}
    },
    
    // Auth methods available
    methods: [{
      type: "oauth",
      label: "Kilo Gateway (Device Authorization)",
      async authorize() {
        return await authenticateWithDeviceAuth()
      }
    }]
  }
}
```

### 7. API Request Headers

For all authenticated API requests to Kilo Gateway:

```typescript
const headers = {
  "Authorization": `Bearer ${token}`,
  "Content-Type": "application/json"
}

// If organization context exists:
if (organizationId) {
  headers["X-KILOCODE-ORGANIZATIONID"] = organizationId
}
```

### 8. Profile and Organization Management

**Fetch Profile:**
```typescript
GET https://api.kilo.ai/api/profile
Headers: { Authorization: `Bearer ${token}` }

Response: {
  user: { email: string, name?: string },
  organizations?: Array<{
    id: string,
    name: string,
    role: string
  }>
}
```

**Switch Organization:**
```typescript
// Update stored auth with new accountId
await Auth.set("kilo", {
  type: "oauth",
  refresh: auth.refresh,
  access: auth.access,
  expires: auth.expires,
  accountId: newOrganizationId  // or omit for personal account
})
```

### 9. CLI Integration

**Login Command:**
```bash
kilo auth login
```

Flow:
1. Show provider selection (prioritize "kilo" as recommended)
2. Call plugin's `authorize()` method
3. Display instructions and URL to user
4. Show spinner: "Waiting for authorization..."
5. Call `callback()` to poll
6. On success: Save auth and show "Login successful"
7. On failure: Show error message

**Logout Command:**
```bash
kilo auth logout
```

Flow:
1. List all stored credentials
2. User selects provider to remove
3. Delete from auth.json
4. Clear any cached data (models, telemetry)

### 10. Error Handling

**Common Errors:**
- `401 Unauthorized` → "Invalid or expired token. Run `kilo auth login` to re-authenticate."
- `403 Forbidden` → "Access denied. Check your permissions."
- `429 Too Many Requests` → "Rate limited. Please try again later."
- Network errors → Retry with exponential backoff (optional)

**User-Facing Messages:**
- Opening browser: "Go to: {url}"
- Waiting: "Waiting for authorization..."
- Success: "Login successful"
- Denied: "Authorization denied by user"
- Expired: "Authorization code expired"
- Timeout: "Authorization timeout. Please try again."

### 11. Environment Configuration

**Configurable Base URL:**
```typescript
const KILO_API_BASE = process.env.KILO_API_URL || "https://api.kilo.ai"
```

**Constants:**
```typescript
const POLL_INTERVAL_MS = 3000
const TOKEN_EXPIRATION_MS = 365 * 24 * 60 * 60 * 1000  // 1 year
const DEFAULT_MODEL = "kilo-auto/balanced"
```

### 12. TypeScript Types

```typescript
interface DeviceAuthInitiateResponse {
  code: string
  verificationUrl: string
  expiresIn: number
}

interface DeviceAuthPollResponse {
  status: "pending" | "approved" | "denied" | "expired"
  token?: string
  userEmail?: string
}

interface Organization {
  id: string
  name: string
  role: string
}

interface KilocodeProfile {
  email: string
  name?: string
  organizations?: Organization[]
}

type AuthInfo = 
  | { type: "oauth"; access: string; refresh: string; expires: number; accountId?: string }
  | { type: "api"; key: string }
```

## Implementation Checklist

- [ ] Implement `initiateDeviceAuth()` with proper error handling
- [ ] Implement `pollDeviceAuth()` with all status codes
- [ ] Create generic `poll()` utility function
- [ ] Implement complete `authenticateWithDeviceAuth()` flow
- [ ] Create auth storage functions (get, set, remove)
- [ ] Register plugin with loader and methods
- [ ] Add Bearer token to all API requests
- [ ] Implement organization switching
- [ ] Create CLI commands (login, logout, list)
- [ ] Add proper error messages and user feedback
- [ ] Set file permissions to 0o600 for auth.json
- [ ] Handle browser opening (with silent failure)

## Testing Scenarios

1. **Happy Path:** User completes auth in browser → Token stored → API requests work
2. **User Denies:** User clicks "Deny" → Show error, don't store token
3. **Code Expires:** User doesn't complete in time → Show timeout error
4. **Network Error:** API unreachable → Show clear error message
5. **Rate Limiting:** Too many requests → Show rate limit message
6. **Organization Switch:** User switches org → accountId updated, cache cleared
7. **Token Expiry:** Expired token used → Show re-auth message

## Security Considerations

1. Store auth.json with 0o600 permissions (user-only access)
2. Never log or display full tokens
3. Use HTTPS for all API requests
4. Validate all API responses before using
5. Clear sensitive data from memory after use
6. Handle token expiration gracefully

## Dependencies

```json
{
  "open": "^9.0.0",           // Open browser
  "@clack/prompts": "^0.7.0"  // CLI prompts (optional)
}
```

## Example Usage

```typescript
// User runs: kilo auth login
// 1. System calls initiateDeviceAuth()
// 2. Opens browser to verification URL
// 3. Shows: "Go to: https://kilo.ai/device and enter code: ABC-DEF"
// 4. Polls every 3 seconds
// 5. User completes auth in browser
// 6. Poll returns token
// 7. Token saved to ~/.opencode/auth.json
// 8. Shows: "Login successful"

// Later, making API requests:
const auth = await Auth.get("kilo")
const token = auth.type === "oauth" ? auth.access : auth.key
const orgId = auth.type === "oauth" ? auth.accountId : undefined

const response = await fetch("https://api.kilo.ai/api/profile", {
  headers: {
    "Authorization": `Bearer ${token}`,
    ...(orgId && { "X-KILOCODE-ORGANIZATIONID": orgId })
  }
})
```

## Notes

- The device flow is designed for CLI/desktop apps without a web server
- Tokens are long-lived (1 year) and don't require refresh in this implementation
- The same token is used for both `access` and `refresh` fields
- Organization ID is optional and stored in `accountId` field
- All API endpoints are under `https://api.kilo.ai/api/`
- Browser opening should fail silently if not possible (headless environments)

Implement this flow exactly as specified for compatibility with Kilo Gateway.
