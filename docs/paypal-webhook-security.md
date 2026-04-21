# PayPal Webhook Security Implementation

## Current Status
- ✅ Webhook endpoint created: `/api/webhooks/paypal`
- ✅ Event handlers implemented for Vault v3 events
- ⚠️ Signature verification is a placeholder (returns True)

## Production TODO: Implement Signature Verification

### Why It's Important
Without signature verification, anyone can send fake webhook requests to your endpoint and trigger actions in your system.

### How to Implement

PayPal provides webhook signature verification via their API. You need to:

1. **Extract headers from the webhook request:**
   - `PAYPAL-TRANSMISSION-ID`
   - `PAYPAL-TRANSMISSION-TIME`
   - `PAYPAL-TRANSMISSION-SIG`
   - `PAYPAL-CERT-URL`
   - `PAYPAL-AUTH-ALGO`

2. **Call PayPal's verify-webhook-signature endpoint:**

```python
async def _verify_webhook_signature(self, payload: dict, headers: dict) -> bool:
    """Verify PayPal webhook signature"""
    
    # Extract required headers
    transmission_id = headers.get('paypal-transmission-id')
    transmission_time = headers.get('paypal-transmission-time')
    transmission_sig = headers.get('paypal-transmission-sig')
    cert_url = headers.get('paypal-cert-url')
    auth_algo = headers.get('paypal-auth-algo')
    
    if not all([transmission_id, transmission_time, transmission_sig]):
        logger.error("Missing required webhook signature headers")
        return False
    
    # Get access token
    access_token = await self.get_access_token()
    
    # Verify signature with PayPal
    response = await self.http_client.post(
        f"{self.base_url}/v1/notifications/verify-webhook-signature",
        headers={
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        },
        json={
            'transmission_id': transmission_id,
            'transmission_time': transmission_time,
            'transmission_sig': transmission_sig,
            'cert_url': cert_url,
            'auth_algo': auth_algo,
            'webhook_id': self.webhook_secret,  # This is actually the webhook_id
            'webhook_event': payload
        }
    )
    
    if response.status_code == 200:
        result = response.json()
        verification_status = result.get('verification_status')
        
        if verification_status == 'SUCCESS':
            logger.info("Webhook signature verified successfully")
            return True
        else:
            logger.error(f"Webhook signature verification failed: {verification_status}")
            return False
    else:
        logger.error(f"Failed to verify webhook signature: {response.text}")
        return False
```

3. **Update the webhook handler to use this verification**

The placeholder is already in place - just replace the TODO with the code above.

## References
- [PayPal Webhook Signature Verification](https://developer.paypal.com/api/rest/webhooks/#verify-webhook-signature)
- [Webhook Security Best Practices](https://developer.paypal.com/docs/api-basics/notifications/webhooks/notification-messages/)

## Testing
1. Use PayPal's webhook simulator to send test events
2. Verify that signature verification passes for legitimate webhooks
3. Test with invalid signatures to ensure they're rejected
