# Payment Method Addition Design

## Overview
Implement a dedicated page for adding payment methods in the AISBF dashboard billing section. The page will display only enabled payment gateways as clickable options and handle secure integration with each gateway type.

## Requirements
- New route: `/dashboard/billing/add-method`
- Show only enabled payment gateways from database
- Secure integrations: Stripe Elements for cards, PayPal OAuth, crypto default setting
- Consistent UI with existing dashboard theme
- Proper error handling and success feedback
- Redirect back to billing page after completion

## Architecture

### Backend Changes
- New FastAPI route `@app.get("/dashboard/billing/add-method")`
- New template `templates/dashboard/add_payment_method.html`
- Reuse existing `enabled_gateways` logic from billing route
- Handle gateway-specific form submissions and redirects

### Frontend Changes
- Update billing.html to change "Add Payment Method" button from modal trigger to page redirect
- Remove the add payment method modal from billing.html
- New add_payment_method.html template with gateway selection cards

### Integration Details

#### Stripe
- Use Stripe Elements for secure card input
- No local storage of card data
- Handle Stripe token creation and storage of payment method ID

#### PayPal
- Initiate PayPal OAuth flow for account connection
- Handle OAuth redirect back to dashboard
- Store PayPal payment method reference

#### Crypto
- Immediate default setting without additional forms
- Store crypto type as default payment method
- No external API calls required

## User Flow
1. User clicks "Add Payment Method" on billing page
2. Redirected to `/dashboard/billing/add-method`
3. Sees cards for enabled gateways only
4. Clicks desired gateway card
5. Completes gateway-specific flow (form/OAuth/immediate)
6. Redirected back to billing page with success message
7. New payment method appears in payment methods list

## Error Handling
- Invalid gateway selections: Show error message
- Integration failures: Display gateway-specific errors
- Network issues: Retry mechanisms where appropriate
- Authentication failures: Re-prompt for credentials

## Security Considerations
- No sensitive payment data stored locally
- Use HTTPS for all payment flows
- Validate all user inputs server-side
- Implement CSRF protection for forms

## Testing
- Unit tests for new route and template rendering
- Integration tests for each gateway flow
- UI tests for responsive design
- Error scenario testing

## Future Extensions
- Support for additional payment gateways
- Bulk payment method management
- Payment method validation/verification
- Subscription integration