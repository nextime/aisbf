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

Why did the programmer quit his job? Because he didn't get arrays!
"""
import smtplib
import hashlib
import secrets
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
import logging

logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    """
    Hash a password using SHA256.
    
    Args:
        password: Plain text password
        
    Returns:
        SHA256 hash of the password
    """
    return hashlib.sha256(password.encode()).hexdigest()


def generate_verification_token() -> str:
    """
    Generate a secure random verification token.
    
    Returns:
        Random token string (32 bytes hex)
    """
    return secrets.token_hex(32)


def send_verification_email(
    to_email: str,
    username: str,
    verification_token: str,
    base_url: str,
    smtp_config: dict
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
        verification_url = f"{base_url}/dashboard/verify-email?token={verification_token}"
        
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = 'Verify your AISBF account'
        msg['From'] = f"{smtp_config.get('from_name', 'AISBF')} <{smtp_config.get('from_email')}>"
        msg['To'] = to_email
        
        # Create plain text and HTML versions
        text = f"""
Hello {username},

Thank you for signing up for AISBF!

Please verify your email address by clicking the link below:

{verification_url}

This link will expire in {smtp_config.get('verification_token_expiry_hours', 24)} hours.

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
    <p>This link will expire in {smtp_config.get('verification_token_expiry_hours', 24)} hours.</p>
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
        
        # Send email
        if smtp_config.get('use_ssl', False):
            # Use SSL
            with smtplib.SMTP_SSL(smtp_config['host'], smtp_config['port']) as server:
                if smtp_config.get('username') and smtp_config.get('password'):
                    server.login(smtp_config['username'], smtp_config['password'])
                server.send_message(msg)
        else:
            # Use TLS or no encryption
            with smtplib.SMTP(smtp_config['host'], smtp_config['port']) as server:
                if smtp_config.get('use_tls', True):
                    server.starttls()
                if smtp_config.get('username') and smtp_config.get('password'):
                    server.login(smtp_config['username'], smtp_config['password'])
                server.send_message(msg)
        
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
    smtp_config: dict
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
        msg['From'] = f"{smtp_config.get('from_name', 'AISBF')} <{smtp_config.get('from_email')}>"
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
        
        # Send email
        if smtp_config.get('use_ssl', False):
            # Use SSL
            with smtplib.SMTP_SSL(smtp_config['host'], smtp_config['port']) as server:
                if smtp_config.get('username') and smtp_config.get('password'):
                    server.login(smtp_config['username'], smtp_config['password'])
                server.send_message(msg)
        else:
            # Use TLS or no encryption
            with smtplib.SMTP(smtp_config['host'], smtp_config['port']) as server:
                if smtp_config.get('use_tls', True):
                    server.starttls()
                if smtp_config.get('username') and smtp_config.get('password'):
                    server.login(smtp_config['username'], smtp_config['password'])
                server.send_message(msg)
        
        logger.info(f"Password reset email sent to {to_email}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send password reset email to {to_email}: {e}")
        return False
