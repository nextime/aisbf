# Payment Integration Deployment Checklist

Use this checklist to deploy the payment integration features to production.

## Pre-Deployment

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

Verify PayPal SDK is installed:
```bash
python -c "import paypalrestsdk; print('PayPal SDK installed')"
```

### 2. Database Migration
No schema changes required. The `payment_methods` table should already exist.

Verify table exists:
```sql
SELECT * FROM payment_methods LIMIT 1;
```

### 3. Configuration Files
Ensure all new template files are deployed:
- [ ] `templates/dashboard/paypal_connect.html`
- [ ] `templates/dashboard/add_payment_method.html` (updated)
- [ ] `templates/dashboard/user_index.html` (updated)
- [ ] `templates/dashboard/billing.html` (updated)

## Stripe Configuration

### 1. Get Stripe API Keys
1. Log in to https://dashboard.stripe.com
2. Navigate to Developers → API keys
3. Copy your Publishable key (starts with `pk_`)
4. Copy your Secret key (starts with `sk_`)

### 2. Configure in AISBF
Via Dashboard:
1. Log in as admin
2. Go to Settings → Payment Gateways
3. Enable Stripe
4. Enter Publishable Key
5. Enter Secret Key
6. Set Test Mode (true for testing, false for production)
7. Save

Via Database:
```sql
UPDATE admin_settings 
SET setting_value = json_set(
    setting_value,
    '$.stripe.enabled', true,
    '$.stripe.publishable_key', 'pk_live_xxxxx',
    '$.stripe.secret_key', 'sk_live_xxxxx',
    '$.stripe.test_mode', false
)
WHERE setting_key = 'payment_gateways';
```

### 3. Test Stripe Integration
1. Navigate to Billing → Add Payment Method
2. Click "Add Credit Card"
3. Use test card: `4242 4242 4242 4242`
4. Expiry: Any future date
5. CVC: Any 3 digits
6. Verify card is added successfully

## PayPal Configuration

### 1. Create PayPal App
1. Go to https://developer.paypal.com
2. Log in with PayPal account
3. Navigate to Dashboard → Apps & Credentials
4. Click "Create App"
5. Enter app name (e.g., "AISBF Payment")
6. Select "Merchant" type
7. Click "Create App"

### 2. Configure OAuth Settings
1. In your PayPal app settings
2. Scroll to "Return URL"
3. Add your callback URL:
   - Production: `https://yourdomain.com/dashboard/billing/add-method/paypal/callback`
   - Staging: `https://staging.yourdomain.com/dashboard/billing/add-method/paypal/callback`
4. Enable "Log In with PayPal"
5. Save changes

### 3. Get Credentials
1. Copy Client ID
2. Click "Show" to reveal Secret
3. Copy Secret

### 4. Configure in AISBF
Via Dashboard:
1. Log in as admin
2. Go to Settings → Payment Gateways
3. Enable PayPal
4. Enter Client ID
5. Enter Client Secret
6. Set Sandbox Mode (true for testing, false for production)
7. Save

Via Database:
```sql
UPDATE admin_settings 
SET setting_value = json_set(
    setting_value,
    '$.paypal.enabled', true,
    '$.paypal.client_id', 'YOUR_CLIENT_ID',
    '$.paypal.client_secret', 'YOUR_CLIENT_SECRET',
    '$.paypal.sandbox', false
)
WHERE setting_key = 'payment_gateways';
```

### 5. Test PayPal Integration
1. Navigate to Billing → Add Payment Method
2. Click "Connect PayPal"
3. Log in with PayPal account
4. Authorize AISBF
5. Verify redirect back to AISBF
6. Verify PayPal account appears in payment methods

## Cryptocurrency Configuration

### 1. Get Wallet Addresses
Obtain wallet addresses for each cryptocurrency you want to support:
- Bitcoin (BTC)
- Ethereum (ETH)
- USDT (Tether)
- USDC (USD Coin)

### 2. Configure in AISBF
Via Dashboard:
1. Log in as admin
2. Go to Settings → Payment Gateways
3. Enable desired cryptocurrencies
4. Enter wallet addresses
5. Set confirmation requirements
6. Save

Via Database:
```sql
UPDATE admin_settings 
SET setting_value = json_set(
    setting_value,
    '$.bitcoin.enabled', true,
    '$.bitcoin.address', 'bc1xxxxx',
    '$.ethereum.enabled', true,
    '$.ethereum.address', '0xxxxx'
)
WHERE setting_key = 'payment_gateways';
```

## Security Checklist

- [ ] HTTPS enabled on production domain
- [ ] SSL certificate valid and not expired
- [ ] PayPal callback URL uses HTTPS
- [ ] Stripe webhook endpoint secured (if implemented)
- [ ] PayPal webhook endpoint secured (if implemented)
- [ ] Database credentials secured
- [ ] API keys stored securely (not in code)
- [ ] Session security configured
- [ ] CSRF protection enabled
- [ ] Rate limiting configured

## Testing Checklist

### Stripe Testing
- [ ] Add test card successfully
- [ ] Card appears in payment methods
- [ ] Card marked as default (if first)
- [ ] Error handling works (use decline card: `4000 0000 0000 0002`)
- [ ] Modal closes properly
- [ ] Validation errors display correctly

### PayPal Testing
- [ ] OAuth flow initiates correctly
- [ ] Redirects to PayPal login
- [ ] Authorization completes
- [ ] Redirects back to AISBF
- [ ] PayPal account appears in payment methods
- [ ] Duplicate account detection works
- [ ] Error handling works

### User Dashboard Testing
- [ ] Subscription section appears
- [ ] Current plan displays correctly
- [ ] "Add Payment Method" button shows when no methods exist
- [ ] Button hides when payment methods exist
- [ ] Subscription status displays correctly
- [ ] Renewal date shows (if applicable)

### General Testing
- [ ] Payment methods list displays correctly
- [ ] PayPal shows email address
- [ ] Stripe shows last 4 digits
- [ ] Crypto shows wallet type
- [ ] Default badge shows correctly
- [ ] Icons display properly

## Monitoring

### Logs to Monitor
1. Payment method additions
2. OAuth flow errors
3. Stripe API errors
4. PayPal API errors
5. Database errors

### Metrics to Track
1. Payment method addition success rate
2. OAuth flow completion rate
3. Payment method types distribution
4. Error rates by payment type

## Rollback Plan

If issues occur:

1. **Disable Payment Gateways**
```sql
UPDATE admin_settings 
SET setting_value = json_set(
    setting_value,
    '$.stripe.enabled', false,
    '$.paypal.enabled', false
)
WHERE setting_key = 'payment_gateways';
```

2. **Revert Code Changes**
```bash
git revert <commit-hash>
```

3. **Restore Previous Version**
```bash
git checkout <previous-tag>
pip install -r requirements.txt
# Restart application
```

## Post-Deployment

### 1. Verify Functionality
- [ ] Test all payment methods in production
- [ ] Verify email notifications (if configured)
- [ ] Check database entries
- [ ] Monitor error logs

### 2. User Communication
- [ ] Announce new payment methods to users
- [ ] Update help documentation
- [ ] Provide support contact information

### 3. Documentation
- [ ] Update internal documentation
- [ ] Document any production-specific configurations
- [ ] Record any issues encountered

## Support

### Common Issues

**Issue**: Stripe modal doesn't open
- Check browser console for JavaScript errors
- Verify Stripe publishable key is set
- Check that Stripe.js is loading

**Issue**: PayPal OAuth fails
- Verify callback URL matches PayPal app settings
- Check that HTTPS is enabled
- Verify Client ID and Secret are correct
- Check server logs for detailed errors

**Issue**: Payment method not appearing
- Check database for entry
- Verify user_id matches
- Check is_active flag
- Review server logs

### Getting Help
- Review `PAYPAL_SETUP.md` for PayPal-specific issues
- Review `PAYMENT_INTEGRATION_SUMMARY.md` for technical details
- Check application logs
- Contact development team

## Success Criteria

Deployment is successful when:
- [ ] All payment methods can be added without errors
- [ ] Payment methods display correctly in billing page
- [ ] User dashboard shows subscription section
- [ ] No errors in application logs
- [ ] All tests pass
- [ ] Users can successfully add payment methods

## Timeline

Estimated deployment time: 2-4 hours

1. Pre-deployment checks: 30 minutes
2. Stripe configuration: 30 minutes
3. PayPal configuration: 45 minutes
4. Testing: 1 hour
5. Monitoring: 30 minutes
6. Documentation: 30 minutes

## Sign-off

- [ ] Development team approval
- [ ] QA team approval
- [ ] Security team approval
- [ ] Product owner approval

Deployed by: _______________
Date: _______________
Version: _______________
