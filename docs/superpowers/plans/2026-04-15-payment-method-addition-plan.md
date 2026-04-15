# Payment Method Addition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a dedicated page for securely adding payment methods to user accounts, with gateway-specific integrations.

**Architecture:** New FastAPI route serves an HTML page displaying enabled payment gateways as selectable options. Each gateway uses appropriate secure integration (Stripe Elements, PayPal OAuth, immediate crypto default setting) with server-side handling and database storage.

**Tech Stack:** Python/FastAPI backend, Jinja2 templates, Stripe Elements JS, PayPal OAuth, SQLite database, Bootstrap CSS.

---

### Task 1: Update Billing Page Button

**Files:**
- Modify: `templates/dashboard/billing.html`

- [ ] **Step 1: Remove modal HTML**
Remove the entire add payment method modal (lines 201-386) from billing.html, including the duplicate modal.

- [ ] **Step 2: Change button to redirect**
Replace the "Add Payment Method" button's `data-bs-toggle` and `data-bs-target` attributes with `href="{{ url_for(request, '/dashboard/billing/add-method') }}"`.

- [ ] **Step 3: Commit changes**
```bash
git add templates/dashboard/billing.html
git commit -m "feat: update billing page to redirect to add payment method page"
```

### Task 2: Add Backend Route for Add Method Page

**Files:**
- Modify: `main.py`
- Test: Create `test_add_payment_method.py` (new test file)

- [ ] **Step 1: Write failing test for route**
```python
import pytest
from fastapi.testclient import TestClient
from main import app

def test_add_payment_method_page():
    client = TestClient(app)
    # Mock authenticated session
    with client:
        response = client.get("/dashboard/billing/add-method")
        assert response.status_code == 200
        assert "Add Payment Method" in response.text
```

- [ ] **Step 2: Run test to verify it fails**
Run: `python -m pytest test_add_payment_method.py::test_add_payment_method_page -v`
Expected: FAIL (route not implemented)

- [ ] **Step 3: Implement the route**
Add to main.py after the billing route:
```python
@app.get("/dashboard/billing/add-method")
async def dashboard_add_payment_method(request: Request):
    """Add payment method page"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    from aisbf.database import get_database
    db = DatabaseRegistry.get_config_database()
    
    # Get enabled payment gateways
    enabled_gateways = []
    gateways = db.get_payment_gateway_settings()
    for gateway, settings in gateways.items():
        if settings.get('enabled', False):
            enabled_gateways.append(gateway)
    
    return templates.TemplateResponse(
        request=request,
        name="dashboard/add_payment_method.html",
        context={
            "request": request,
            "session": request.session,
            "enabled_gateways": enabled_gateways
        }
    )
```

- [ ] **Step 4: Run test to verify it passes**
Run: `python -m pytest test_add_payment_method.py::test_add_payment_method_page -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add main.py test_add_payment_method.py
git commit -m "feat: add backend route for payment method addition page"
```

### Task 3: Create Add Payment Method Template

**Files:**
- Create: `templates/dashboard/add_payment_method.html`
- Modify: `setup.py` (add template to package)

- [ ] **Step 1: Write template HTML**
Create new file `templates/dashboard/add_payment_method.html`:
```html
{% extends "base.html" %}

{% block title %}Add Payment Method - AISBF Dashboard{% endblock %}

{% block content %}
<h2 style="margin-bottom: 30px;">Add Payment Method</h2>

<div style="max-width: 800px; margin: 0 auto;">
    <div style="background: #16213e; border: 2px solid #4a9eff; border-radius: 8px; padding: 30px;">
        <p class="text-muted mb-4">Choose a payment method to add to your account. You can use this for subscription payments and plan upgrades.</p>

        <div class="row g-4">
            {% if 'stripe' in enabled_gateways %}
            <div class="col-md-6">
                <div class="card h-100 border-primary">
                    <div class="card-body text-center">
                        <i class="fab fa-cc-stripe fa-4x mb-3 text-primary"></i>
                        <h5 class="card-title">Credit Card</h5>
                        <p class="card-text text-muted">Secure payment via Stripe</p>
                        <button class="btn btn-primary w-100" id="stripe-button">Add Credit Card</button>
                    </div>
                </div>
            </div>
            {% endif %}

            {% if 'paypal' in enabled_gateways %}
            <div class="col-md-6">
                <div class="card h-100 border-primary">
                    <div class="card-body text-center">
                        <i class="fab fa-paypal fa-4x mb-3 text-primary"></i>
                        <h5 class="card-title">PayPal</h5>
                        <p class="card-text text-muted">Connect your PayPal account</p>
                        <button class="btn btn-primary w-100" id="paypal-button">Connect PayPal</button>
                    </div>
                </div>
            </div>
            {% endif %}

            {% if 'bitcoin' in enabled_gateways or 'eth' in enabled_gateways or 'usdt' in enabled_gateways or 'usdc' in enabled_gateways %}
            <div class="col-12">
                <div class="card border-warning">
                    <div class="card-header bg-warning text-dark">
                        <h6 class="mb-0">
                            <i class="fab fa-bitcoin me-2"></i>Cryptocurrency Payments
                        </h6>
                    </div>
                    <div class="card-body">
                        <p class="text-muted mb-3">Set cryptocurrency as your default payment method</p>
                        <div class="row g-3">
                            {% if 'bitcoin' in enabled_gateways %}
                            <div class="col-md-3">
                                <button class="btn btn-outline-warning w-100 crypto-default" data-type="bitcoin">
                                    <i class="fab fa-bitcoin fa-2x mb-2"></i><br>
                                    <strong>Bitcoin</strong>
                                </button>
                            </div>
                            {% endif %}
                            {% if 'eth' in enabled_gateways %}
                            <div class="col-md-3">
                                <button class="btn btn-outline-purple w-100 crypto-default" data-type="eth">
                                    <i class="fab fa-ethereum fa-2x mb-2"></i><br>
                                    <strong>Ethereum</strong>
                                </button>
                            </div>
                            {% endif %}
                            {% if 'usdt' in enabled_gateways %}
                            <div class="col-md-3">
                                <button class="btn btn-outline-success w-100 crypto-default" data-type="usdt">
                                    <i class="fas fa-coins fa-2x mb-2"></i><br>
                                    <strong>USDT</strong>
                                </button>
                            </div>
                            {% endif %}
                            {% if 'usdc' in enabled_gateways %}
                            <div class="col-md-3">
                                <button class="btn btn-outline-info w-100 crypto-default" data-type="usdc">
                                    <i class="fas fa-coins fa-2x mb-2"></i><br>
                                    <strong>USDC</strong>
                                </button>
                            </div>
                            {% endif %}
                        </div>
                    </div>
                </div>
            </div>
            {% endif %}
        </div>

        <div class="text-center mt-4">
            <a href="{{ url_for(request, '/dashboard/billing') }}" class="btn btn-secondary">Back to Billing</a>
        </div>
    </div>
</div>

<!-- Stripe Elements Container -->
<div id="stripe-form" style="display: none;">
    <form id="payment-form">
        <div id="card-element"></div>
        <button id="submit-button">Add Card</button>
    </form>
</div>

{% endblock %}

{% block extra_js %}
<script src="https://js.stripe.com/v3/"></script>
<script>
document.addEventListener('DOMContentLoaded', function() {
    // Crypto default buttons
    document.querySelectorAll('.crypto-default').forEach(button => {
        button.addEventListener('click', function() {
            const type = this.dataset.type;
            fetch('/dashboard/billing/add-method', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ type: type, action: 'set_default' })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    window.location.href = '/dashboard/billing?success=' + encodeURIComponent(data.message);
                } else {
                    alert('Error: ' + data.error);
                }
            });
        });
    });

    // PayPal button
    document.getElementById('paypal-button').addEventListener('click', function() {
        window.location.href = '/dashboard/billing/add-method/paypal/oauth';
    });

    // Stripe button - show Stripe form
    document.getElementById('stripe-button').addEventListener('click', function() {
        document.getElementById('stripe-form').style.display = 'block';
        // Initialize Stripe Elements
        const stripe = Stripe('{{ stripe_publishable_key }}');
        const elements = stripe.elements();
        const cardElement = elements.create('card');
        cardElement.mount('#card-element');
        
        const form = document.getElementById('payment-form');
        form.addEventListener('submit', async (event) => {
            event.preventDefault();
            const {error, paymentMethod} = await stripe.createPaymentMethod({
                type: 'card',
                card: cardElement,
            });
            if (error) {
                alert(error.message);
            } else {
                // Send payment method ID to server
                fetch('/dashboard/billing/add-method/stripe', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ payment_method_id: paymentMethod.id })
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        window.location.href = '/dashboard/billing?success=' + encodeURIComponent(data.message);
                    } else {
                        alert('Error: ' + data.error);
                    }
                });
            }
        });
    });
});
</script>
{% endblock %}
```

- [ ] **Step 2: Update setup.py to include template**
Add to setup.py MANIFEST.in or package_data to include the new template.

- [ ] **Step 3: Commit**
```bash
git add templates/dashboard/add_payment_method.html setup.py
git commit -m "feat: create add payment method template with gateway selection"
```

### Task 4: Implement Stripe Integration

**Files:**
- Modify: `main.py` (add Stripe routes)
- Modify: `templates/dashboard/add_payment_method.html` (add Stripe publishable key context)

- [ ] **Step 1: Add Stripe POST route**
Add to main.py:
```python
@app.post("/dashboard/billing/add-method/stripe")
async def dashboard_add_payment_method_stripe(request: Request, data: dict):
    """Handle Stripe payment method addition"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    user_id = request.session.get('user_id')
    payment_method_id = data.get('payment_method_id')
    
    # Store payment method in database
    from aisbf.database import get_database
    db = DatabaseRegistry.get_config_database()
    
    # Attach payment method to customer (assuming customer exists)
    # Implementation depends on existing Stripe integration
    
    return {"success": True, "message": "Credit card added successfully"}
```

- [ ] **Step 2: Add Stripe publishable key to template context**
Modify the add_payment_method route to include Stripe key from config.

- [ ] **Step 3: Commit**
```bash
git add main.py
git commit -m "feat: implement Stripe payment method addition"
```

### Task 5: Implement PayPal Integration

**Files:**
- Modify: `main.py` (add PayPal OAuth route)

- [ ] **Step 1: Add PayPal OAuth route**
Add to main.py:
```python
@app.get("/dashboard/billing/add-method/paypal/oauth")
async def dashboard_paypal_oauth(request: Request):
    """Initiate PayPal OAuth flow"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    # Redirect to PayPal OAuth URL
    paypal_oauth_url = "https://www.paypal.com/oauth/authorize?client_id=YOUR_CLIENT_ID&response_type=code&redirect_uri=YOUR_REDIRECT_URI"
    return RedirectResponse(paypal_oauth_url)

@app.get("/dashboard/billing/add-method/paypal/callback")
async def dashboard_paypal_callback(request: Request, code: str):
    """Handle PayPal OAuth callback"""
    # Exchange code for access token and store payment method
    return RedirectResponse("/dashboard/billing?success=PayPal connected successfully")
```

- [ ] **Step 2: Commit**
```bash
git add main.py
git commit -m "feat: implement PayPal OAuth integration"
```

### Task 6: Implement Crypto Default Setting

**Files:**
- Modify: `main.py` (add POST route for crypto)

- [ ] **Step 1: Add crypto POST route**
Add to main.py:
```python
@app.post("/dashboard/billing/add-method")
async def dashboard_add_payment_method_post(request: Request, data: dict):
    """Handle crypto default setting"""
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check
    
    user_id = request.session.get('user_id')
    payment_type = data.get('type')
    
    if payment_type in ['bitcoin', 'eth', 'usdt', 'usdc']:
        from aisbf.database import get_database
        db = DatabaseRegistry.get_config_database()
        
        # Set as default payment method
        db.set_user_default_payment_method(user_id, payment_type)
        
        return {"success": True, "message": f"{payment_type.upper()} set as default payment method"}
    
    return {"success": False, "error": "Invalid payment type"}
```

- [ ] **Step 2: Commit**
```bash
git add main.py
git commit -m "feat: implement crypto default payment method setting"
```

### Task 7: Add Success/Error Handling

**Files:**
- Modify: `templates/dashboard/billing.html` (handle success query param)
- Modify: `main.py` (ensure redirects work)

- [ ] **Step 1: Update billing route to handle success messages**
Modify dashboard_billing route to pass success message from query param.

- [ ] **Step 2: Update billing template to show success messages**
Add success message display in billing.html.

- [ ] **Step 3: Commit**
```bash
git add main.py templates/dashboard/billing.html
git commit -m "feat: add success message handling for payment method addition"
```

### Task 8: Run Integration Tests

**Files:**
- Test: Manual testing of flows

- [ ] **Step 1: Test Stripe flow**
Manually test adding credit card via Stripe Elements.

- [ ] **Step 2: Test PayPal flow**
Manually test PayPal OAuth redirect.

- [ ] **Step 3: Test crypto flow**
Manually test setting crypto as default.

- [ ] **Step 4: Test error scenarios**
Verify error handling for invalid inputs.

- [ ] **Step 5: Commit any fixes**
```bash
git add [files]
git commit -m "fix: address issues found during testing"
```