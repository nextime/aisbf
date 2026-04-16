# Payment System Installation Guide

The AISBF payment system supports both fiat (Stripe/PayPal) and cryptocurrency payments. Cryptocurrency support is optional due to system dependency requirements.

## Installation Options

### Option 1: Core Payment System Only (Fiat Payments)

Install the base requirements without cryptocurrency support:

```bash
pip install -r requirements.txt
```

This includes:
- ✅ Stripe payment processing
- ✅ PayPal billing agreements
- ✅ Subscription management
- ✅ Email notifications
- ✅ Background scheduler
- ❌ Cryptocurrency payments (BTC, ETH, USDT, USDC)

### Option 2: Full Payment System (Fiat + Crypto)

#### Step 1: Install System Dependencies

**Ubuntu/Debian:**
```bash
sudo apt-get update
sudo apt-get install -y pkg-config libsecp256k1-dev build-essential
```

**RHEL/CentOS/Fedora:**
```bash
sudo yum install -y pkgconfig libsecp256k1-devel gcc
```

**Alpine Linux:**
```bash
sudo apk add pkgconfig libsecp256k1-dev gcc musl-dev
```

#### Step 2: Install Python Dependencies

```bash
pip install -r requirements.txt
pip install -r requirements-crypto.txt
```

This includes:
- ✅ All fiat payment features
- ✅ Cryptocurrency payments (BTC, ETH, USDT, USDC)
- ✅ HD wallet generation (BIP32/BIP44)
- ✅ Blockchain monitoring
- ✅ Multi-exchange price aggregation

## Troubleshooting

### Error: "Could NOT find PkgConfig"

This means system dependencies are missing. Install them using the commands above for your OS.

### Error: "coincurve build failed"

The `coincurve` package requires `libsecp256k1`. Install system dependencies first, then retry.

### Alternative: Use Pre-built Wheels

If you cannot install system dependencies, try using pre-built wheels:

```bash
pip install --only-binary :all: coincurve
pip install -r requirements-crypto.txt
```

## Configuration

After installation, configure the payment system:

1. Set encryption key for HD wallets:
   ```bash
   export ENCRYPTION_KEY="your-fernet-key-here"
   ```

2. Configure payment gateways in the admin dashboard:
   - Stripe API keys
   - PayPal client credentials
   - Crypto consolidation addresses (if using crypto)

3. Run database migrations:
   ```bash
   python main.py  # Migrations run automatically on startup
   ```

## Features by Installation Type

| Feature | Core Only | Full (Crypto) |
|---------|-----------|---------------|
| Stripe Payments | ✅ | ✅ |
| PayPal Payments | ✅ | ✅ |
| Subscriptions | ✅ | ✅ |
| Auto-renewals | ✅ | ✅ |
| Email Notifications | ✅ | ✅ |
| Quota Enforcement | ✅ | ✅ |
| BTC Payments | ❌ | ✅ |
| ETH/USDT/USDC | ❌ | ✅ |
| HD Wallet | ❌ | ✅ |
| Blockchain Monitor | ❌ | ✅ |
| Wallet Consolidation | ❌ | ✅ |

## Recommendation

For production deployments:
- **With crypto support**: Install on a server where you have root access to install system dependencies
- **Without crypto support**: Use the core installation and rely on Stripe/PayPal for all payments

Both options provide a fully functional subscription payment system.
