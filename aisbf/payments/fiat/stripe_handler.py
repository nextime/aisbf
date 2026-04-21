"""
Stripe payment integration
"""
import logging
import stripe
import asyncio
from typing import Optional

logger = logging.getLogger(__name__)


class StripePaymentHandler:
    """Handle Stripe payments with async operations"""
    
    def __init__(self, db_manager, config: dict):
        self.db = db_manager
        self.config = config
        
        # Load Stripe configuration from admin_settings
        gateways = self.db.get_payment_gateway_settings()
        stripe_config = gateways.get('stripe', {})
        
        if stripe_config.get('enabled'):
            stripe.api_key = stripe_config.get('secret_key')
            self.publishable_key = stripe_config.get('publishable_key')
            self.webhook_secret = stripe_config.get('webhook_secret')
            self.test_mode = stripe_config.get('sandbox', False)
        else:
            self.publishable_key = None
            self.webhook_secret = None
    
    async def add_payment_method(self, user_id: int, payment_method_token: str) -> dict:
        """Add Stripe payment method with authorization hold for verification"""
        try:
            # Get or create Stripe customer
            customer_id = await self._get_or_create_customer(user_id)
            
            # Attach payment method to customer
            payment_method = await asyncio.to_thread(
                stripe.PaymentMethod.attach,
                payment_method_token,
                customer=customer_id
            )
            
            # Set as default payment method
            await asyncio.to_thread(
                stripe.Customer.modify,
                customer_id,
                invoice_settings={'default_payment_method': payment_method.id}
            )
            
            # Create authorization hold for verification (not a charge)
            verification_amount = 100  # $1.00 in cents
            
            payment_intent = await asyncio.to_thread(
                stripe.PaymentIntent.create,
                amount=verification_amount,
                currency=self.config.get('currency_code', 'usd').lower(),
                customer=customer_id,
                payment_method=payment_method.id,
                capture_method='manual',  # Authorization only, not captured
                confirm=True,
                description='Payment method verification'
            )
            
            # Cancel the authorization immediately (releases the hold)
            await asyncio.to_thread(
                stripe.PaymentIntent.cancel,
                payment_intent.id
            )
            
            # Store payment method in database
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO payment_methods
                    (user_id, type, identifier, is_default, is_active)
                    VALUES (?, 'stripe', ?, 1, 1)
                """, (user_id, payment_method.id))
                conn.commit()
            
            logger.info(f"Added Stripe payment method for user {user_id}")
            
            return {
                'success': True,
                'payment_method_id': payment_method.id,
                'last4': payment_method.card.last4,
                'brand': payment_method.card.brand
            }
            
        except stripe.error.CardError as e:
            logger.error(f"Card error: {e.user_message}")
            return {'success': False, 'error': e.user_message}
        except Exception as e:
            logger.error(f"Error adding Stripe payment method: {e}")
            return {'success': False, 'error': str(e)}
    
    async def _get_or_create_customer(self, user_id: int) -> str:
        """Get existing Stripe customer or create new one"""
        # Check if customer exists in database
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT email, stripe_customer_id FROM users WHERE id = ?",
                (user_id,)
            )
            user = cursor.fetchone()
        
        if not user:
            raise ValueError(f"User {user_id} not found")
        
        email = user[0]
        stripe_customer_id = user[1] if len(user) > 1 else None
        
        if stripe_customer_id:
            return stripe_customer_id
        
        # Create new Stripe customer
        customer = await asyncio.to_thread(
            stripe.Customer.create,
            email=email,
            metadata={'user_id': user_id}
        )
        
        # Store customer ID
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET stripe_customer_id = ? WHERE id = ?",
                (customer.id, user_id)
            )
            conn.commit()
        
        return customer.id
    
    async def handle_webhook(self, payload: bytes, signature: str) -> dict:
        """Handle Stripe webhook events"""
        try:
            # Verify webhook signature
            event = stripe.Webhook.construct_event(
                payload, signature, self.webhook_secret
            )
            
            event_type = event['type']
            
            if event_type == 'payment_intent.succeeded':
                await self._handle_payment_succeeded(event['data']['object'])
            elif event_type == 'payment_intent.payment_failed':
                await self._handle_payment_failed(event['data']['object'])
            
            return {'status': 'success'}
            
        except stripe.error.SignatureVerificationError as e:
            logger.error(f"Invalid webhook signature: {e}")
            return {'status': 'error', 'message': 'Invalid signature'}
        except Exception as e:
            logger.error(f"Error handling Stripe webhook: {e}")
            return {'status': 'error', 'message': str(e)}
    
    async def _handle_payment_succeeded(self, payment_intent: dict):
        """Handle successful payment"""
        logger.info(f"Payment succeeded: {payment_intent['id']}")
    
    async def _handle_payment_failed(self, payment_intent: dict):
        """Handle failed payment"""
        logger.warning(f"Payment failed: {payment_intent['id']}")
