"""
Copyleft (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

Utility functions for AISBF.

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

Utility functions for AISBF.
"""
from typing import Dict, List, Optional
from langchain_text_splitters import TokenTextSplitter
from .config import config


def count_messages_tokens(messages: List[Dict], model: str) -> int:
    """
    Count the total number of tokens in a list of messages.
    
    This function uses tiktoken for accurate token counting.
    
    Args:
        messages: List of message dictionaries with 'role' and 'content' keys
        model: Model name to determine encoding
    
    Returns:
        Total token count across all messages
    """
    import tiktoken
    import logging
    logger = logging.getLogger(__name__)
    
    # Select encoding based on model
    # OpenAI models use cl100k_base encoding
    if model.startswith(('gpt-', 'text-', 'davinci-', 'ada-', 'babbage-', 'curie-')):
        try:
            encoding = tiktoken.encoding_for_model(model)
        except KeyError:
            # Fallback to cl100k_base if model not found
            encoding = tiktoken.get_encoding("cl100k_base")
    else:
        # Default encoding for other models
        encoding = tiktoken.get_encoding("cl100k_base")
    
    total_tokens = 0
    for msg in messages:
        content = msg.get('content', '')
        if content:
            if isinstance(content, str):
                total_tokens += len(encoding.encode(content))
            elif isinstance(content, list):
                # Handle complex content (e.g., with images)
                for item in content:
                    if isinstance(item, dict):
                        text = item.get('text', '')
                        if text:
                            total_tokens += len(encoding.encode(text))
                    elif isinstance(item, str):
                        total_tokens += len(encoding.encode(item))
    
    logger.debug(f"Token count for model {model}: {total_tokens}")
    return total_tokens


def split_messages_into_chunks(messages: List[Dict], max_tokens: int, model: str) -> List[List[Dict]]:
    """
    Split messages into chunks based on token limit using langchain-text-splitters.
    
    This function uses TokenTextSplitter to intelligently split text while
    maintaining context through overlap between chunks.
    
    Args:
        messages: List of message dictionaries with 'role' and 'content' keys
        max_tokens: Maximum tokens per chunk
        model: Model name (used for logging)
    
    Returns:
        List of message chunks, where each chunk is a list of messages
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # Combine all messages into a single text for splitting
    combined_text = ""
    for msg in messages:
        role = msg.get('role', 'user')
        content = msg.get('content', '')
        if content:
            if isinstance(content, str):
                combined_text += f"{role}: {content}\n\n"
            elif isinstance(content, list):
                # Handle complex content
                for item in content:
                    if isinstance(item, dict):
                        text = item.get('text', '')
                        if text:
                            combined_text += f"{role}: {text}\n\n"
                    elif isinstance(item, str):
                        combined_text += f"{role}: {item}\n\n"
    
    # Use langchain-text-splitters for intelligent text splitting
    # chunk_size: Set slightly below max_tokens to allow room for model output
    # chunk_overlap: Shared tokens between chunks for context continuity
    text_splitter = TokenTextSplitter(
        chunk_size=max_tokens - 200,  # Leave room for model output
        chunk_overlap=100,  # Helps model understand transition between chunks
        length_function=len  # Use character count as proxy for token count
    )
    
    # Split text into chunks
    text_chunks = text_splitter.split_text(combined_text)
    
    logger.info(f"Split text into {len(text_chunks)} chunks using langchain-text-splitters")
    logger.info(f"Max tokens per chunk: {max_tokens}, Chunk overlap: 100")
    
    # Convert text chunks back to message format
    message_chunks = []
    for i, chunk_text in enumerate(text_chunks):
        # Create a single user message with the chunk content
        chunk_messages = [{"role": "user", "content": chunk_text}]
        message_chunks.append(chunk_messages)
        logger.debug(f"Chunk {i+1}: {len(chunk_text)} characters")
    
    return message_chunks


def get_max_request_tokens_for_model(
    model_name: str,
    provider_config,
    rotation_model_config: Optional[Dict] = None
) -> Optional[int]:
    """
    Get the max_request_tokens for a model from provider or rotation configuration.
    
    Priority order:
    1. Check rotation model config (if provided)
    2. Check provider models config
    
    Args:
        model_name: The model name to look up
        provider_config: The provider configuration
        rotation_model_config: Optional model config from rotation
    
    Returns:
        The max_request_tokens value, or None if not configured
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # First check rotation model config (highest priority)
    if rotation_model_config and 'max_request_tokens' in rotation_model_config:
        max_tokens = rotation_model_config['max_request_tokens']
        logger.info(f"Found max_request_tokens in rotation model config: {max_tokens}")
        return max_tokens
    
    # Then check provider models config
    if hasattr(provider_config, 'models') and provider_config.models:
        for model in provider_config.models:
            # Handle both Pydantic objects and dictionaries
            model_name_value = model.name if hasattr(model, 'name') else model.get('name')
            if model_name_value == model_name:
                max_tokens = model.max_request_tokens if hasattr(model, 'max_request_tokens') else model.get('max_request_tokens')
                if max_tokens:
                    logger.info(f"Found max_request_tokens in provider model config: {max_tokens}")
                    return max_tokens
                if max_tokens:
                    logger.info(f"Found max_request_tokens in provider model config: {max_tokens}")
                    return max_tokens
    
    logger.debug(f"No max_request_tokens configured for model {model_name}")
    return None


def generate_self_signed_certificate(cert_path: str, key_path: str) -> bool:
    """
    Generate a self-signed SSL certificate and private key.
    
    Args:
        cert_path: Path where the certificate should be saved
        key_path: Path where the private key should be saved
    
    Returns:
        True if successful, False otherwise
    """
    import logging
    from pathlib import Path
    logger = logging.getLogger(__name__)
    
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        import datetime
        
        logger.info(f"Generating self-signed SSL certificate...")
        logger.info(f"Certificate path: {cert_path}")
        logger.info(f"Key path: {key_path}")
        
        # Generate private key
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        
        # Create certificate
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "State"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, "City"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "AISBF"),
            x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
        ])
        
        cert = x509.CertificateBuilder().subject_name(
            subject
        ).issuer_name(
            issuer
        ).public_key(
            private_key.public_key()
        ).serial_number(
            x509.random_serial_number()
        ).not_valid_before(
            datetime.datetime.utcnow()
        ).not_valid_after(
            datetime.datetime.utcnow() + datetime.timedelta(days=365)
        ).add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.DNSName("127.0.0.1"),
            ]),
            critical=False,
        ).sign(private_key, hashes.SHA256())
        
        # Ensure directories exist
        Path(cert_path).parent.mkdir(parents=True, exist_ok=True)
        Path(key_path).parent.mkdir(parents=True, exist_ok=True)
        
        # Write certificate to file
        with open(cert_path, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
        
        # Write private key to file
        with open(key_path, "wb") as f:
            f.write(private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption()
            ))
        
        logger.info(f"Successfully generated self-signed SSL certificate")
        logger.info(f"Certificate valid for 365 days")
        return True
        
    except ImportError:
        logger.error("cryptography library not installed. Cannot generate self-signed certificate.")
        logger.error("Install with: pip install cryptography")
        return False
    except Exception as e:
        logger.error(f"Error generating self-signed certificate: {e}", exc_info=True)
        return False


def check_certificate_expiry(cert_path: str) -> Optional[int]:
    """
    Check how many days until certificate expires.
    
    Args:
        cert_path: Path to certificate file
    
    Returns:
        Number of days until expiry, or None if cannot be determined
    """
    import logging
    from pathlib import Path
    logger = logging.getLogger(__name__)
    
    try:
        from cryptography import x509
        from cryptography.hazmat.backends import default_backend
        import datetime
        
        if not Path(cert_path).exists():
            return None
        
        with open(cert_path, 'rb') as f:
            cert_data = f.read()
        
        cert = x509.load_pem_x509_certificate(cert_data, default_backend())
        expiry_date = cert.not_valid_after
        days_until_expiry = (expiry_date - datetime.datetime.utcnow()).days
        
        logger.info(f"Certificate expires in {days_until_expiry} days")
        return days_until_expiry
        
    except Exception as e:
        logger.error(f"Error checking certificate expiry: {e}")
        return None


def generate_letsencrypt_certificate(domain: str, cert_path: str, key_path: str, email: Optional[str] = None) -> bool:
    """
    Generate Let's Encrypt SSL certificate using certbot.
    
    Args:
        domain: Public domain name
        cert_path: Path where certificate should be saved
        key_path: Path where private key should be saved
        email: Optional email for Let's Encrypt notifications
    
    Returns:
        True if successful, False otherwise
    """
    import logging
    import subprocess
    from pathlib import Path
    logger = logging.getLogger(__name__)
    
    try:
        logger.info(f"Generating Let's Encrypt certificate for domain: {domain}")
        
        # Check if certbot is installed
        try:
            subprocess.run(['certbot', '--version'], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.error("certbot not found. Please install certbot:")
            logger.error("  Ubuntu/Debian: sudo apt-get install certbot")
            logger.error("  CentOS/RHEL: sudo yum install certbot")
            logger.error("  macOS: brew install certbot")
            return False
        
        # Prepare certbot command
        config_dir = Path.home() / '.aisbf' / 'letsencrypt'
        config_dir.mkdir(parents=True, exist_ok=True)
        
        cmd = [
            'certbot', 'certonly',
            '--standalone',
            '--non-interactive',
            '--agree-tos',
            '--domain', domain,
            '--config-dir', str(config_dir),
            '--work-dir', str(config_dir / 'work'),
            '--logs-dir', str(config_dir / 'logs'),
        ]
        
        if email:
            cmd.extend(['--email', email])
        else:
            cmd.append('--register-unsafely-without-email')
        
        logger.info(f"Running certbot command...")
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            logger.error(f"certbot failed: {result.stderr}")
            return False
        
        # Copy certificates to specified paths
        le_cert = config_dir / 'live' / domain / 'fullchain.pem'
        le_key = config_dir / 'live' / domain / 'privkey.pem'
        
        if le_cert.exists() and le_key.exists():
            import shutil
            shutil.copy2(le_cert, cert_path)
            shutil.copy2(le_key, key_path)
            logger.info(f"Let's Encrypt certificate generated successfully")
            logger.info(f"Certificate valid for 90 days")
            return True
        else:
            logger.error(f"Certificate files not found after certbot execution")
            return False
            
    except Exception as e:
        logger.error(f"Error generating Let's Encrypt certificate: {e}", exc_info=True)
        return False


def renew_letsencrypt_certificate(domain: str, cert_path: str, key_path: str) -> bool:
    """
    Renew Let's Encrypt SSL certificate.
    
    Args:
        domain: Public domain name
        cert_path: Path where certificate should be saved
        key_path: Path where private key should be saved
    
    Returns:
        True if successful, False otherwise
    """
    import logging
    import subprocess
    from pathlib import Path
    logger = logging.getLogger(__name__)
    
    try:
        logger.info(f"Renewing Let's Encrypt certificate for domain: {domain}")
        
        config_dir = Path.home() / '.aisbf' / 'letsencrypt'
        
        cmd = [
            'certbot', 'renew',
            '--config-dir', str(config_dir),
            '--work-dir', str(config_dir / 'work'),
            '--logs-dir', str(config_dir / 'logs'),
            '--non-interactive',
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            logger.error(f"certbot renew failed: {result.stderr}")
            return False
        
        # Copy renewed certificates
        le_cert = config_dir / 'live' / domain / 'fullchain.pem'
        le_key = config_dir / 'live' / domain / 'privkey.pem'
        
        if le_cert.exists() and le_key.exists():
            import shutil
            shutil.copy2(le_cert, cert_path)
            shutil.copy2(le_key, key_path)
            logger.info(f"Let's Encrypt certificate renewed successfully")
            return True
        else:
            logger.error(f"Renewed certificate files not found")
            return False
            
    except Exception as e:
        logger.error(f"Error renewing Let's Encrypt certificate: {e}", exc_info=True)
        return False


def ensure_ssl_certificates(cert_path: Optional[str] = None, key_path: Optional[str] = None,
                           public_domain: Optional[str] = None, email: Optional[str] = None) -> tuple:
    """
    Ensure SSL certificates exist, generating them if necessary.
    Uses Let's Encrypt if public_domain is provided, otherwise self-signed.
    Also checks expiry and renews if needed.
    
    Args:
        cert_path: Path to certificate file (None for default)
        key_path: Path to key file (None for default)
        public_domain: Public domain for Let's Encrypt (None for self-signed)
        email: Email for Let's Encrypt notifications (optional)
    
    Returns:
        Tuple of (cert_path, key_path) with resolved paths
    """
    import logging
    from pathlib import Path
    logger = logging.getLogger(__name__)
    
    # Use default paths if not specified
    config_dir = Path.home() / '.aisbf'
    if not cert_path:
        cert_path = str(config_dir / 'cert.pem')
    if not key_path:
        key_path = str(config_dir / 'key.pem')
    
    # Expand user paths
    cert_path = str(Path(cert_path).expanduser())
    key_path = str(Path(key_path).expanduser())
    
    # Check if certificates exist
    cert_exists = Path(cert_path).exists()
    key_exists = Path(key_path).exists()
    
    # Check certificate expiry if it exists
    needs_renewal = False
    if cert_exists:
        days_until_expiry = check_certificate_expiry(cert_path)
        if days_until_expiry is not None and days_until_expiry < 30:
            logger.warning(f"Certificate expires in {days_until_expiry} days, renewal needed")
            needs_renewal = True
    
    # Generate or renew certificate
    if not cert_exists or not key_exists or needs_renewal:
        if public_domain:
            # Try Let's Encrypt
            logger.info(f"Using Let's Encrypt for domain: {public_domain}")
            
            if needs_renewal:
                success = renew_letsencrypt_certificate(public_domain, cert_path, key_path)
            else:
                success = generate_letsencrypt_certificate(public_domain, cert_path, key_path, email)
            
            if not success:
                logger.warning(f"Let's Encrypt failed, falling back to self-signed certificate")
                if not generate_self_signed_certificate(cert_path, key_path):
                    raise FileNotFoundError(f"Failed to generate SSL certificates")
        else:
            # Generate self-signed certificate
            logger.info(f"Generating self-signed SSL certificate...")
            if not generate_self_signed_certificate(cert_path, key_path):
                raise FileNotFoundError(f"Failed to generate self-signed SSL certificate")
    else:
        logger.info(f"Using existing SSL certificate: {cert_path}")
        logger.info(f"Using existing SSL key: {key_path}")
    
    return cert_path, key_path