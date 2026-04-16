# Quick Start Guide - Payment Integration

This is a quick reference for setting up and using the payment integration features.

## 🚀 Quick Setup (5 Minutes)

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Enable Payment Methods

**Via Admin Dashboard:**
1. Login as admin → Settings → Payment Gateways
2. Enable desired payment methods
3. Enter credentials
4. Save

**Via Database (Quick):**
```sql
-- Enable Stripe
UPDATE admin_settings 
SET setting_value = json_set(setting_value, '$.stripe.enabled', true)
WHERE setting_key = 'payment_gateways';

-- Enable PayPal
UPDATE admin_settings 
SET setting_value = json_set(setting_value, '$.paypal.enabled', true)
WHERE setting_key = 'payment_gateways';
```

### 3. Test
- Navigate to `/dashboard/billing/add-method`
- Try adding each payment method
- Verify they appear in `/dashboard/billing`

## 🔑 Quick Configuration

### Stripe (2 minutes)
```json
{
  "stripe": {
    "enabled": true,
    "publishable_key": "pk_test_...",
    "secret_key": "sk_test_...",
    "test_mode": true
  }
}
```

Get keys: https://dashboard.stripe.com/apikeys

### PayPal (5 minutes)
```json
{
  "paypal": {
    "enabled": true,
    "client_id": "YOUR_CLIENT_ID",
    "client_secret": "YOUR_SECRET",
    "sandbox": true
  }
}
```

Setup:
1. Create app: https://developer.paypal.com
2. Add callback URL: `https://yourdomain.com/dashboard/billing/add-method/paypal/callback`
3. Copy Client ID and Secret

### Cryptocurrency (1 minute)
```json
{
  "bitcoin": {
    "enabled": true,
    "address": "bc1..."
  },
  "ethereum": {
    "enabled": true,
    "address": "0x..."
  }
}
```

## 📍 Key Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/dashboard/billing` | GET | View payment methods |
| `/dashboard/billing/add-method` | GET | Add payment method page |
| `/dashboard/billing/add-method/stripe` | POST | Add Stripe card |
| `/dashboard/billing/add-method/paypal/oauth` | GET | Start PayPal OAuth |
| `/dashboard/billing/add-method/paypal/callback` | GET | PayPal OAuth callback |
| `/dashboard/subscription` | GET | Subscription management |
| `/dashboard/user` | GET | User dashboard with subscription |

## 🧪 Testing

### Stripe Test Cards
```
Success:     4242 4242 4242 4242
Decline:     4000 0000 0000 0002
Auth needed: 4000 0025 0000 3155
```
Expiry: Any future date | CVC: Any 3 digits

### PayPal Sandbox
1. Enable sandbox mode in settings
2. Create test account: https://developer.paypal.com/dashboard/accounts
3. Use test credentials

## 🔍 Troubleshooting

### Stripe Modal Not Opening
```javascript
// Check browser console for errors
// Verify publishable key is set
console.log('Stripe key:', '{{ stripe_publishable_key }}');
```

### PayPal OAuth Fails
```bash
# Check logs
tail -f /var/log/aisbf/app.log | grep -i paypal

# Verify callback URL
echo "https://yourdomain.com/dashboard/billing/add-method/paypal/callback"

# Test OAuth endpoint
curl -I https://yourdomain.com/dashboard/billing/add-method/paypal/oauth
```

### Payment Method Not Appearing
```sql
-- Check database
SELECT * FROM payment_methods WHERE user_id = YOUR_USER_ID;

-- Check if active
SELECT id, type, identifier, is_active FROM payment_methods;
```

## 📊 Database Quick Reference

### View Payment Methods
```sql
SELECT 
    pm.id,
    u.email as user_email,
    pm.type,
    pm.identifier,
    pm.is_default,
    pm.is_active,
    pm.created_at
FROM payment_methods pm
JOIN users u ON pm.user_id = u.id
ORDER BY pm.created_at DESC
LIMIT 10;
```

### Count by Type
```sql
SELECT type, COUNT(*) as count
FROM payment_methods
WHERE is_active = 1
GROUP BY type;
```

### Recent Additions
```sql
SELECT type, identifier, created_at
FROM payment_methods
WHERE created_at > datetime('now', '-7 days')
ORDER BY created_at DESC;
```

## 🎯 Common Tasks

### Add Test Payment Method
```bash
# Stripe
curl -X POST https://yourdomain.com/dashboard/billing/add-method/stripe \
  -H "Content-Type: application/json" \
  -d '{"payment_method_id": "pm_test_..."}'

# Crypto
curl -X POST https://yourdomain.com/dashboard/billing/add-method \
  -H "Content-Type: application/json" \
  -d '{"type": "bitcoin", "action": "set_default"}'
```

### Check Configuration
```sql
SELECT setting_value 
FROM admin_settings 
WHERE setting_key = 'payment_gateways';
```

### Enable All Payment Methods
```sql
UPDATE admin_settings 
SET setting_value = json_set(
    setting_value,
    '$.stripe.enabled', true,
    '$.paypal.enabled', true,
    '$.bitcoin.enabled', true,
    '$.ethereum.enabled', true
)
WHERE setting_key = 'payment_gateways';
```

## 🔐 Security Checklist

Quick security verification:
- [ ] HTTPS enabled
- [ ] SSL certificate valid
- [ ] API keys not in code
- [ ] Session security configured
- [ ] CSRF protection enabled
- [ ] PayPal callback uses HTTPS
- [ ] Database credentials secured

## 📱 User Flow

### Adding Stripe Card
1. User: Click "Add Credit Card"
2. System: Show modal with Stripe Elements
3. User: Enter card details
4. Stripe: Validate and create payment method
5. System: Store payment method ID
6. User: See card in payment methods list

### Adding PayPal
1. User: Click "Connect PayPal"
2. System: Redirect to PayPal OAuth
3. User: Login and authorize
4. PayPal: Redirect back with code
5. System: Exchange code for token
6. System: Fetch user info
7. System: Store PayPal account
8. User: See PayPal in payment methods list

## 📚 Documentation Files

| File | Purpose |
|------|---------|
| `QUICK_START_PAYMENT.md` | This file - quick reference |
| `PAYPAL_SETUP.md` | Detailed PayPal setup guide |
| `PAYMENT_INTEGRATION_SUMMARY.md` | Technical overview |
| `DEPLOYMENT_CHECKLIST.md` | Production deployment guide |

## 🆘 Getting Help

1. **Check logs first:**
   ```bash
   tail -f /var/log/aisbf/app.log
   ```

2. **Review documentation:**
   - PayPal issues → `PAYPAL_SETUP.md`
   - Technical details → `PAYMENT_INTEGRATION_SUMMARY.md`
   - Deployment → `DEPLOYMENT_CHECKLIST.md`

3. **Common log searches:**
   ```bash
   # Payment errors
   grep -i "payment\|stripe\|paypal" /var/log/aisbf/app.log
   
   # OAuth errors
   grep -i "oauth\|authorization" /var/log/aisbf/app.log
   
   # Database errors
   grep -i "database\|sql" /var/log/aisbf/app.log
   ```

## ⚡ Performance Tips

- Stripe Elements loads asynchronously
- PayPal OAuth requires external redirect (slower)
- Cache payment gateway settings
- Index payment_methods table on user_id
- Monitor API response times

## 🎨 UI Customization

### Stripe Modal Colors
Edit `templates/dashboard/add_payment_method.html`:
```javascript
cardElement = elements.create('card', {
    style: {
        base: {
            color: '#e0e0e0',  // Change text color
            // ... other styles
        }
    }
});
```

### Payment Method Icons
Icons use Font Awesome:
- Stripe: `fab fa-cc-stripe`
- PayPal: `fab fa-paypal`
- Bitcoin: `fab fa-bitcoin`
- Ethereum: `fab fa-ethereum`

## 🔄 Updates & Maintenance

### Update Dependencies
```bash
pip install --upgrade paypalrestsdk
pip install --upgrade stripe
```

### Check for Updates
```bash
pip list --outdated | grep -E "paypal|stripe"
```

### Backup Before Updates
```bash
# Backup database
sqlite3 aisbf.db ".backup aisbf_backup.db"

# Backup code
git commit -am "Backup before payment update"
```

## 📈 Monitoring

### Key Metrics
- Payment method addition success rate
- OAuth completion rate
- Error rate by payment type
- Average time to add payment method

### Log Monitoring
```bash
# Watch for errors
tail -f /var/log/aisbf/app.log | grep -i error

# Count payment additions today
grep "payment.*added" /var/log/aisbf/app.log | grep "$(date +%Y-%m-%d)" | wc -l
```

## ✅ Quick Verification

After setup, verify everything works:
```bash
# 1. Check dependencies
python -c "import paypalrestsdk; print('✓ PayPal SDK')"

# 2. Check routes
python -c "from main import app; print('✓ Routes:', len([r for r in app.routes if 'billing' in str(r.path)]))"

# 3. Check database
sqlite3 aisbf.db "SELECT COUNT(*) FROM payment_methods;" && echo "✓ Database"

# 4. Check templates
ls templates/dashboard/paypal_connect.html && echo "✓ Templates"
```

All checks pass? You're ready to go! 🚀

---

**Last Updated:** 2026-04-16  
**Version:** 1.0  
**Status:** Production Ready
