"""
PayPal payment integration
"""
import logging
import base64
import time
import httpx
from typing import Optional

logger = logging.getLogger(__name__)


class PayPalPaymentHandler:
    """Handle PayPal payments with async operations"""
    
    def __init__(self, db_manager, config: dict):
        self.db = db_manager
        self.config = config
        self.http_client = httpx.AsyncClient(timeout=30.0)
        
        # Load PayPal configuration from admin_settings
        gateways = self.db.get_payment_gateway_settings()
        paypal_config = gateways.get('paypal', {})
        
        if paypal_config.get('enabled'):
            self.client_id = paypal_config.get('client_id')
            self.client_secret = paypal_config.get('client_secret')
            self.webhook_secret = paypal_config.get('webhook_secret')
            self.sandbox = paypal_config.get('sandbox', False)
            
            # Set API base URL
            if self.sandbox:
                self.base_url = 'https://api-m.sandbox.paypal.com'
            else:
                self.base_url = 'https://api-m.paypal.com'
        else:
            self.client_id = None
            self.client_secret = None
            self.base_url = None
    
    async def get_access_token(self) -> str:
        """Get PayPal OAuth access token"""
        auth = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()
        
        response = await self.http_client.post(
            f"{self.base_url}/v1/oauth2/token",
            headers={
                'Authorization': f'Basic {auth}',
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            data={'grant_type': 'client_credentials'}
        )
        
        if response.status_code == 200:
            data = response.json()
            return data['access_token']
        else:
            raise Exception(f"Failed to get PayPal access token: {response.text}")
    
    async def create_setup_token(self, return_url: str, cancel_url: str) -> dict:
        """Create PayPal Vault Setup Token for payment method saving"""
        try:
            access_token = await self.get_access_token()
            
            response = await self.http_client.post(
                f"{self.base_url}/v3/vault/setup-tokens",
                headers={
                    'Authorization': f'Bearer {access_token}',
                    'Content-Type': 'application/json'
                },
                json={
                    'payment_source': {
                        'paypal': {
                            'usage_type': 'MERCHANT',
                            'experience_context': {
                                'return_url': return_url,
                                'cancel_url': cancel_url,
                                'shipping_preference': 'NO_SHIPPING',
                                'user_action': 'PAY_NOW'
                            }
                        }
                    }
                }
            )
            
            if response.status_code == 201:
                data = response.json()
                return {
                    'success': True,
                    'id': data['id'],
                    'approval_url': data['links'][1]['href']
                }
            else:
                logger.error(f"Failed to create setup token: {response.text}")
                return {'success': False, 'error': response.text}
                
        except Exception as e:
            logger.error(f"Error creating setup token: {e}")
            return {'success': False, 'error': str(e)}
    
    async def create_payment_token(self, setup_token_id: str) -> dict:
        """Exchange setup token for permanent payment token"""
        try:
            access_token = await self.get_access_token()
            
            response = await self.http_client.post(
                f"{self.base_url}/v3/vault/payment-tokens",
                headers={
                    'Authorization': f'Bearer {access_token}',
                    'Content-Type': 'application/json'
                },
                json={
                    'setup_token_id': setup_token_id
                }
            )
            
            if response.status_code == 201:
                data = response.json()
                return {
                    'success': True,
                    'payment_token_id': data['id'],
                    'payer_email': data.get('payer', {}).get('email_address'),
                    'payment_method_type': data['payment_source']['paypal']['card_type'] if 'card_type' in data['payment_source']['paypal'] else 'PAYPAL'
                }
            else:
                logger.error(f"Failed to create payment token: {response.text}")
                return {'success': False, 'error': response.text}
                
        except Exception as e:
            logger.error(f"Error creating payment token: {e}")
            return {'success': False, 'error': str(e)}
    
    async def charge_payment_token(self, payment_token_id: str, amount: float, currency_code: str = 'USD') -> dict:
        """Charge saved payment token (off-session merchant initiated transaction)"""
        try:
            access_token = await self.get_access_token()
            
            response = await self.http_client.post(
                f"{self.base_url}/v2/checkout/orders",
                headers={
                    'Authorization': f'Bearer {access_token}',
                    'Content-Type': 'application/json',
                    'PayPal-Request-Id': f'charge_{payment_token_id}_{int(time.time())}'
                },
                json={
                    'intent': 'CAPTURE',
                    'purchase_units': [{
                        'amount': {
                            'currency_code': currency_code,
                            'value': f"{amount:.2f}"
                        }
                    }],
                    'payment_source': {
                        'token': {
                            'id': payment_token_id,
                            'type': 'PAYMENT_METHOD_TOKEN'
                        }
                    },
                    'payment_instruction': {
                        'usage': 'MERCHANT',
                        'customer_present': False
                    }
                }
            )
            
            if response.status_code == 201:
                data = response.json()
                return {
                    'success': True,
                    'order_id': data['id'],
                    'status': data['status']
                }
            else:
                logger.error(f"Failed to charge payment token: {response.text}")
                return {'success': False, 'error': response.text}
                
        except Exception as e:
            logger.error(f"Error charging payment token: {e}")
            return {'success': False, 'error': str(e)}
    
    async def create_billing_agreement(self, user_id: int, return_url: str, 
                                      cancel_url: str) -> dict:
        """Create PayPal billing agreement for recurring payments"""
        try:
            access_token = await self.get_access_token()
            
            # Create billing agreement token
            response = await self.http_client.post(
                f"{self.base_url}/v1/billing-agreements/agreement-tokens",
                headers={
                    'Authorization': f'Bearer {access_token}',
                    'Content-Type': 'application/json'
                },
                json={
                    'description': 'AISBF Subscription',
                    'payer': {
                        'payment_method': 'PAYPAL'
                    },
                    'plan': {
                        'type': 'MERCHANT_INITIATED_BILLING',
                        'merchant_preferences': {
                            'return_url': return_url,
                            'cancel_url': cancel_url,
                            'notify_url': f"{self.config['base_url']}/api/webhooks/paypal",
                            'accepted_payment_type': 'INSTANT',
                            'skip_shipping_address': True
                        }
                    }
                }
            )
            
            if response.status_code == 201:
                data = response.json()
                token = data['token_id']
                
                # Generate approval URL
                approval_url = f"{self.base_url}/checkoutnow?token={token}"
                
                return {
                    'success': True,
                    'token': token,
                    'approval_url': approval_url
                }
            else:
                error_data = response.json() if response.headers.get('Content-Type', '').startswith('application/json') else {}
                error_details = error_data.get('details', [])
                
                # Check for specific known errors
                for detail in error_details:
                    error_name = detail.get('name')
                    if error_name == 'REFUSED_MARK_REF_TXN_NOT_ENABLED':
                        logger.error(f"PayPal account does not have Reference Transactions enabled: {response.text}")
                        return {
                            'success': False,
                            'error': 'PayPal merchant account is not configured for Reference Transactions. Please contact PayPal support to enable this feature for your account.',
                            'error_code': 'reference_transactions_not_enabled'
                        }
                
                logger.error(f"Failed to create billing agreement: {response.text}")
                return {'success': False, 'error': response.text}
                
        except Exception as e:
            logger.error(f"Error creating PayPal billing agreement: {e}")
            return {'success': False, 'error': str(e)}
    
    async def execute_billing_agreement(self, user_id: int, token: str) -> dict:
        """Execute billing agreement after user approval"""
        try:
            access_token = await self.get_access_token()
            
            # Execute agreement
            response = await self.http_client.post(
                f"{self.base_url}/v1/billing-agreements/agreements",
                headers={
                    'Authorization': f'Bearer {access_token}',
                    'Content-Type': 'application/json'
                },
                json={'token_id': token}
            )
            
            if response.status_code == 201:
                data = response.json()
                agreement_id = data['id']
                
                # Store payment method
                with self.db._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO payment_methods
                        (user_id, type, identifier, is_default, is_active)
                        VALUES (?, 'paypal', ?, 1, 1)
                    """, (user_id, agreement_id))
                    conn.commit()
                
                logger.info(f"Executed PayPal billing agreement for user {user_id}")
                
                return {
                    'success': True,
                    'agreement_id': agreement_id,
                    'payer_email': data.get('payer', {}).get('payer_info', {}).get('email')
                }
            else:
                logger.error(f"Failed to execute billing agreement: {response.text}")
                return {'success': False, 'error': response.text}
                
        except Exception as e:
            logger.error(f"Error executing PayPal billing agreement: {e}")
            return {'success': False, 'error': str(e)}
    
    async def handle_webhook(self, payload: dict, headers: dict) -> dict:
        """Handle PayPal webhook events"""
        try:
            # Verify webhook signature for security
            if not await self._verify_webhook_signature(payload, headers):
                logger.error("PayPal webhook signature verification failed")
                return {'status': 'error', 'message': 'Invalid signature'}
            
            event_type = payload.get('event_type')
            resource = payload.get('resource', {})
            
            logger.info(f"Received PayPal webhook: {event_type}")
            
            # Vault v3 / Payment events
            if event_type == 'CHECKOUT.ORDER.COMPLETED':
                await self._handle_order_completed(resource)
            elif event_type == 'CHECKOUT.ORDER.APPROVED':
                await self._handle_order_approved(resource)
            elif event_type == 'PAYMENT.CAPTURE.COMPLETED':
                await self._handle_payment_capture_completed(resource)
            elif event_type == 'PAYMENT.CAPTURE.DENIED':
                await self._handle_payment_capture_denied(resource)
            elif event_type == 'PAYMENT.CAPTURE.REFUNDED':
                await self._handle_payment_refunded(resource)
            
            # Legacy billing agreement events (backward compatibility)
            elif event_type == 'PAYMENT.SALE.COMPLETED':
                await self._handle_payment_completed(resource)
            elif event_type == 'PAYMENT.SALE.DENIED':
                await self._handle_payment_denied(resource)
            
            # Vault token events
            elif event_type == 'VAULT.PAYMENT-TOKEN.CREATED':
                await self._handle_vault_token_created(resource)
            elif event_type == 'VAULT.PAYMENT-TOKEN.DELETED':
                await self._handle_vault_token_deleted(resource)
            
            # Customer disputes
            elif event_type == 'CUSTOMER.DISPUTE.CREATED':
                await self._handle_dispute_created(resource)
            elif event_type == 'CUSTOMER.DISPUTE.RESOLVED':
                await self._handle_dispute_resolved(resource)
            
            else:
                logger.info(f"Unhandled PayPal webhook event: {event_type}")
            
            return {'status': 'success'}
            
        except Exception as e:
            logger.error(f"Error handling PayPal webhook: {e}")
            return {'status': 'error', 'message': str(e)}
    
    async def _verify_webhook_signature(self, payload: dict, headers: dict) -> bool:
        """
        Verify PayPal webhook signature
        
        For production, implement proper signature verification:
        https://developer.paypal.com/api/rest/webhooks/rest/#verify-webhook-signature
        """
        # For now, basic verification - in production, verify the signature properly
        if not self.webhook_secret:
            logger.warning("PayPal webhook_secret not configured - skipping signature verification")
            return True
        
        # TODO: Implement proper webhook signature verification
        # This requires calling PayPal's verify-webhook-signature endpoint
        # with the webhook_id, transmission_id, transmission_sig, etc.
        
        return True
    
    async def _handle_order_completed(self, resource: dict):
        """Handle completed order (Vault v3)"""
        order_id = resource.get('id')
        logger.info(f"PayPal order completed: {order_id}")
        # TODO: Update transaction status in database
    
    async def _handle_order_approved(self, resource: dict):
        """Handle approved order"""
        order_id = resource.get('id')
        logger.info(f"PayPal order approved: {order_id}")
    
    async def _handle_payment_capture_completed(self, resource: dict):
        """Handle completed payment capture"""
        capture_id = resource.get('id')
        logger.info(f"PayPal payment capture completed: {capture_id}")
        # TODO: Mark subscription payment as successful
    
    async def _handle_payment_capture_denied(self, resource: dict):
        """Handle denied payment capture"""
        capture_id = resource.get('id')
        logger.warning(f"PayPal payment capture denied: {capture_id}")
        # TODO: Add to payment retry queue
    
    async def _handle_payment_refunded(self, resource: dict):
        """Handle refunded payment"""
        refund_id = resource.get('id')
        logger.info(f"PayPal payment refunded: {refund_id}")
        # TODO: Update transaction and subscription status
    
    async def _handle_vault_token_created(self, resource: dict):
        """Handle vault token creation"""
        token_id = resource.get('id')
        logger.info(f"PayPal vault token created: {token_id}")
    
    async def _handle_vault_token_deleted(self, resource: dict):
        """Handle vault token deletion"""
        token_id = resource.get('id')
        logger.info(f"PayPal vault token deleted: {token_id}")
        # TODO: Mark payment method as inactive in database
    
    async def _handle_dispute_created(self, resource: dict):
        """Handle dispute creation"""
        dispute_id = resource.get('dispute_id')
        logger.warning(f"PayPal dispute created: {dispute_id}")
        # TODO: Send notification to admin
    
    async def _handle_dispute_resolved(self, resource: dict):
        """Handle dispute resolution"""
        dispute_id = resource.get('dispute_id')
        logger.info(f"PayPal dispute resolved: {dispute_id}")
    
    async def _handle_payment_completed(self, resource: dict):
        """Handle completed payment (legacy)"""
        logger.info(f"PayPal payment completed: {resource.get('id')}")
    
    async def _handle_payment_denied(self, resource: dict):
        """Handle denied payment (legacy)"""
        logger.warning(f"PayPal payment denied: {resource.get('id')}")
