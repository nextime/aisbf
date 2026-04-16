# PayPal OAuth Integration Troubleshooting Guide

## Common Error: "invalid client_id or redirect_uri"

This error occurs when PayPal cannot validate your OAuth request. Here's how to fix it.

## Quick Fix Checklist

### 1. Verify PayPal App Configuration

Go to https://developer.paypal.com/dashboard/applications and check:

- [ ] App is created and active
- [ ] You're using the correct Client ID
- [ ] Sandbox mode matches your configuration
- [ ] Return URL is properly configured

### 2. Configure Return URL in PayPal App

**CRITICAL:** The Return URL in PayPal app settings must EXACTLY match your callback URL.

#### Steps:
1. Open your PayPal app in developer dashboard
2. Scroll to **"Return URL"** section
3. Add your callback URL:
   ```
   https://yourdomain.com/dashboard/billing/add-method/paypal/callback
   ```
4. Click **Save**

#### Important Notes:
- Must use **HTTPS** in production (HTTP only for localhost testing)
- URL is **case-sensitive**
- No trailing slash (unless your logs show one)
- Must match exactly what appears in server logs

### 3. Check Server Logs

The AISBF server logs the redirect_uri being used. Check logs:

```bash
# View logs
tail -f /var/log/aisbf/app.log | grep "PayPal OAuth"

# Or if using systemd
journalctl -u aisbf -f | grep "PayPal OAuth"
```

Look for lines like:
```
PayPal OAuth redirect_uri: https://yourdomain.com/dashboard/billing/add-method/paypal/callback
PayPal OAuth client_id: AYxxxxxx...
PayPal OAuth sandbox mode: True
```

### 4. Verify Configuration in AISBF

Check your PayPal settings in AISBF admin dashboard:

1. Login as admin
2. Go to Settings → Payment Gateways
3. Check PayPal section:
   - [ ] Enabled: Yes
   - [ ] Client ID: Matches PayPal app
   - [ ] Client Secret: Matches PayPal app
   - [ ] Sandbox Mode: Matches PayPal app type

## Detailed Troubleshooting

### Issue: Wrong Client ID

**Symptoms:**
- Error: "invalid client_id"
- PayPal rejects immediately

**Solution:**
1. Go to PayPal developer dashboard
2. Open your app
3. Copy the **Client ID** (starts with "A" for live, different for sandbox)
4. Update in AISBF admin settings
5. Make sure you're using:
   - **Sandbox Client ID** if sandbox mode is enabled
   - **Live Client ID** if sandbox mode is disabled

### Issue: Redirect URI Not Registered

**Symptoms:**
- Error: "invalid redirect_uri"
- PayPal shows "action is not supported"

**Solution:**
1. Check server logs for the exact redirect_uri being used
2. Go to PayPal app settings
3. Add that EXACT URL to "Return URL" field
4. Common mistakes:
   - Using http instead of https
   - Adding/missing trailing slash
   - Wrong domain name
   - Typo in path

### Issue: Sandbox vs Production Mismatch

**Symptoms:**
- Works in sandbox but not production (or vice versa)
- Client ID seems correct but still fails

**Solution:**
- Sandbox apps and Live apps are separate in PayPal
- You need TWO apps:
  - One for sandbox (for testing)
  - One for production (for live)
- Make sure AISBF sandbox mode matches the app type you're using

### Issue: HTTPS vs HTTP

**Symptoms:**
- Logs show http:// but PayPal expects https://
- Works locally but not on server

**Solution:**

If behind a reverse proxy (nginx, Apache):
1. Ensure proxy sets X-Forwarded-Proto header:
   ```nginx
   proxy_set_header X-Forwarded-Proto $scheme;
   ```

2. AISBF should detect this automatically via ProxyHeadersMiddleware

3. If still using http://, check:
   - Proxy configuration
   - SSL certificate is valid
   - AISBF is receiving correct headers

## Testing Procedure

### 1. Test with Sandbox First

1. Create a sandbox app in PayPal developer dashboard
2. Get sandbox Client ID and Secret
3. Configure AISBF with sandbox credentials
4. Set sandbox mode to `true`
5. Add sandbox return URL
6. Test the OAuth flow

### 2. Verify Each Step

**Step 1: Check Configuration**
```bash
# Check AISBF logs when clicking "Connect PayPal"
tail -f /var/log/aisbf/app.log
```

**Step 2: Verify Redirect**
- Click "Connect PayPal" in AISBF
- Check browser URL bar
- Should redirect to: `https://www.sandbox.paypal.com/signin/authorize?client_id=...`

**Step 3: Check PayPal Response**
- If you see PayPal login page: ✅ OAuth URL is correct
- If you see error page: ❌ Check client_id or redirect_uri

**Step 4: Complete Flow**
- Login with PayPal sandbox account
- Authorize the app
- Should redirect back to AISBF
- Check if PayPal account appears in payment methods

### 3. Move to Production

Once sandbox works:

1. Create a live app in PayPal dashboard
2. Get live Client ID and Secret
3. Update AISBF configuration
4. Set sandbox mode to `false`
5. Add production return URL (must use HTTPS)
6. Test with real PayPal account

## Configuration Examples

### Sandbox Configuration

```json
{
  "paypal": {
    "enabled": true,
    "client_id": "AYSq3RDGsmBLJE-otTkBtM-jBRd1TCQwFf9RGfwddNXWz0uFU9ztymylOhRS",
    "client_secret": "EGnHDxD_qRPdaLdZz8iCr8N7_MzF-YHPTkjs6NKYQvQSBngp4PTTVWkPZRbL",
    "sandbox": true
  }
}
```

Return URL in PayPal sandbox app:
```
https://yourdomain.com/dashboard/billing/add-method/paypal/callback
```

### Production Configuration

```json
{
  "paypal": {
    "enabled": true,
    "client_id": "AeHGtyuJHGFRTYUIKJHGFRTYUIKJHGFRTYUIKJHGFRTYUIKJHGFRTYUIKJH",
    "client_secret": "ELkjhgfdsaLKJHGFDSALKJHGFDSALKJHGFDSALKJHGFDSALKJHGFDSALKJ",
    "sandbox": false
  }
}
```

Return URL in PayPal live app:
```
https://yourdomain.com/dashboard/billing/add-method/paypal/callback
```

## Debug Mode

To see detailed OAuth flow information:

1. Check AISBF logs for PayPal OAuth messages
2. Use browser developer tools (Network tab) to see redirects
3. Check PayPal app dashboard for API call logs

## Still Having Issues?

### Check These:

1. **Client ID Format**
   - Sandbox: Usually starts with "AY" or "AS"
   - Live: Different format
   - Should be 80+ characters long

2. **Return URL Format**
   - Must be absolute URL (include https://)
   - Must include full path
   - No query parameters
   - No fragments (#)

3. **PayPal App Status**
   - App must be active (not disabled)
   - For live apps, may need PayPal approval

4. **Network Issues**
   - Firewall blocking PayPal API calls
   - DNS resolution issues
   - SSL certificate problems

### Get Help

If still stuck:

1. Check server logs for detailed error messages
2. Review PayPal app settings carefully
3. Test with PayPal sandbox first
4. Verify HTTPS is working correctly
5. Check that redirect_uri in logs matches PayPal settings exactly

## Quick Reference

### PayPal OAuth Endpoints

**Sandbox:**
- Authorization: `https://www.sandbox.paypal.com/signin/authorize`
- Token: `https://api.sandbox.paypal.com/v1/oauth2/token`
- User Info: `https://api.sandbox.paypal.com/v1/identity/oauth2/userinfo`

**Production:**
- Authorization: `https://www.paypal.com/signin/authorize`
- Token: `https://api.paypal.com/v1/oauth2/token`
- User Info: `https://api.paypal.com/v1/identity/oauth2/userinfo`

### Required OAuth Parameters

- `client_id`: Your PayPal app Client ID
- `response_type`: `code`
- `scope`: `openid profile email`
- `redirect_uri`: Your callback URL (URL encoded)
- `state`: Random token for CSRF protection

### AISBF Callback URL

Always:
```
https://yourdomain.com/dashboard/billing/add-method/paypal/callback
```

Replace `yourdomain.com` with your actual domain.

## Success Indicators

You'll know it's working when:

1. ✅ Clicking "Connect PayPal" redirects to PayPal login
2. ✅ After login, you see PayPal authorization screen
3. ✅ After authorizing, you're redirected back to AISBF
4. ✅ PayPal account appears in payment methods list
5. ✅ No errors in server logs

## Common Success Path

```
User clicks "Connect PayPal"
  ↓
AISBF generates state token
  ↓
AISBF redirects to PayPal with client_id and redirect_uri
  ↓
User logs into PayPal
  ↓
User authorizes AISBF
  ↓
PayPal redirects to callback URL with authorization code
  ↓
AISBF exchanges code for access token
  ↓
AISBF fetches user info from PayPal
  ↓
AISBF stores PayPal account as payment method
  ↓
User sees PayPal account in payment methods list
```

---

**Last Updated:** 2026-04-16  
**Version:** 1.0  
**For AISBF:** v0.99.26+
