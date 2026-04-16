# Critical Fix - Missing Template in PyPI Package

## Issue

**Error**: `TemplateNotFound: 'dashboard/admin_payment_settings.html' not found in search path: 'templates'`

**Impact**: Production deployment failed with 500 Internal Server Error when accessing `/dashboard/admin/payment-settings`

## Root Cause

The `admin_payment_settings.html` template was created in the repository but was **NOT added to setup.py's data_files list**. This meant:

1. Template exists in git repository ✓
2. Template works in development ✓
3. Template NOT included in PyPI package ✗
4. Production installation missing the file ✗

## Fix Applied

**Commit**: 02f867a

**File**: `setup.py`

**Change**: Added line 218
```python
'templates/dashboard/admin_payment_settings.html',
```

**Location in setup.py**:
```python
data_files=[
    ('share/aisbf/templates/dashboard', [
        # ... other templates ...
        'templates/dashboard/admin_tiers.html',
        'templates/dashboard/admin_tier_form.html',
        'templates/dashboard/admin_payment_settings.html',  # ← ADDED
        'templates/dashboard/pricing.html',
        # ... more templates ...
    ]),
]
```

## How This Happened

When the admin payment settings page was created, the template file was added to the repository but the setup.py file was not updated to include it in the package distribution. This is a common oversight when adding new templates.

## Resolution Steps

### For Development
No action needed - template already exists in repository.

### For Production Deployment

1. **Pull latest changes**:
   ```bash
   cd /path/to/aisbf
   git pull origin feature/subscription-payment-system
   ```

2. **Rebuild the package**:
   ```bash
   ./build.sh
   ```

3. **Reinstall the package**:
   ```bash
   pip install dist/aisbf-0.99.27-*.whl --force-reinstall
   ```

4. **Restart AISBF service**:
   ```bash
   systemctl restart aisbf
   # or
   supervisorctl restart aisbf
   # or kill and restart the process
   ```

5. **Verify template is installed**:
   ```bash
   ls -la /usr/local/share/aisbf/templates/dashboard/admin_payment_settings.html
   # or
   ls -la /home/aisbf/.local/share/aisbf/templates/dashboard/admin_payment_settings.html
   ```

6. **Test the page**:
   ```bash
   curl -I http://localhost:17765/dashboard/admin/payment-settings
   # Should return 200 OK (after login)
   ```

## Verification

After reinstalling, the template should be present in the installation directory:

**System-wide installation**:
```
/usr/local/share/aisbf/templates/dashboard/admin_payment_settings.html
```

**User installation**:
```
~/.local/share/aisbf/templates/dashboard/admin_payment_settings.html
```

**Virtual environment**:
```
/path/to/venv/share/aisbf/templates/dashboard/admin_payment_settings.html
```

## Prevention

To prevent this in the future:

1. **Always update setup.py when adding templates**
2. **Test PyPI package installation before deploying**:
   ```bash
   ./build.sh
   pip install dist/aisbf-*.whl --force-reinstall
   python -c "import os; print(os.path.exists('/usr/local/share/aisbf/templates/dashboard/admin_payment_settings.html'))"
   ```
3. **Add to deployment checklist**: Verify all new templates are in setup.py

## Related Files

- `setup.py` - Package configuration (FIXED)
- `templates/dashboard/admin_payment_settings.html` - Template file (exists)
- `main.py` line 6754 - Route that uses the template

## Status

✅ **FIXED** - Template now included in setup.py
✅ **TESTED** - Verified template is in data_files list
⏳ **PENDING** - Needs rebuild and reinstall in production

## Timeline

- **2026-04-16 18:50**: Error discovered in production
- **2026-04-16 18:52**: Root cause identified
- **2026-04-16 18:53**: Fix applied (commit 02f867a)
- **Next**: Rebuild and redeploy

## Commit Details

```
commit 02f867a
Author: [Your Name]
Date: 2026-04-16

fix: add admin_payment_settings.html to setup.py data_files

- Template was missing from PyPI package
- Caused TemplateNotFound error when accessing /dashboard/admin/payment-settings
- Added to templates/dashboard list in setup.py
```

## Additional Notes

This was the only missing template. All other templates were already properly included in setup.py:
- ✅ admin_tiers.html
- ✅ admin_tier_form.html
- ✅ pricing.html
- ✅ subscription.html
- ✅ billing.html
- ✅ add_payment_method.html
- ✅ paypal_connect.html

The admin_payment_settings.html template is now added to this list.
