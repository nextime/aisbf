
"""
Copyleft (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

Email utilities for sending verification emails and notifications.

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""
import smtplib
import hashlib
import secrets
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
import logging
import traceback
import sys
from aisbf.config import SMTPConfig

logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    """Hash a password. Delegates to database._hash_password (bcrypt when available)."""
    from aisbf.database import _hash_password
    return _hash_password(password)


def generate_verification_token() -> str:
    """
    Generate a secure random verification token.

    Returns:
        Random token string (32 bytes hex)
    """
    return secrets.token_hex(32)


def generate_password_reset_token() -> str:
    """
    Generate a secure random password reset token.

    Returns:
        Random token string (32 bytes hex)
    """
    return generate_verification_token()


def send_verification_email(
    to_email: str,
    username: str,
    verification_token: str,
    base_url: str,
    smtp_config: SMTPConfig
) -> bool:
    """
    Send email verification email to a user.
    
    Args:
        to_email: Recipient email address
        username: Username of the user
        verification_token: Verification token
        base_url: Base URL of the application
        smtp_config: SMTP configuration dictionary
        
    Returns:
        True if email sent successfully, False otherwise
    """
    try:
        # Create verification URL
        verification_url = f"{base_url}/dashboard/verify-email?token={verification_token}&email={to_email}"
        
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = 'Verify your AISBF account'
        msg['From'] = f"{smtp_config.from_name} <{smtp_config.from_email}>"
        msg['To'] = to_email
        
        # Create plain text and HTML versions
        text = f"""
Hello {username},

Thank you for signing up for AISBF!

Please verify your email address by clicking the link below:

 {verification_url}

 This link will expire in 24 hours.

If you did not create this account, please ignore this email.

Best regards,
AISBF Team
"""
        
        html = f"""
<html>
  <head></head>
  <body>
    <h2>Hello {username},</h2>
    <p>Thank you for signing up for AISBF!</p>
    <p>Please verify your email address by clicking the button below:</p>
    <p style="margin: 30px 0;">
      <a href="{verification_url}" 
         style="background-color: #4CAF50; color: white; padding: 14px 20px; 
                text-decoration: none; border-radius: 4px; display: inline-block;">
        Verify Email Address
      </a>
    </p>
    <p>Or copy and paste this link into your browser:</p>
    <p><a href="{verification_url}">{verification_url}</a></p>
    <p>This link will expire in 24 hours.</p>
    <p>If you did not create this account, please ignore this email.</p>
    <br>
    <p>Best regards,<br>AISBF Team</p>
  </body>
</html>
"""
        
        # Attach parts
        part1 = MIMEText(text, 'plain')
        part2 = MIMEText(html, 'html')
        msg.attach(part1)
        msg.attach(part2)
        
        logger.debug(f"SMTP Config:")
        logger.debug(f"  Host: {smtp_config.host}")
        logger.debug(f"  Port: {smtp_config.port}")
        logger.debug(f"  Use SSL: {smtp_config.use_ssl}")
        logger.debug(f"  Use TLS: {smtp_config.use_tls}")
        logger.debug(f"  Username: {smtp_config.username}")
        logger.debug(f"  Password length: {len(smtp_config.password)} chars")
        logger.debug(f"  From Email: {smtp_config.from_email}")
        logger.debug(f"  From Name: {smtp_config.from_name}")

        # Send email
        if smtp_config.use_ssl:
            # Use SSL
            logger.debug("Connecting with SSL")
            with smtplib.SMTP_SSL(smtp_config.host, smtp_config.port) as server:
                server.set_debuglevel(1)
                if smtp_config.username and smtp_config.password:
                    logger.debug("Sending EHLO")
                    server.ehlo()
                    logger.debug(f"Logging in with user: {smtp_config.username}")
                    server.login(smtp_config.username, smtp_config.password)
                logger.debug("Sending message")
                server.send_message(msg)
                logger.debug("Message sent successfully")
        else:
            # Use TLS or no encryption
            logger.debug("Connecting plaintext")
            with smtplib.SMTP(smtp_config.host, smtp_config.port) as server:
                server.set_debuglevel(1)
                logger.debug("Sending EHLO")
                server.ehlo()
                if smtp_config.use_tls:
                    logger.debug("Starting TLS")
                    server.starttls()
                    logger.debug("Sending EHLO after STARTTLS")
                    server.ehlo()
                if smtp_config.username and smtp_config.password:
                    logger.debug(f"Logging in with user: {smtp_config.username}")
                    server.login(smtp_config.username, smtp_config.password)
                logger.debug("Sending message")
                server.send_message(msg)
                logger.debug("Message sent successfully")
        
        logger.info(f"Verification email sent to {to_email}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send verification email to {to_email}: {e}")
        return False


def send_password_reset_email(
    to_email: str,
    username: str,
    reset_token: str,
    base_url: str,
    smtp_config: SMTPConfig
) -> bool:
    """
    Send password reset email to a user.
    
    Args:
        to_email: Recipient email address
        username: Username of the user
        reset_token: Password reset token
        base_url: Base URL of the application
        smtp_config: SMTP configuration dictionary
        
    Returns:
        True if email sent successfully, False otherwise
    """
    try:
        # Create reset URL
        reset_url = f"{base_url}/dashboard/reset-password?token={reset_token}"
        
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = 'Reset your AISBF password'
        msg['From'] = f"{smtp_config.from_name} <{smtp_config.from_email}>"
        msg['To'] = to_email
        
        # Create plain text and HTML versions
        text = f"""
Hello {username},

You requested to reset your password for your AISBF account.

Please click the link below to reset your password:

{reset_url}

This link will expire in 1 hour.

If you did not request a password reset, please ignore this email.

Best regards,
AISBF Team
"""
        
        html = f"""
<html>
  <head></head>
  <body>
    <h2>Hello {username},</h2>
    <p>You requested to reset your password for your AISBF account.</p>
    <p>Please click the button below to reset your password:</p>
    <p style="margin: 30px 0;">
      <a href="{reset_url}" 
         style="background-color: #2196F3; color: white; padding: 14px 20px; 
                text-decoration: none; border-radius: 4px; display: inline-block;">
        Reset Password
      </a>
    </p>
    <p>Or copy and paste this link into your browser:</p>
    <p><a href="{reset_url}">{reset_url}</a></p>
    <p>This link will expire in 1 hour.</p>
    <p>If you did not request a password reset, please ignore this email.</p>
    <br>
    <p>Best regards,<br>AISBF Team</p>
  </body>
</html>
"""
        
        # Attach parts
        part1 = MIMEText(text, 'plain')
        part2 = MIMEText(html, 'html')
        msg.attach(part1)
        msg.attach(part2)
        
        logger.debug(f"SMTP Config:")
        logger.debug(f"  Host: {smtp_config.host}")
        logger.debug(f"  Port: {smtp_config.port}")
        logger.debug(f"  Use SSL: {smtp_config.use_ssl}")
        logger.debug(f"  Use TLS: {smtp_config.use_tls}")
        logger.debug(f"  Username: {smtp_config.username}")
        logger.debug(f"  Password length: {len(smtp_config.password)} chars")
        logger.debug(f"  From Email: {smtp_config.from_email}")
        logger.debug(f"  From Name: {smtp_config.from_name}")

        # Send email
        if smtp_config.use_ssl:
            # Use SSL
            logger.debug("Connecting with SSL")
            with smtplib.SMTP_SSL(smtp_config.host, smtp_config.port) as server:
                server.set_debuglevel(1)
                if smtp_config.username and smtp_config.password:
                    logger.debug("Sending EHLO")
                    server.ehlo()
                    logger.debug(f"Logging in with user: {smtp_config.username}")
                    server.login(smtp_config.username, smtp_config.password)
                logger.debug("Sending message")
                server.send_message(msg)
                logger.debug("Message sent successfully")
        else:
            # Use TLS or no encryption
            logger.debug("Connecting plaintext")
            with smtplib.SMTP(smtp_config.host, smtp_config.port) as server:
                server.set_debuglevel(1)
                logger.debug("Sending EHLO")
                server.ehlo()
                if smtp_config.use_tls:
                    logger.debug("Starting TLS")
                    server.starttls()
                    logger.debug("Sending EHLO after STARTTLS")
                    server.ehlo()
                if smtp_config.username and smtp_config.password:
                    logger.debug(f"Logging in with user: {smtp_config.username}")
                    server.login(smtp_config.username, smtp_config.password)
                logger.debug("Sending message")
                server.send_message(msg)
                logger.debug("Message sent successfully")
        
        logger.info(f"Password reset email sent to {to_email}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send password reset email to {to_email}: {e}")
        return False


def send_test_email(
    to_email: str,
    smtp_config: SMTPConfig
) -> bool:
    """
    Send a test email to verify SMTP configuration.
    
    Args:
        to_email: Recipient email address
        smtp_config: SMTP configuration dictionary
        
    Returns:
        True if email sent successfully, False otherwise
    """
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = 'AISBF SMTP Test Email'
        msg['From'] = f"{smtp_config.from_name} <{smtp_config.from_email}>"
        msg['To'] = to_email
        
        text = """
This is a test email sent from your AISBF server.

If you received this email, your SMTP configuration is working correctly!

Best regards,
AISBF Team
"""
        
        html = """
<html>
  <head></head>
  <body>
    <h2>AISBF SMTP Test Email</h2>
    <p>This is a test email sent from your AISBF server.</p>
    <p style="color: #4CAF50; font-weight: bold;">✅ If you received this email, your SMTP configuration is working correctly!</p>
    <br>
    <p>Best regards,<br>AISBF Team</p>
  </body>
</html>
"""
        
        part1 = MIMEText(text, 'plain')
        part2 = MIMEText(html, 'html')
        msg.attach(part1)
        msg.attach(part2)
        
        logger.info(f"Sending test email to {to_email}")
        
        logger.info(f"SMTP Config:")
        logger.info(f"  Host: {smtp_config.host}")
        logger.info(f"  Port: {smtp_config.port}")
        logger.info(f"  Use SSL: {smtp_config.use_ssl}")
        logger.info(f"  Use TLS: {smtp_config.use_tls}")
        logger.info(f"  Username: {smtp_config.username}")
        logger.info(f"  Password length: {len(smtp_config.password)} chars")
        logger.info(f"  From Email: {smtp_config.from_email}")
        logger.info(f"  From Name: {smtp_config.from_name}")

        # Enable SMTP debug logging at INFO level always
        old_stdout = sys.stdout
        log_buffer = []
        
        class LogBuffer:
            def write(self, data):
                line = data.strip()
                if line:
                    log_buffer.append(line)
                    logger.info(f"SMTP: {line}")
            def flush(self):
                pass
        
        sys.stdout = LogBuffer()
        
        try:
            # Send email
            if smtp_config.use_ssl:
                # Use SSL
                logger.info("Connecting with SSL")
                with smtplib.SMTP_SSL(smtp_config.host, smtp_config.port) as server:
                    server.set_debuglevel(2)
                    if smtp_config.username and smtp_config.password:
                        logger.info("Sending EHLO")
                        server.ehlo()
                        logger.info(f"Logging in with user: {smtp_config.username}")
                        server.login(smtp_config.username, smtp_config.password)
                    logger.info("Sending message")
                    server.send_message(msg)
                    logger.info("Message sent successfully")
            else:
                # Use TLS or no encryption
                logger.info("Connecting plaintext")
                with smtplib.SMTP(smtp_config.host, smtp_config.port) as server:
                    server.set_debuglevel(2)
                    logger.info("Sending EHLO")
                    server.ehlo()
                    if smtp_config.use_tls:
                        logger.info("Starting TLS")
                        server.starttls()
                        logger.info("Sending EHLO after STARTTLS")
                        server.ehlo()
                    if smtp_config.username and smtp_config.password:
                        logger.info(f"Logging in with user: {smtp_config.username}")
                        server.login(smtp_config.username, smtp_config.password)
                    logger.info("Sending message")
                    server.send_message(msg)
                    logger.info("Message sent successfully")
        finally:
            sys.stdout = old_stdout
        
        logger.info(f"Test email sent successfully to {to_email}")
        return True
        
    except smtplib.SMTPException as e:
        logger.error(f"SMTP Error sending test email to {to_email}: {e}")
        logger.error(f"SMTP Code: {e.smtp_code}, Message: {e.smtp_error}")
        logger.error(f"SMTP Server Response: {getattr(e, 'resp', 'N/A')}")
        return False
    except Exception as e:
        logger.error(f"Exception sending test email to {to_email}: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False
