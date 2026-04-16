# PayPal Payment Integration Setup Guide

This guide explains how to configure PayPal as a payment method in AISBF.

## Overview

AISBF now supports PayPal OAuth integration, allowing users to connect their PayPal accounts as payment methods for subscriptions and plan upgrades.

## Features

- **OAuth 2.0 Integration**: Secure PayPal account connection using OAuth 2.0
- **Automatic Account Detection**: Prevents duplicate PayPal accounts
- **Sandbox Support**: Test mode for development
- **User Information**: Stores PayPal email, user ID, and name
- **Access Token Storage**: Stores access token for future API calls

## Prerequisites

1. **PayPal Developer Account**: Sign up at https://developer.paypal.com
2. **PayPal App Credentials**: Create an app to get Client ID and Secret

## Creating a PayPal App

### Step 1: Create a PayPal Developer Account

1. Go to https://developer.paypal.com
2. Sign in with your PayPal account or create a new one
3. Navigate to "Dashboard"

### Step 2: Create an App

1. Click "Apps & Credentials" in the left sidebar
2. Click "Create App" button
3. Enter an app name (e.g., "AISBF Payment Integration")
4. Select "Merchant" as the app type
5. Click "Create App"

### Step 3: Get Your Credentials

After creating the app, you'll see:
- **Client ID**: Your application's public identifier
- **Secret**: Your application's secret key (click "Show" to reveal)

### Step 4: Configure OAuth Settings

1. Scroll down to "App Settings"
2. Under "Return URL", add your callback URL:
   - For production: `https://yourdomain.com/dashboard/billing/add-method/paypal/callback`
   - For development: `http://localhost:8000/dashboard/billing/add-method/paypal/callback`
3. Click "Save"

### Step 5: Enable Required Features

1. Under "Features", ensure these are enabled:
   - **Log In with PayPal**: Required for OAuth
   - **Accept Payments**: Required for payment processing
2. Under "Advanced Features", configure:
   - **Return URL**: Your callback URL
   - **Privacy Policy URL**: Your privacy policy page
   - **User Agreement URL**: Your terms of service page

## Configuring AISBF

### Option 1: Via Dashboard (Recommended)

1. Log in to AISBF dashboard as admin
2. Navigate to "Settings" → "Payment Gateways"
3. Find the "PayPal" section
4. Configure the following:
   - **Enabled**: Toggle to enable PayPal
   - **Client ID**: Paste your PayPal app Client ID
   - **Client Secret**: Paste your PayPal app Secret
   - **Sandbox Mode**: Enable for testing, disable for production
   - **Webhook Secret**: (Optional) For webhook verification
5. Click "Save Settings"

### Option 2: Via Database

Update the `admin_settings` table:

```sql
INSERT OR REPLACE INTO admin_settings (setting_key, setting_value, updated_at)
VALUES ('payment_gateways', '{
  "paypal": {
    "enabled": true,
    "client_id": "YOUR_CLIENT_ID",
    "client_secret": "YOUR_CLIENT_SECRET",
    "webhook_secret": "",
    "sandbox": true
  },
  "stripe": {...},
  "bitcoin": {...}
}', CURRENT_TIMESTAMP);
```

## Testing the Integration

### Sandbox Testing

1. Enable sandbox mode in PayPal settings
2. Create a sandbox account at https://developer.paypal.com/dashboard/accounts
3. Use sandbox credentials to test the OAuth flow

### Test Flow

1. Navigate to "Billing" → "Add Payment Method"
2. Click "Connect PayPal"
3. You'll be redirected to PayPal login
4. Log in with your PayPal account (or sandbox account)
5. Authorize the connection
6. You'll be redirected back to AISBF
7. PayPal account should appear in your payment methods

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

## Security Considerations

1. **HTTPS Required**: PayPal OAuth requires HTTPS in production
2. **State Token**: CSRF protection using random state tokens
3. **Client Secret**: Never expose client secret in frontend code
4. **Access Token Storage**: Tokens are stored securely in database
5. **Duplicate Prevention**: System checks for existing PayPal accounts

## Troubleshooting

### Error: "PayPal is not enabled"
- Check that PayPal is enabled in payment gateway settings
- Verify admin_settings table has correct configuration

### Error: "PayPal is not properly configured"
- Ensure Client ID is set in gateway settings
- Verify Client ID is correct

### Error: "Invalid state token"
- This is a CSRF protection error
- Clear browser cookies and try again
- Check that sessions are working properly

### Error: "Failed to connect PayPal account"
- Check that Client Secret is correct
- Verify callback URL is configured in PayPal app settings
- Check server logs for detailed error messages

### Error: "This PayPal account is already connected"
- User already has this PayPal account as a payment method
- Remove existing PayPal method first, then reconnect

## API Endpoints

### Initiate OAuth
```
GET /dashboard/billing/add-method/paypal/oauth
```
Redirects to PayPal OAuth URL

### OAuth Callback
```
GET /dashboard/billing/add-method/paypal/callback?code=xxx&state=xxx
```
Handles OAuth callback and stores payment method

## Database Schema

### payment_methods Table

```sql
CREATE TABLE payment_methods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    type VARCHAR(50) NOT NULL,  -- 'paypal'
    identifier VARCHAR(255),     -- PayPal email
    is_default BOOLEAN DEFAULT 0,
    is_active BOOLEAN DEFAULT 1,
    metadata TEXT,               -- JSON with PayPal details
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
```

### Metadata Structure

```json
{
  "paypal_user_id": "PAYPAL_USER_ID",
  "paypal_email": "user@example.com",
  "paypal_name": "John Doe",
  "access_token": "ACCESS_TOKEN",
  "sandbox": true
}
```

## Production Checklist

- [ ] Create production PayPal app
- [ ] Configure production callback URL
- [ ] Set sandbox mode to `false`
- [ ] Test OAuth flow in production
- [ ] Verify HTTPS is enabled
- [ ] Configure webhook endpoints (if needed)
- [ ] Test payment processing
- [ ] Monitor error logs

## Future Enhancements

- **Webhook Integration**: Handle PayPal webhooks for payment notifications
- **Payment Processing**: Process actual payments using PayPal API
- **Subscription Management**: Create and manage PayPal subscriptions
- **Refund Support**: Handle refunds through PayPal API
- **Token Refresh**: Implement access token refresh logic

## Support

For issues or questions:
- Check server logs: `/var/log/aisbf/` or application logs
- Review PayPal Developer documentation: https://developer.paypal.com/docs/
- Contact AISBF support

## References

- [PayPal OAuth Documentation](https://developer.paypal.com/docs/log-in-with-paypal/)
- [PayPal REST API](https://developer.paypal.com/docs/api/overview/)
- [PayPal Sandbox Testing](https://developer.paypal.com/docs/api-basics/sandbox/)
