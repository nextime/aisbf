"""
Email Notification Service

Sends email notifications for payment events including payment success,
payment failure, subscription upgrades, downgrades, and cancellations.
Admin configurable per notification type.
"""
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class EmailNotificationService:
    """
    Sends email notifications for payment events.
    
    Supports configurable notification types with custom templates.
    Admin can enable/disable specific notification types.
    """
    
    # Notification types
    PAYMENT_SUCCESS = 'payment_success'
    PAYMENT_FAILED = 'payment_failed'
    SUBSCRIPTION_UPGRADED = 'subscription_upgraded'
    SUBSCRIPTION_DOWNGRADED = 'subscription_downgraded'
    SUBSCRIPTION_CANCELLED = 'subscription_cancelled'
    SUBSCRIPTION_RENEWED = 'subscription_renewed'
    SUBSCRIPTION_EXPIRING = 'subscription_expiring'
    
    def __init__(self, db_manager):
        """
        Initialize email notification service.
        
        Args:
            db_manager: DatabaseManager instance
        """
        self.db = db_manager
        self._smtp_config = None
    
    def _get_smtp_config(self) -> Optional[Dict]:
        """
        Get SMTP configuration from database.
        
        Returns:
            Dict with SMTP config or None if not configured
        """
        if self._smtp_config:
            return self._smtp_config
        
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT smtp_host, smtp_port, smtp_username, smtp_password,
                       from_email, from_name, use_tls
                FROM email_config
                LIMIT 1
            """)
            row = cursor.fetchone()
        
        if not row:
            logger.warning("No email configuration found")
            return None
        
        self._smtp_config = {
            'host': row[0],
            'port': row[1],
            'username': row[2],
            'password': row[3],
            'from_email': row[4],
            'from_name': row[5],
            'use_tls': bool(row[6])
        }
        
        return self._smtp_config
    
    def _is_notification_enabled(self, notification_type: str) -> bool:
        """
        Check if notification type is enabled.
        
        Args:
            notification_type: Type of notification
            
        Returns:
            True if enabled, False otherwise
        """
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
            
            cursor.execute(f"""
                SELECT is_enabled
                FROM email_notification_settings
                WHERE notification_type = {placeholder}
            """, (notification_type,))
            
            row = cursor.fetchone()
        
        return bool(row[0]) if row else False
    
    def _get_notification_template(self, notification_type: str) -> Optional[Dict]:
        """
        Get email template for notification type.
        
        Args:
            notification_type: Type of notification
            
        Returns:
            Dict with subject_template, template_html, template_text or None
        """
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
            
            cursor.execute(f"""
                SELECT s.subject_template, t.template_html, t.template_text
                FROM email_notification_settings s
                LEFT JOIN email_templates t ON s.notification_type = t.notification_type
                WHERE s.notification_type = {placeholder}
            """, (notification_type,))
            
            row = cursor.fetchone()
        
        if not row:
            return None
        
        return {
            'subject': row[0],
            'html': row[1],
            'text': row[2]
        }
    
    async def send_notification(
        self,
        user_id: int,
        notification_type: str,
        context: Dict
    ):
        """
        Send email notification to user.
        
        Args:
            user_id: User ID to send notification to
            notification_type: Type of notification
            context: Template context variables
        """
        # Check if notification is enabled
        if not self._is_notification_enabled(notification_type):
            logger.debug(f"Notification type {notification_type} is disabled")
            return
        
        # Get SMTP config
        smtp_config = self._get_smtp_config()
        if not smtp_config:
            logger.warning("Cannot send email: SMTP not configured")
            return
        
        # Get user email
        user_email = self._get_user_email(user_id)
        if not user_email:
            logger.warning(f"Cannot send email: No email for user {user_id}")
            return
        
        # Get template
        template = self._get_notification_template(notification_type)
        if not template:
            logger.warning(f"No template found for {notification_type}")
            return
        
        # Render template
        subject = self._render_template(template['subject'], context)
        html_body = self._render_template(template['html'], context) if template['html'] else None
        text_body = self._render_template(template['text'], context) if template['text'] else None
        
        # Send email
        try:
            await self._send_email(
                smtp_config,
                user_email,
                subject,
                html_body,
                text_body
            )
            logger.info(f"Sent {notification_type} notification to user {user_id}")
        except Exception as e:
            logger.error(f"Failed to send email to user {user_id}: {e}")
            # Queue for retry
            self._queue_notification(user_id, notification_type, context, str(e))
    
    def _get_user_email(self, user_id: int) -> Optional[str]:
        """Get user email address"""
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
            
            cursor.execute(f"""
                SELECT email FROM users WHERE id = {placeholder}
            """, (user_id,))
            
            row = cursor.fetchone()
        
        return row[0] if row else None
    
    def _render_template(self, template: str, context: Dict) -> str:
        """
        Simple template rendering using string formatting.
        
        Args:
            template: Template string with {variable} placeholders
            context: Dict of variables
            
        Returns:
            Rendered string
        """
        if not template:
            return ""
        
        try:
            return template.format(**context)
        except KeyError as e:
            logger.warning(f"Missing template variable: {e}")
            return template
    
    async def _send_email(
        self,
        smtp_config: Dict,
        to_email: str,
        subject: str,
        html_body: Optional[str],
        text_body: Optional[str]
    ):
        """
        Send email via SMTP.
        
        Args:
            smtp_config: SMTP configuration dict
            to_email: Recipient email address
            subject: Email subject
            html_body: HTML body (optional)
            text_body: Plain text body (optional)
        """
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"{smtp_config['from_name']} <{smtp_config['from_email']}>"
        msg['To'] = to_email
        
        # Add text body
        if text_body:
            msg.attach(MIMEText(text_body, 'plain'))
        
        # Add HTML body
        if html_body:
            msg.attach(MIMEText(html_body, 'html'))
        
        # Send via SMTP
        if smtp_config['use_tls']:
            server = smtplib.SMTP(smtp_config['host'], smtp_config['port'])
            server.starttls()
        else:
            server = smtplib.SMTP(smtp_config['host'], smtp_config['port'])
        
        try:
            if smtp_config['username'] and smtp_config['password']:
                server.login(smtp_config['username'], smtp_config['password'])
            
            server.send_message(msg)
        finally:
            server.quit()
    
    def _queue_notification(
        self,
        user_id: int,
        notification_type: str,
        context: Dict,
        error: str
    ):
        """
        Queue notification for retry.
        
        Args:
            user_id: User ID
            notification_type: Notification type
            context: Template context
            error: Error message
        """
        import json
        
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
            
            cursor.execute(f"""
                INSERT INTO email_notification_queue
                (user_id, notification_type, context_json, status, error_message, retry_count)
                VALUES ({placeholder}, {placeholder}, {placeholder}, 'pending', {placeholder}, 0)
            """, (user_id, notification_type, json.dumps(context), error))
            
            conn.commit()
    
    async def process_notification_queue(self):
        """
        Process queued notifications.
        
        Called by background scheduler to retry failed notifications.
        """
        logger.info("Processing notification queue...")
        
        try:
            # Get pending notifications
            pending = self._get_pending_notifications()
            
            if not pending:
                logger.debug("No pending notifications")
                return
            
            logger.info(f"Processing {len(pending)} pending notifications")
            
            for notification in pending:
                try:
                    await self.send_notification(
                        notification['user_id'],
                        notification['notification_type'],
                        notification['context']
                    )
                    self._mark_notification_sent(notification['id'])
                except Exception as e:
                    logger.error(f"Error sending notification {notification['id']}: {e}")
                    self._increment_retry_count(notification['id'], str(e))
            
            logger.info("Notification queue processing completed")
        except Exception as e:
            logger.error(f"Error processing notification queue: {e}", exc_info=True)
    
    def _get_pending_notifications(self) -> list:
        """Get pending notifications from queue"""
        import json
        from datetime import datetime, timedelta
        
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            
            # Get notifications ready for retry (not sent recently)
            cursor.execute("""
                SELECT id, user_id, notification_type, context_json, retry_count
                FROM email_notification_queue
                WHERE status = 'pending'
                AND retry_count < 5
                AND (next_retry_at IS NULL OR next_retry_at <= CURRENT_TIMESTAMP)
                ORDER BY created_at ASC
                LIMIT 10
            """)
            
            rows = cursor.fetchall()
        
        return [
            {
                'id': row[0],
                'user_id': row[1],
                'notification_type': row[2],
                'context': json.loads(row[3]),
                'retry_count': row[4]
            }
            for row in rows
        ]
    
    def _mark_notification_sent(self, notification_id: int):
        """Mark notification as sent"""
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
            
            cursor.execute(f"""
                UPDATE email_notification_queue
                SET status = 'sent', sent_at = CURRENT_TIMESTAMP
                WHERE id = {placeholder}
            """, (notification_id,))
            
            conn.commit()
    
    def _increment_retry_count(self, notification_id: int, error: str):
        """Increment retry count and schedule next retry"""
        from datetime import datetime, timedelta
        
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
            
            # Calculate next retry time (exponential backoff)
            cursor.execute(f"""
                SELECT retry_count FROM email_notification_queue
                WHERE id = {placeholder}
            """, (notification_id,))
            
            row = cursor.fetchone()
            retry_count = row[0] + 1 if row else 1
            
            # Exponential backoff: 5min, 15min, 1hr, 4hr, 12hr
            backoff_minutes = [5, 15, 60, 240, 720]
            delay_minutes = backoff_minutes[min(retry_count - 1, len(backoff_minutes) - 1)]
            
            if self.db.db_type == 'sqlite':
                next_retry = f"datetime('now', '+{delay_minutes} minutes')"
            else:
                next_retry = f"DATE_ADD(NOW(), INTERVAL {delay_minutes} MINUTE)"
            
            cursor.execute(f"""
                UPDATE email_notification_queue
                SET retry_count = retry_count + 1,
                    error_message = {placeholder},
                    next_retry_at = {next_retry}
                WHERE id = {placeholder}
            """, (error, notification_id))
            
            conn.commit()
    
    def _notify_admin(self, event_key: str, subject: str, body_html: str):
        """Send an email to the admin if that event type is enabled in config."""
        try:
            import json
            from pathlib import Path
            config_path = Path.home() / '.aisbf' / 'aisbf.json'
            if not config_path.exists():
                config_path = Path(__file__).parent.parent.parent / 'config' / 'aisbf.json'
            if not config_path.exists():
                return
            with open(config_path) as f:
                cfg = json.load(f)
            dashboard = cfg.get('dashboard', {})
            admin_email = dashboard.get('email', '')
            if not admin_email:
                return
            notifications = dashboard.get('notifications', {})
            if not notifications.get(event_key, False):
                return
            smtp = cfg.get('smtp', {})
            if not smtp.get('enabled', False) or not smtp.get('host'):
                return
            from aisbf.email_utils import send_simple_email

            class _SmtpCfg:
                pass

            smtp_cfg = _SmtpCfg()
            smtp_cfg.host = smtp.get('host', '')
            smtp_cfg.port = smtp.get('port', 587)
            smtp_cfg.username = smtp.get('username', '')
            smtp_cfg.password = smtp.get('password', '')
            smtp_cfg.use_tls = smtp.get('use_tls', True)
            smtp_cfg.use_ssl = smtp.get('use_ssl', False)
            smtp_cfg.from_email = smtp.get('from_email', '')
            smtp_cfg.from_name = smtp.get('from_name', 'AISBF')
            send_simple_email(admin_email, subject, body_html, smtp_cfg)
        except Exception as e:
            logger.warning(f"Admin notification ({event_key}): {e}")

    # Convenience methods for common notifications

    async def notify_payment_success(self, user_id: int, amount: float, currency: str):
        """Send payment success notification"""
        await self.send_notification(
            user_id,
            self.PAYMENT_SUCCESS,
            {
                'amount': amount,
                'currency': currency,
                'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
        )
        self._notify_admin(
            'payment_received',
            f"Payment received: {amount} {currency}",
            f"<h2>Payment Received</h2><p>User ID {user_id} completed a payment of <b>{amount} {currency}</b>.</p>"
        )

    async def notify_payment_failed(self, user_id: int, amount: float, currency: str, reason: str):
        """Send payment failed notification"""
        await self.send_notification(
            user_id,
            self.PAYMENT_FAILED,
            {
                'amount': amount,
                'currency': currency,
                'reason': reason,
                'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
        )

    async def notify_subscription_upgraded(self, user_id: int, old_tier: str, new_tier: str):
        """Send subscription upgraded notification"""
        await self.send_notification(
            user_id,
            self.SUBSCRIPTION_UPGRADED,
            {
                'old_tier': old_tier,
                'new_tier': new_tier,
                'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
        )
        self._notify_admin(
            'tier_upgrade',
            f"Subscription upgraded: {old_tier} → {new_tier}",
            f"<h2>Subscription Upgraded</h2><p>User ID {user_id} upgraded from <b>{old_tier}</b> to <b>{new_tier}</b>.</p>"
        )

    async def notify_subscription_downgraded(self, user_id: int, old_tier: str, new_tier: str):
        """Send subscription downgraded notification"""
        await self.send_notification(
            user_id,
            self.SUBSCRIPTION_DOWNGRADED,
            {
                'old_tier': old_tier,
                'new_tier': new_tier,
                'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
        )
        self._notify_admin(
            'tier_downgrade',
            f"Subscription downgraded: {old_tier} → {new_tier}",
            f"<h2>Subscription Downgraded</h2><p>User ID {user_id} downgraded from <b>{old_tier}</b> to <b>{new_tier}</b>.</p>"
        )

    async def notify_subscription_cancelled(self, user_id: int, tier: str, end_date: str):
        """Send subscription cancelled notification"""
        await self.send_notification(
            user_id,
            self.SUBSCRIPTION_CANCELLED,
            {
                'tier': tier,
                'end_date': end_date,
                'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
        )
        self._notify_admin(
            'subscription_expired',
            f"Subscription expired/cancelled: {tier}",
            f"<h2>Subscription Cancelled</h2><p>User ID {user_id} subscription <b>{tier}</b> was cancelled (expires {end_date}).</p>"
        )

    async def notify_subscription_renewed(self, user_id: int, tier: str, new_end_date: str):
        """Send subscription renewed notification"""
        await self.send_notification(
            user_id,
            self.SUBSCRIPTION_RENEWED,
            {
                'tier': tier,
                'new_end_date': new_end_date,
                'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
        )
        self._notify_admin(
            'subscription_renewed',
            f"Subscription renewed: {tier}",
            f"<h2>Subscription Renewed</h2><p>User ID {user_id} renewed <b>{tier}</b> subscription (next renewal: {new_end_date}).</p>"
        )
