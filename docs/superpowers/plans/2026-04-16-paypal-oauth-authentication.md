# PayPal OAuth 2.0 Authentication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement proper PayPal OAuth 2.0 authentication to verify user PayPal account ownership before adding as payment method.

**Architecture:** Replace stub implementation with full OAuth 2.0 authorization code flow. Generate CSRF state token, redirect to PayPal for authentication, exchange authorization code for access token, fetch user profile, and store verified payment method.

**Tech Stack:** FastAPI, httpx, secrets (stdlib), base64 (stdlib), existing database layer

---

## File Structure

**Modified Files:**
- `main.py:6205-6275` - Replace PayPal OAuth endpoints with full implementation
  - `dashboard_add_payment_method_paypal_oauth()` - OAuth initiation
  - `dashboard_add_payment_method_paypal_callback()` - OAuth callback handler

**No New Files Required** - All changes are modifications to existing endpoints

---

### Task 1: Implement OAuth Initiation Endpoint

**Files:**
- Modify: `main.py:6205-6268`

- [ ] **Step 1: Replace OAuth initiation endpoint**

Replace the existing stub implementation at `main.py:6205-6268` with:

```python
@app.get("/dashboard/billing/add-method/paypal/oauth")
async def dashboard_add_payment_method_paypal_oauth(request: Request):
    """Initiate PayPal OAuth 2.0 flow"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    from aisbf.database import get_database
    db = DatabaseRegistry.get_config_database()
    user_id = request.session.get('user_id')
    
    # Get PayPal settings
    gateways = db.get_payment_gateway_settings()
    paypal_settings = gateways.get('paypal', {})
    
    # Validate PayPal is enabled
    if not paypal_settings.get('enabled'):
        logger.warning(f"PayPal OAuth attempted but PayPal is not enabled (user_id={user_id})")
        return RedirectResponse(
            url="/dashboard/billing?error=PayPal is not enabled",
            status_code=302
        )
    
    # Validate PayPal is configured
    client_id = paypal_settings.get('client_id', '').strip()
    if not client_id:
        logger.error(f"PayPal OAuth attempted but client_id not configured (user_id={user_id})")
        return RedirectResponse(
            url="/dashboard/billing?error=PayPal is not properly configured",
            status_code=302
        )
    
    # Check if user already has PayPal as payment method
    existing_methods = db.get_user_payment_methods(user_id)
    for method in existing_methods:
        if method.get('type') == 'paypal':
            logger.info(f"User {user_id} already has PayPal payment method")
            return RedirectResponse(
                url="/dashboard/billing?error=PayPal is already added as a payment method",
                status_code=302
            )
    
    # Generate CSRF state token
    import secrets
    state_token = secrets.token_hex(32)  # 64 hex characters
    request.session['paypal_oauth_state'] = state_token
    
    # Determine PayPal URLs based on sandbox mode
    is_sandbox = paypal_settings.get('sandbox', True)
    if is_sandbox:
        auth_base_url = "https://www.sandbox.paypal.com/signin/authorize"
    else:
        auth_base_url = "https://www.paypal.com/signin/authorize"
    
    # Construct callback URL
    base_url = str(request.base_url).rstrip('/')
    redirect_uri = f"{base_url}/dashboard/billing/add-method/paypal/callback"
    
    # Build PayPal authorization URL
    from urllib.parse import urlencode
    params = {
        'client_id': client_id,
        'response_type': 'code',
        'scope': 'openid profile email',
        'redirect_uri': redirect_uri,
        'state': state_token
    }
    paypal_auth_url = f"{auth_base_url}?{urlencode(params)}"
    
    logger.info(f"Initiating PayPal OAuth for user {user_id}, sandbox={is_sandbox}")
    logger.debug(f"PayPal OAuth redirect_uri: {redirect_uri}")
    
    return RedirectResponse(url=paypal_auth_url, status_code=302)
```

- [ ] **Step 2: Verify imports are present**

Check that these imports exist at the top of `main.py` (they should already be there):

```python
import secrets  # Line ~50
import httpx    # Line ~53
from urllib.parse import urljoin  # Line ~61
```

If `urlencode` is not imported, add it to the urllib.parse import line:

```python
from urllib.parse import urljoin, urlencode
```

- [ ] **Step 3: Test OAuth initiation manually**

Start the server and test:

```bash
# Start server (if not running)
python -m aisbf.main

# In browser:
# 1. Log in to dashboard
# 2. Navigate to /dashboard/billing
# 3. Click "Add Payment Method"
# 4. Click "Connect PayPal"
# 5. Should redirect to PayPal login (sandbox or live depending on config)
```

Expected: Redirect to PayPal with URL containing `client_id`, `state`, `redirect_uri` parameters

- [ ] **Step 4: Commit OAuth initiation**

```bash
git add main.py
git commit -m "feat: implement PayPal OAuth initiation endpoint"
```

---

### Task 2: Implement OAuth Callback Endpoint

**Files:**
- Modify: `main.py:6270-6275`

- [ ] **Step 1: Replace OAuth callback endpoint**

Replace the existing stub implementation at `main.py:6270-6275` with:

```python
@app.get("/dashboard/billing/add-method/paypal/callback")
async def dashboard_add_payment_method_paypal_callback(request: Request):
    """Handle PayPal OAuth 2.0 callback"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    from aisbf.database import get_database
    db = DatabaseRegistry.get_config_database()
    user_id = request.session.get('user_id')
    
    # Get query parameters
    code = request.query_params.get('code')
    state = request.query_params.get('state')
    error = request.query_params.get('error')
    
    # Handle user cancellation
    if error:
        logger.info(f"PayPal OAuth cancelled by user {user_id}: {error}")
        return RedirectResponse(
            url="/dashboard/billing?error=PayPal connection cancelled",
            status_code=302
        )
    
    # Validate state token (CSRF protection)
    session_state = request.session.get('paypal_oauth_state')
    if not session_state:
        logger.warning(f"PayPal OAuth callback with no session state (user_id={user_id})")
        return RedirectResponse(
            url="/dashboard/billing?error=Session expired, please try again",
            status_code=302
        )
    
    if state != session_state:
        logger.warning(f"PayPal OAuth state mismatch (user_id={user_id})")
        return RedirectResponse(
            url="/dashboard/billing?error=Invalid request (security check failed)",
            status_code=302
        )
    
    # Clear state token from session
    request.session.pop('paypal_oauth_state', None)
    
    # Validate authorization code
    if not code:
        logger.error(f"PayPal OAuth callback missing authorization code (user_id={user_id})")
        return RedirectResponse(
            url="/dashboard/billing?error=Invalid PayPal response",
            status_code=302
        )
    
    # Get PayPal settings
    gateways = db.get_payment_gateway_settings()
    paypal_settings = gateways.get('paypal', {})
    
    client_id = paypal_settings.get('client_id', '').strip()
    client_secret = paypal_settings.get('client_secret', '').strip()
    is_sandbox = paypal_settings.get('sandbox', True)
    
    if not client_id or not client_secret:
        logger.error(f"PayPal OAuth callback but credentials not configured (user_id={user_id})")
        return RedirectResponse(
            url="/dashboard/billing?error=PayPal is not properly configured",
            status_code=302
        )
    
    # Determine PayPal API URLs
    if is_sandbox:
        token_url = "https://api.sandbox.paypal.com/v1/oauth2/token"
        userinfo_url = "https://api.sandbox.paypal.com/v1/identity/oauth2/userinfo?schema=openid"
    else:
        token_url = "https://api.paypal.com/v1/oauth2/token"
        userinfo_url = "https://api.paypal.com/v1/identity/oauth2/userinfo?schema=openid"
    
    # Construct callback URL (must match what was sent to PayPal)
    base_url = str(request.base_url).rstrip('/')
    redirect_uri = f"{base_url}/dashboard/billing/add-method/paypal/callback"
    
    try:
        # Exchange authorization code for access token
        import base64
        auth_string = f"{client_id}:{client_secret}"
        auth_bytes = auth_string.encode('utf-8')
        auth_b64 = base64.b64encode(auth_bytes).decode('utf-8')
        
        async with httpx.AsyncClient() as client:
            # Token exchange request
            token_response = await client.post(
                token_url,
                headers={
                    'Authorization': f'Basic {auth_b64}',
                    'Content-Type': 'application/x-www-form-urlencoded'
                },
                data={
                    'grant_type': 'authorization_code',
                    'code': code,
                    'redirect_uri': redirect_uri
                },
                timeout=30.0
            )
            
            if token_response.status_code != 200:
                logger.error(f"PayPal token exchange failed (user_id={user_id}): {token_response.status_code} {token_response.text}")
                return RedirectResponse(
                    url="/dashboard/billing?error=Failed to connect PayPal account",
                    status_code=302
                )
            
            token_data = token_response.json()
            access_token = token_data.get('access_token')
            
            if not access_token:
                logger.error(f"PayPal token response missing access_token (user_id={user_id})")
                return RedirectResponse(
                    url="/dashboard/billing?error=Failed to connect PayPal account",
                    status_code=302
                )
            
            logger.info(f"PayPal access token obtained for user {user_id}")
            
            # Fetch user profile
            userinfo_response = await client.get(
                userinfo_url,
                headers={
                    'Authorization': f'Bearer {access_token}',
                    'Content-Type': 'application/json'
                },
                timeout=30.0
            )
            
            if userinfo_response.status_code != 200:
                logger.error(f"PayPal userinfo fetch failed (user_id={user_id}): {userinfo_response.status_code}")
                return RedirectResponse(
                    url="/dashboard/billing?error=Failed to retrieve PayPal account information",
                    status_code=302
                )
            
            userinfo = userinfo_response.json()
            paypal_user_id = userinfo.get('user_id')
            paypal_email = userinfo.get('email')
            paypal_name = userinfo.get('name', '')
            
            if not paypal_user_id or not paypal_email:
                logger.error(f"PayPal userinfo missing required fields (user_id={user_id})")
                return RedirectResponse(
                    url="/dashboard/billing?error=Failed to retrieve PayPal account information",
                    status_code=302
                )
            
            logger.info(f"PayPal user profile retrieved for user {user_id}: {paypal_email}")
            
            # Check for duplicate PayPal account
            existing_methods = db.get_user_payment_methods(user_id)
            for method in existing_methods:
                if method.get('type') == 'paypal':
                    metadata = method.get('metadata', {})
                    if isinstance(metadata, str):
                        import json
                        metadata = json.loads(metadata)
                    
                    existing_email = metadata.get('paypal_email')
                    existing_user_id = metadata.get('paypal_user_id')
                    
                    if existing_email == paypal_email or existing_user_id == paypal_user_id:
                        logger.info(f"Duplicate PayPal account detected for user {user_id}")
                        return RedirectResponse(
                            url="/dashboard/billing?error=This PayPal account is already connected",
                            status_code=302
                        )
            
            # Store payment method
            is_default = len(existing_methods) == 0
            metadata = {
                'paypal_user_id': paypal_user_id,
                'paypal_email': paypal_email,
                'paypal_name': paypal_name,
                'access_token': access_token,
                'sandbox': is_sandbox
            }
            
            method_id = db.add_payment_method(
                user_id=user_id,
                method_type='paypal',
                identifier=paypal_email,
                is_default=is_default,
                metadata=metadata
            )
            
            if method_id:
                logger.info(f"PayPal payment method added for user {user_id} (method_id={method_id})")
                return RedirectResponse(
                    url="/dashboard/billing?success=PayPal account connected successfully",
                    status_code=302
                )
            else:
                logger.error(f"Failed to store PayPal payment method for user {user_id}")
                return RedirectResponse(
                    url="/dashboard/billing?error=Failed to save payment method",
                    status_code=302
                )
    
    except httpx.TimeoutException as e:
        logger.error(f"PayPal OAuth timeout (user_id={user_id}): {e}")
        return RedirectResponse(
            url="/dashboard/billing?error=Connection timeout, please try again",
            status_code=302
        )
    except httpx.HTTPError as e:
        logger.error(f"PayPal OAuth HTTP error (user_id={user_id}): {e}")
        return RedirectResponse(
            url="/dashboard/billing?error=Connection error, please try again",
            status_code=302
        )
    except Exception as e:
        logger.error(f"PayPal OAuth unexpected error (user_id={user_id}): {e}", exc_info=True)
        return RedirectResponse(
            url="/dashboard/billing?error=An error occurred while connecting PayPal",
            status_code=302
        )
```

- [ ] **Step 2: Verify base64 import**

Check that `base64` is imported at the top of `main.py`. If not, add it:

```python
import base64
```

- [ ] **Step 3: Test OAuth callback manually**

Complete the OAuth flow:

```bash
# In browser:
# 1. Start OAuth flow (Task 1 Step 3)
# 2. Log in to PayPal sandbox account
# 3. Approve access
# 4. Should redirect back to /dashboard/billing with success message
# 5. Verify PayPal appears in payment methods list
```

Expected: 
- Success message displayed
- PayPal payment method visible in billing page
- Database contains PayPal email and access token in metadata

- [ ] **Step 4: Test error cases**

Test error handling:

```bash
# Test 1: User cancellation
# - Start OAuth flow
# - Click "Cancel" on PayPal login page
# - Should redirect with "PayPal connection cancelled" error

# Test 2: Duplicate account
# - Complete OAuth flow successfully
# - Try to add same PayPal account again
# - Should redirect with "already connected" error

# Test 3: Invalid state (CSRF)
# - Start OAuth flow
# - Clear browser cookies
# - Try to complete callback
# - Should redirect with "Session expired" error
```

- [ ] **Step 5: Commit OAuth callback**

```bash
git add main.py
git commit -m "feat: implement PayPal OAuth callback with token exchange and user profile fetch"
```

---

### Task 3: Verify Database Storage

**Files:**
- Verify: `aisbf/database.py:2355-2372` (no changes needed)

- [ ] **Step 1: Verify payment method storage**

Check database after successful OAuth:

```bash
# Connect to database
sqlite3 config/aisbf.db  # or your database path

# Query payment methods
SELECT id, user_id, type, identifier, is_default, metadata, created_at 
FROM payment_methods 
WHERE type = 'paypal' 
ORDER BY created_at DESC 
LIMIT 1;
```

Expected output should show:
- `type`: 'paypal'
- `identifier`: PayPal email address
- `metadata`: JSON containing `paypal_user_id`, `paypal_email`, `paypal_name`, `access_token`, `sandbox`

- [ ] **Step 2: Verify metadata structure**

Parse and verify metadata:

```bash
# In sqlite3:
SELECT json_extract(metadata, '$.paypal_email') as email,
       json_extract(metadata, '$.paypal_user_id') as user_id,
       json_extract(metadata, '$.access_token') as token_present
FROM payment_methods 
WHERE type = 'paypal';
```

Expected: All fields should be populated with actual values

- [ ] **Step 3: Document verification**

No commit needed - verification only.

---

### Task 4: Update Documentation

**Files:**
- Modify: `PAYPAL_SETUP.md:114-134`

- [ ] **Step 1: Update OAuth flow documentation**

Update the "OAuth Flow Details" section in `PAYPAL_SETUP.md` to reflect actual implementation:

```markdown
## OAuth Flow Details

### Step 1: Initiate OAuth
- User clicks "Connect PayPal" button
- AISBF generates a cryptographically secure state token (64 hex characters)
- State token is stored in user session for CSRF protection
- User is redirected to PayPal OAuth URL with:
  - `client_id`: Your PayPal app client ID
  - `response_type=code`: Authorization code flow
  - `scope=openid profile email`: Requested permissions
  - `redirect_uri`: Your callback URL
  - `state`: CSRF protection token

### Step 2: User Authorization
- User logs in to PayPal (sandbox or live)
- User reviews requested permissions
- User clicks "Agree and Continue" to authorize
- PayPal redirects back with authorization code and state token

### Step 3: Token Exchange
- AISBF validates state token matches session (CSRF check)
- AISBF exchanges authorization code for access token via PayPal API
- Uses HTTP Basic Auth with base64-encoded client credentials
- Receives access token from PayPal

### Step 4: Fetch User Profile
- AISBF calls PayPal Identity API with access token
- Retrieves user_id, email, and name from PayPal
- Validates required fields are present

### Step 5: Store Payment Method
- AISBF checks for duplicate PayPal accounts (by email and user_id)
- Stores payment method in database with:
  - Type: 'paypal'
  - Identifier: PayPal email
  - Metadata: PayPal user_id, email, name, access token, sandbox flag
- Sets as default if user's first payment method
- Redirects to billing page with success message
```

- [ ] **Step 2: Commit documentation update**

```bash
git add PAYPAL_SETUP.md
git commit -m "docs: update PayPal OAuth flow details with actual implementation"
```

---

### Task 5: End-to-End Testing

**Files:**
- Test: All endpoints

- [ ] **Step 1: Test complete OAuth flow (sandbox)**

Full integration test:

```bash
# Prerequisites:
# 1. PayPal sandbox app created at developer.paypal.com
# 2. Sandbox credentials configured in AISBF admin settings
# 3. Callback URL registered in PayPal app settings

# Test steps:
# 1. Log in to AISBF dashboard
# 2. Navigate to /dashboard/billing
# 3. Click "Add Payment Method"
# 4. Click "Connect PayPal"
# 5. Should redirect to sandbox.paypal.com
# 6. Log in with sandbox test account
# 7. Click "Agree and Continue"
# 8. Should redirect back to /dashboard/billing
# 9. Verify success message appears
# 10. Verify PayPal account in payment methods list
# 11. Verify PayPal email is displayed
```

Expected: Complete flow works without errors

- [ ] **Step 2: Test duplicate prevention**

```bash
# After successful OAuth (Step 1):
# 1. Click "Add Payment Method" again
# 2. Click "Connect PayPal"
# 3. Log in with SAME PayPal account
# 4. Complete authorization
# 5. Should redirect with error: "This PayPal account is already connected"
```

Expected: Duplicate detection works

- [ ] **Step 3: Test error handling**

```bash
# Test A: PayPal disabled
# 1. Disable PayPal in admin settings
# 2. Try to access /dashboard/billing/add-method/paypal/oauth
# 3. Should redirect with "PayPal is not enabled" error

# Test B: Missing credentials
# 1. Enable PayPal but clear client_id
# 2. Try to start OAuth flow
# 3. Should redirect with "not properly configured" error

# Test C: User cancellation
# 1. Start OAuth flow with valid config
# 2. Click "Cancel" on PayPal login
# 3. Should redirect with "connection cancelled" error

# Test D: Session expiration
# 1. Start OAuth flow
# 2. Clear browser cookies/session
# 3. Try to complete callback manually
# 4. Should redirect with "Session expired" error
```

Expected: All error cases handled gracefully

- [ ] **Step 4: Test with production credentials (if available)**

```bash
# Only if you have production PayPal app:
# 1. Switch sandbox mode to false in admin settings
# 2. Configure production client_id and client_secret
# 3. Update callback URL in production PayPal app
# 4. Repeat Step 1 test with production PayPal account
```

Expected: Works with production PayPal

- [ ] **Step 5: Verify logs**

Check application logs for proper logging:

```bash
tail -f /var/log/aisbf/app.log | grep -i paypal

# Should see logs like:
# - "Initiating PayPal OAuth for user X"
# - "PayPal access token obtained for user X"
# - "PayPal user profile retrieved for user X: email@example.com"
# - "PayPal payment method added for user X"
```

Expected: All OAuth steps are logged, no sensitive data (tokens) in logs

- [ ] **Step 6: Document test results**

No commit needed - testing complete.

---

## Self-Review Checklist

**Spec Coverage:**
- ✅ OAuth initiation endpoint - Task 1
- ✅ OAuth callback endpoint - Task 2
- ✅ State token generation and validation - Task 1, Task 2
- ✅ Token exchange with PayPal API - Task 2
- ✅ User profile fetch from Identity API - Task 2
- ✅ Duplicate PayPal account detection - Task 2
- ✅ Payment method storage - Task 2, Task 3
- ✅ Error handling (all cases) - Task 2
- ✅ Security (CSRF, credentials, validation) - Task 1, Task 2
- ✅ Documentation update - Task 4
- ✅ Testing - Task 5

**Placeholder Scan:**
- ✅ No TBD, TODO, or "implement later"
- ✅ All error handling is explicit with actual code
- ✅ All test steps have expected outcomes
- ✅ All code blocks are complete

**Type Consistency:**
- ✅ `paypal_user_id` used consistently
- ✅ `paypal_email` used consistently
- ✅ `paypal_name` used consistently
- ✅ `access_token` used consistently
- ✅ `state_token` / `session_state` used consistently

**Implementation Notes:**
- No new files created - all changes are modifications to existing `main.py`
- No database schema changes required
- No frontend changes required
- Uses existing dependencies (httpx, secrets, base64)
- Follows existing code patterns in main.py
