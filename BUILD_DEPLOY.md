# Building and Deploying AISBF v0.99.27 with Payment System

## Quick Build Instructions

### 1. Build the Package

```bash
cd /path/to/aisbf
git checkout feature/subscription-payment-system
./build.sh
```

This will:
- Build the OAuth2 extension
- Clean previous builds
- Create distribution packages in `dist/`
- Verify the package integrity

### 2. Upload to PyPI

**Test PyPI (recommended first):**
```bash
python -m twine upload --repository testpypi dist/*
```

**Production PyPI:**
```bash
python -m twine upload dist/*
```

### 3. Install on Remote Machines

**Option A: From PyPI (after upload)**
```bash
pip install --upgrade aisbf
```

**Option B: From Local Build**
```bash
# Copy the wheel file to remote machine
scp dist/aisbf-0.99.27-*.whl user@remote:/tmp/

# On remote machine
pip install /tmp/aisbf-0.99.27-*.whl
```

**Option C: Direct from Git**
```bash
pip install git+https://git.nexlab.net/nexlab/aisbf.git@feature/subscription-payment-system
```

## Installation Options

### Core Installation (Fiat Payments Only)

```bash
pip install aisbf
# or
pip install -r requirements.txt
```

Includes: Stripe, PayPal, subscriptions, renewals, email notifications

### Full Installation (Fiat + Crypto)

```bash
# Install system dependencies first
sudo apt-get install pkg-config libsecp256k1-dev build-essential

# Install Python packages
pip install aisbf
pip install -r requirements-crypto.txt
```

Includes: All core features + BTC, ETH, USDT, USDC payments

## What's New in v0.99.27

### Complete Subscription Payment System

**Phase 1: Foundation & Crypto**
- HD wallet manager (BIP32/BIP44)
- Multi-exchange price aggregation
- Blockchain monitoring
- Crypto payment API

**Phase 2: Fiat Payments**
- Stripe integration with authorization holds
- PayPal billing agreements
- Payment method management
- Webhook handlers

**Phase 3: Subscriptions & Billing**
- Subscription lifecycle management
- Prorated upgrades
- Scheduled downgrades
- Automatic renewals
- Smart payment retry logic

**Phase 4: Advanced Features**
- Quota enforcement (creation order)
- Wallet consolidation
- Email notifications
- Background scheduler
- Admin configuration API

### API Endpoints Added (17 total)

- 3 crypto payment endpoints
- 5 fiat payment endpoints
- 2 webhook endpoints
- 5 subscription management endpoints
- 2 admin configuration endpoints

## Configuration

### Environment Variables

```bash
# Required for crypto payments
export ENCRYPTION_KEY="your-fernet-key-here"

# Optional
export BASE_URL="https://your-domain.com"
```

### Database Migrations

Migrations run automatically on startup. The payment system adds 20+ new tables.

### Payment Gateway Setup

Configure in the admin dashboard:
1. Navigate to Admin → Payment Settings
2. Add Stripe API keys (test/live)
3. Add PayPal client credentials
4. Configure crypto consolidation addresses (if using crypto)
5. Set up email notification preferences

## Troubleshooting

### "No module named 'aisbf.payments'"

The package wasn't built/installed correctly. Rebuild with:
```bash
./build.sh
pip install --force-reinstall dist/aisbf-0.99.27-*.whl
```

### "coincurve build failed"

Missing system dependencies. Install:
```bash
sudo apt-get install pkg-config libsecp256k1-dev build-essential
```

Or skip crypto support and use core installation only.

### "No ENCRYPTION_KEY set"

Set the environment variable:
```bash
export ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
```

## Verification

After installation, verify the payment system is loaded:

```bash
python -c "from aisbf.payments import PaymentService; print('Payment system loaded successfully')"
```

Check version:
```bash
python -c "import aisbf; print(aisbf.__version__)"
# Should output: 0.99.27
```

## Support

For issues or questions:
- GitHub Issues: https://git.nexlab.net/nexlab/aisbf.git/issues
- Documentation: See PAYMENT_INSTALLATION.md
- Email: stefy@nexlab.net
