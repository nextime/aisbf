# PayPal OAuth 2.0 Authentication Design

**Date:** 2026-04-16  
**Status:** Approved for Implementation

## Problem Statement

The current PayPal payment method implementation bypasses OAuth authentication entirely. When users click "Connect PayPal", the system adds a generic database entry without verifying PayPal account ownership. This creates security risks and will cause payment failures at checkout since no actual PayPal account is linked.

## Solution Overview

Implement proper PayPal OAuth 2.0 authorization code flow to authenticate users and obtain verified access tokens before adding PayPal as a payment method.

## Architecture

### Components

1. **OAuth Initiation Endpoint** (`/dashboard/billing/add-method/paypal/oauth`)
   - Validates PayPal gateway is enabled and configured
   - Generates CSRF state token and stores in session
   - Constructs PayPal authorization URL with required scopes
   - Redirects user to PayPal login page

2. **OAuth Callback Endpoint** (`/dashboard/billing/add-method/paypal/callback`)
   - Validates state token for CSRF protection
   - Exchanges authorization code for access token
   - Fetches user profile from PayPal Identity API
   - Checks for duplicate PayPal accounts
   - Stores payment method with OAuth data in database

3. **Session State Management**
   - Store state token in user session with timestamp
   - Validate state token on callback
   - Clear state after successful or failed authentication

## Data Flow

### Step 1: User Initiates Connection
- User clicks "Connect PayPal" button in `add_payment_method.html`
- Browser navigates to `/dashboard/billing/add-method/paypal/oauth`

### Step 2: OAuth Initiation
- Server generates random state token using `secrets.token_hex(32)` (64 hex characters)
- Stores state token in `request.session['paypal_oauth_state']`
- Retrieves PayPal settings from database via `db.get_payment_gateway_settings()`
- Constructs PayPal authorization URL:
  - **Base URL (Live):** `https://www.paypal.com/signin/authorize`
  - **Base URL (Sandbox):** `https://www.sandbox.paypal.com/signin/authorize`
  - **Parameters:**
    - `client_id`: From gateway settings
    - `response_type=code`
    - `scope=openid profile email`
    - `redirect_uri`: `{base_url}/dashboard/billing/add-method/paypal/callback`
    - `state`: Generated state token
- Redirects user to constructed PayPal URL

### Step 3: User Authorizes on PayPal
- User logs into PayPal (handled entirely by PayPal)
- User reviews and approves access to profile information
- PayPal redirects back to: `/dashboard/billing/add-method/paypal/callback?code=AUTH_CODE&state=STATE_TOKEN`
- If user cancels: `/dashboard/billing/add-method/paypal/callback?error=access_denied&state=STATE_TOKEN`

### Step 4: Token Exchange
- Server validates state token matches `request.session['paypal_oauth_state']`
- Makes POST request to PayPal token endpoint using `httpx`:
  - **URL (Live):** `https://api.paypal.com/v1/oauth2/token`
  - **URL (Sandbox):** `https://api.sandbox.paypal.com/v1/oauth2/token`
  - **Headers:**
    - `Authorization: Basic {base64(client_id:client_secret)}`
    - `Content-Type: application/x-www-form-urlencoded`
  - **Body:**
    - `grant_type=authorization_code`
    - `code={authorization_code}`
    - `redirect_uri={callback_url}`
- Receives JSON response with `access_token`, `token_type`, `expires_in`

### Step 5: Fetch User Profile
- Makes GET request to PayPal Identity API using `httpx`:
  - **URL (Live):** `https://api.paypal.com/v1/identity/oauth2/userinfo?schema=openid`
  - **URL (Sandbox):** `https://api.sandbox.paypal.com/v1/identity/oauth2/userinfo?schema=openid`
  - **Headers:**
    - `Authorization: Bearer {access_token}`
    - `Content-Type: application/json`
- Receives JSON response with:
  - `user_id`: PayPal user identifier
  - `email`: PayPal account email
  - `name`: User's full name
  - Additional profile fields (optional)

### Step 6: Store Payment Method
- Check if user already has this PayPal account:
  - Query existing payment methods via `db.get_user_payment_methods(user_id)`
  - Check for matching `paypal_email` or `paypal_user_id` in metadata
- If duplicate found, redirect to billing with error message
- Otherwise, call `db.add_payment_method()`:
  - `user_id`: From session
  - `method_type='paypal'`
  - `identifier`: PayPal email address
  - `is_default=True` if this is user's first payment method
  - `metadata`: JSON object containing:
    ```json
    {
      "paypal_user_id": "USER_ID_FROM_PAYPAL",
      "paypal_email": "user@example.com",
      "paypal_name": "John Doe",
      "access_token": "ACCESS_TOKEN_FROM_OAUTH",
      "sandbox": true/false
    }
    ```
- Clear state token from session
- Redirect to billing page with success message

## Error Handling

### Configuration Errors
- **PayPal not enabled:** Redirect to `/dashboard/billing?error=PayPal is not enabled`
- **Missing client_id or client_secret:** Redirect to `/dashboard/billing?error=PayPal is not properly configured`
- Log all configuration errors with `logger.error()` for admin debugging

### OAuth Flow Errors
- **Missing state token in session:** Redirect to `/dashboard/billing?error=Session expired, please try again`
- **State token mismatch:** Redirect to `/dashboard/billing?error=Invalid request (security check failed)`
- **User cancels on PayPal:** Callback receives `error=access_denied` → Redirect to `/dashboard/billing?error=PayPal connection cancelled`
- **Authorization code missing:** Redirect to `/dashboard/billing?error=Invalid PayPal response`

### API Errors
- **Token exchange fails (401, 403):** Log detailed error with status code and response body, redirect to `/dashboard/billing?error=Failed to connect PayPal account`
- **Token exchange network error:** Log exception, redirect to `/dashboard/billing?error=Connection error, please try again`
- **User info fetch fails:** Log error with status code, redirect to `/dashboard/billing?error=Failed to retrieve PayPal account information`
- **Rate limiting (429):** Redirect to `/dashboard/billing?error=Too many requests, please try again later`

### Business Logic Errors
- **Duplicate PayPal account detected:** Redirect to `/dashboard/billing?error=This PayPal account is already connected`
- **Database error storing payment method:** Log exception with full traceback, redirect to `/dashboard/billing?error=Failed to save payment method`

### Logging Strategy
- Log all OAuth redirects with sanitized URLs (mask state tokens in logs)
- Log all API requests with sanitized data (mask access tokens, client secrets)
- Log all API responses with sanitized data (mask tokens)
- Log all errors with full context including user_id, timestamp, and error details
- Use existing `logger` instance from `main.py`

## Security

### CSRF Protection
- Generate cryptographically secure random state token using `secrets.token_hex(32)`
- Store state token in server-side session (not cookies or URL parameters)
- Validate state token on callback before processing authorization code
- Clear state token from session after use (success or failure)
- Reject requests with missing or mismatched state tokens

### Credential Security
- Client secret never exposed to frontend code
- Access tokens stored in database metadata field (encrypted at rest if database encryption enabled)
- Token exchange uses HTTP Basic Auth with base64-encoded `client_id:client_secret`
- All PayPal API calls use HTTPS (enforced by PayPal)
- No sensitive data in URL parameters or logs

### Session Security
- Require authenticated user session via existing `require_dashboard_auth` middleware
- Validate `user_id` from session matches throughout entire flow
- Session timeout handled by existing session management
- State token tied to specific user session

### Input Validation
- Validate authorization code format before token exchange (non-empty string)
- Validate state token format (exactly 64 hex characters)
- Sanitize all user-facing error messages (no sensitive data leakage)
- Validate PayPal API responses before storing (check required fields exist)
- Validate email format from PayPal response

### Duplicate Prevention
- Check existing payment methods by PayPal email before storing
- Also check by PayPal user_id to catch cases where user changed email
- Use atomic database operations to prevent race conditions
- Return clear error message if duplicate detected

### Production Requirements
- HTTPS required for production (PayPal enforces this for OAuth)
- Callback URL must match exactly what's configured in PayPal app settings
- Sandbox mode flag determines which PayPal endpoints to use
- Different client credentials for sandbox vs production

## Implementation Details

### Modified Endpoints

**`/dashboard/billing/add-method/paypal/oauth` (GET)**
- Replace current stub implementation with full OAuth initiation
- Generate and store state token
- Construct proper PayPal authorization URL
- Redirect to PayPal

**`/dashboard/billing/add-method/paypal/callback` (GET)**
- Replace current stub implementation with full OAuth callback handling
- Validate state token
- Exchange authorization code for access token
- Fetch user profile
- Store payment method
- Handle all error cases

### Dependencies
- `httpx`: For making HTTP requests to PayPal API (already in use)
- `secrets`: For generating secure random state tokens (Python stdlib)
- `base64`: For encoding client credentials (Python stdlib)
- `json`: For parsing API responses (Python stdlib)

### Database Schema
No changes required. Existing `payment_methods` table supports this:
- `type`: 'paypal'
- `identifier`: PayPal email address
- `metadata`: JSON field stores OAuth data

### Frontend Changes
No changes required. Existing button in `add_payment_method.html` already links to correct endpoint.

## Testing Strategy

### Manual Testing
1. Enable PayPal in gateway settings with sandbox credentials
2. Navigate to "Add Payment Method" page
3. Click "Connect PayPal"
4. Verify redirect to PayPal sandbox login
5. Log in with sandbox account
6. Approve access
7. Verify redirect back to billing page
8. Verify PayPal account appears in payment methods list
9. Verify metadata contains correct OAuth data

### Error Testing
1. Test with PayPal disabled
2. Test with missing client_id
3. Test with invalid client_secret
4. Test user cancellation on PayPal
5. Test duplicate PayPal account
6. Test session expiration (clear cookies mid-flow)
7. Test state token tampering

### Security Testing
1. Verify state token validation prevents CSRF
2. Verify client secret never appears in logs or responses
3. Verify access tokens are sanitized in logs
4. Verify HTTPS enforcement in production

## Rollout Plan

1. Implement OAuth endpoints in `main.py`
2. Test in development with sandbox credentials
3. Update PAYPAL_SETUP.md with any clarifications
4. Deploy to staging environment
5. Test end-to-end flow in staging
6. Deploy to production
7. Monitor logs for errors

## Success Criteria

- Users can successfully connect PayPal accounts via OAuth
- PayPal email and user_id are stored in database
- Access tokens are stored for future payment processing
- Duplicate PayPal accounts are prevented
- All error cases are handled gracefully
- No security vulnerabilities introduced
- Existing payment methods (Stripe, crypto) continue working

## Future Enhancements

- Token refresh logic (PayPal access tokens expire)
- Webhook integration for payment notifications
- Actual payment processing using stored access tokens
- PayPal subscription management
- Refund support via PayPal API
