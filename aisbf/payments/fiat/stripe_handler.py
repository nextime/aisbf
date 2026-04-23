"""
Stripe payment integration
"""
import logging
import stripe
import asyncio
from decimal import Decimal
from typing import Optional, Dict, Any

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
                ph = '?' if self.db.db_type == 'sqlite' else '%s'
                cursor.execute(f"""
                    INSERT INTO payment_methods
                    (user_id, type, identifier, is_default, is_active)
                    VALUES ({ph}, 'stripe', {ph}, 1, 1)
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
        ph = '?' if self.db.db_type == 'sqlite' else '%s'
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"SELECT email, stripe_customer_id FROM users WHERE id = {ph}",
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
                f"UPDATE users SET stripe_customer_id = {ph} WHERE id = {ph}",
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
    
    async def create_topup_intent(self, user_id: int, amount: Decimal, payment_method_id: str = None) -> dict:
        """Create Stripe PaymentIntent for wallet top up"""
        try:
            customer_id = await self._get_or_create_customer(user_id)
            amount_cents = int(amount * 100)

            intent_params = {
                'amount': amount_cents,
                'currency': self.config.get('currency_code', 'usd').lower(),
                'customer': customer_id,
                'description': f'Wallet top up: ${amount:.2f}',
                'metadata': {
                    'user_id': str(user_id),
                    'topup': 'true',
                    'amount': str(amount)
                }
            }

            if payment_method_id:
                intent_params['payment_method'] = payment_method_id
                intent_params['confirm'] = True

            payment_intent = await asyncio.to_thread(
                stripe.PaymentIntent.create,
                **intent_params
            )

            logger.info(f"Created Stripe top up intent for user {user_id}: {payment_intent.id}")

            return {
                'success': True,
                'payment_intent_id': payment_intent.id,
                'client_secret': payment_intent.client_secret,
                'amount': amount,
                'payment_method': 'stripe'
            }

        except Exception as e:
            logger.error(f"Error creating Stripe top up intent: {e}")
            return {'success': False, 'error': str(e)}

    async def create_topup_checkout_session(self, user_id: int, amount: Decimal, success_url: str, cancel_url: str) -> dict:
        """Create a Stripe Checkout Session for wallet top-up (hosted redirect flow)."""
        try:
            customer_id = await self._get_or_create_customer(user_id)
            currency = self.config.get('currency_code', 'usd').lower()
            session = await asyncio.to_thread(
                stripe.checkout.Session.create,
                customer=customer_id,
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': currency,
                        'product_data': {'name': 'Wallet Top-Up'},
                        'unit_amount': int(amount * 100),
                    },
                    'quantity': 1,
                }],
                mode='payment',
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    'user_id': str(user_id),
                    'topup': 'true',
                    'amount': str(amount),
                },
                payment_intent_data={
                    'metadata': {
                        'user_id': str(user_id),
                        'topup': 'true',
                        'amount': str(amount),
                    },
                },
            )
            logger.info(f"Created Stripe checkout session for user {user_id}: {session.id}")
            return {'success': True, 'checkout_url': session.url, 'session_id': session.id}
        except Exception as e:
            logger.error(f"Error creating Stripe checkout session: {e}")
            return {'success': False, 'error': str(e)}

    async def _handle_payment_succeeded(self, payment_intent: dict):
        """Handle successful Stripe payment — credits user wallet for top-up intents."""
        logger.info(f"Payment succeeded: {payment_intent['id']}")

        metadata = payment_intent.get('metadata', {})
        if metadata.get('topup') != 'true':
            return

        try:
            user_id = int(metadata['user_id'])
            amount = Decimal(metadata['amount'])
        except (KeyError, ValueError) as e:
            logger.error(f"Stripe webhook: missing/invalid metadata on {payment_intent['id']}: {e}")
            return

        from aisbf.payments.wallet.manager import WalletManager
        wallet_manager = WalletManager(self.db)
        await wallet_manager.credit_wallet(
            user_id=user_id,
            amount=amount,
            transaction_details={
                'payment_gateway': 'stripe',
                'gateway_transaction_id': payment_intent['id'],
                'description': 'Wallet top up via Stripe',
                'metadata': {'payment_intent': payment_intent['id']}
            }
        )
        logger.info(f"Wallet credited: user={user_id}, amount={amount}, intent={payment_intent['id']}")

    async def auto_charge(self, user_id: int, amount: Decimal, payment_method_id: str,
                          description: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None,
                          off_session: bool = True) -> Dict[str, Any]:
        """Charge a saved payment method immediately.

        Use off_session=False when the customer is actively present (e.g. clicking
        an upgrade button) so the charge is treated as a Customer-Initiated
        Transaction and settles at normal speed.  Use off_session=True only for
        background charges (auto-renewals, auto top-ups) where the customer is
        not present.
        """
        try:
            customer_id = await self._get_or_create_customer(user_id)
            amount_cents = int(amount * 100)

            intent_params = dict(
                amount=amount_cents,
                currency=self.config.get('currency_code', 'usd').lower(),
                customer=customer_id,
                payment_method=payment_method_id,
                confirm=True,
                description=description or f'Charge: ${amount:.2f}',
                metadata=metadata or {'user_id': str(user_id), 'amount': str(amount)}
            )
            if off_session:
                intent_params['off_session'] = True

            payment_intent = await asyncio.to_thread(
                stripe.PaymentIntent.create,
                **intent_params
            )

            if payment_intent.status not in ('succeeded', 'processing'):
                logger.error(f"Unexpected PaymentIntent status for user {user_id}: {payment_intent.status} ({payment_intent.id})")
                return {"success": False, "error": f"Payment not completed (status: {payment_intent.status})"}

            logger.info(f"Auto charge successful for user {user_id}: {payment_intent.id} status={payment_intent.status}")
            return {
                "success": True,
                "gateway_transaction_id": payment_intent.id,
                "amount": amount
            }

        except stripe.error.CardError as e:
            logger.error(f"Auto charge card error for user {user_id}: {e.user_message}")
            return {"success": False, "error": e.user_message}
        except Exception as e:
            logger.error(f"Auto charge failed for user {user_id}: {e}")
            return {"success": False, "error": str(e)}

    async def _handle_payment_failed(self, payment_intent: dict):
        """Handle failed payment"""
        logger.warning(f"Payment failed: {payment_intent['id']}")
