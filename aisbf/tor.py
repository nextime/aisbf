"""
Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

TOR hidden service management for AISBF.

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

import logging
from pathlib import Path
from typing import Optional, Dict, Any
import os

logger = logging.getLogger(__name__)


class TorHiddenService:
    """
    Manages TOR hidden service for AISBF.
    
    This class handles:
    - Connection to TOR control port
    - Creation of hidden services (ephemeral or persistent)
    - Retrieval of onion addresses
    - Status monitoring
    """
    
    def __init__(self, tor_config):
        """
        Initialize TOR hidden service manager.
        
        Args:
            tor_config: TorConfig object with TOR settings
        """
        self.config = tor_config
        self.controller = None
        self.onion_address = None
        self.service_id = None
        self._is_connected = False
        
    def is_enabled(self) -> bool:
        """Check if TOR is enabled in configuration"""
        return self.config.enabled if self.config else False
    
    def is_connected(self) -> bool:
        """Check if connected to TOR control port"""
        return self._is_connected
    
    def connect(self) -> bool:
        """
        Connect to TOR control port.
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        if not self.is_enabled():
            logger.info("TOR is not enabled in configuration")
            return False
        
        try:
            from stem.control import Controller
            from stem import SocketError
            
            logger.info(f"Connecting to TOR control port at {self.config.control_host}:{self.config.control_port}")
            
            self.controller = Controller.from_port(
                address=self.config.control_host,
                port=self.config.control_port
            )
            
            # Authenticate
            if self.config.control_password and self.config.control_password.strip():
                logger.info("Authenticating with TOR control port using password")
                self.controller.authenticate(password=self.config.control_password)
            else:
                logger.info("Authenticating with TOR control port (no password)")
                self.controller.authenticate()
            
            self._is_connected = True
            logger.info("Successfully connected to TOR control port")
            return True
            
        except ImportError:
            logger.error("stem library not installed. Install with: pip install stem")
            return False
        except SocketError as e:
            logger.error(f"Failed to connect to TOR control port: {e}")
            logger.error("Make sure TOR is running and ControlPort is configured")
            return False
        except Exception as e:
            logger.error(f"Error connecting to TOR: {e}")
            return False
    
    def _check_existing_hidden_service(self, hidden_service_dir: Path) -> Optional[str]:
        """
        Check if a hidden service already exists in torrc and retrieve its onion address.
        
        Args:
            hidden_service_dir: Path to the hidden service directory
            
        Returns:
            str: Onion address if found, None otherwise
        """
        try:
            hostname_file = hidden_service_dir / 'hostname'
            if hostname_file.exists() and hostname_file.stat().st_size > 0:
                onion_address = hostname_file.read_text().strip()
                logger.info(f"Found existing hidden service: {onion_address}")
                return onion_address
        except Exception as e:
            logger.debug(f"Could not read existing hostname file: {e}")
        return None
    
    def _print_manual_configuration_instructions(self, hidden_service_dir: Path, local_port: int):
        """
        Print manual configuration instructions for persistent hidden service.
        
        Args:
            hidden_service_dir: Path to the hidden service directory
            local_port: Local port where AISBF is running
        """
        logger.error("=" * 80)
        logger.error("MANUAL CONFIGURATION REQUIRED")
        logger.error("=" * 80)
        logger.error("To set up a persistent Tor hidden service, add the following lines")
        logger.error("to your torrc file (usually /etc/tor/torrc):")
        logger.error("")
        logger.error(f"  HiddenServiceDir {hidden_service_dir}")
        logger.error(f"  HiddenServicePort {self.config.hidden_service_port} 127.0.0.1:{local_port}")
        logger.error("")
        logger.error("Then restart Tor:")
        logger.error("  sudo systemctl restart tor")
        logger.error("")
        logger.error("After Tor restarts, your onion address will be in:")
        logger.error(f"  {hidden_service_dir}/hostname")
        logger.error("=" * 80)
    
    def create_hidden_service(self, local_port: int) -> Optional[str]:
        """
        Create a TOR hidden service.
        
        Args:
            local_port: Local port where AISBF is running
            
        Returns:
            str: Onion address if successful, None otherwise
        """
        if not self._is_connected:
            logger.error("Not connected to TOR control port")
            return None
        
        try:
            from stem.control import Controller
            import time
            
            # Determine if we should use persistent or ephemeral hidden service
            if self.config.hidden_service_dir and self.config.hidden_service_dir.strip():
                # Persistent hidden service
                hidden_service_dir = Path(self.config.hidden_service_dir).expanduser().resolve()
                hidden_service_dir.mkdir(parents=True, exist_ok=True)
                
                logger.info(f"Setting up persistent hidden service in {hidden_service_dir}")
                
                # Check if hidden service already exists
                existing_address = self._check_existing_hidden_service(hidden_service_dir)
                if existing_address:
                    self.onion_address = existing_address
                    logger.info(f"Using existing persistent hidden service: {self.onion_address}")
                    return self.onion_address
                
                # Persistent hidden services must be configured in torrc
                logger.warning("Persistent hidden service not found")
                self._print_manual_configuration_instructions(hidden_service_dir, local_port)
                
                # Wait a bit to see if user configured it
                logger.info("Waiting 10 seconds for manual configuration...")
                logger.info("(Configure torrc now, or press Ctrl+C to cancel)")
                
                import time
                hostname_file = hidden_service_dir / 'hostname'
                
                for attempt in range(10):
                    time.sleep(1)
                    if hostname_file.exists() and hostname_file.stat().st_size > 0:
                        self.onion_address = hostname_file.read_text().strip()
                        logger.info(f"Persistent hidden service detected: {self.onion_address}")
                        return self.onion_address
                
                logger.error("Persistent hidden service not configured")
                logger.error("Please configure torrc manually and restart aisbf")
                return None
            else:
                # Ephemeral hidden service
                logger.info("Creating ephemeral hidden service")
                
                response = self.controller.create_ephemeral_hidden_service(
                    ports={self.config.hidden_service_port: local_port},
                    await_publication=True
                )
                
                self.onion_address = f"{response.service_id}.onion"
                self.service_id = response.service_id
                logger.info(f"Ephemeral hidden service created: {self.onion_address}")
            
            return self.onion_address
            
        except Exception as e:
            logger.error(f"Error creating hidden service: {e}")
            return None
    
    def get_onion_address(self) -> Optional[str]:
        """
        Get the onion address of the hidden service.
        
        Returns:
            str: Onion address if available, None otherwise
        """
        return self.onion_address
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get status information about the TOR hidden service.
        
        Returns:
            dict: Status information
        """
        return {
            'enabled': self.is_enabled(),
            'connected': self._is_connected,
            'onion_address': self.onion_address,
            'service_id': self.service_id,
            'control_host': self.config.control_host if self.config else None,
            'control_port': self.config.control_port if self.config else None,
            'hidden_service_port': self.config.hidden_service_port if self.config else None
        }
    
    def disconnect(self):
        """Disconnect from TOR control port and cleanup"""
        if self.controller:
            try:
                # Remove ephemeral hidden service if it exists
                if self.service_id:
                    logger.info(f"Removing ephemeral hidden service: {self.service_id}")
                    self.controller.remove_ephemeral_hidden_service(self.service_id)
                
                self.controller.close()
                logger.info("Disconnected from TOR control port")
            except Exception as e:
                logger.error(f"Error disconnecting from TOR: {e}")
            finally:
                self.controller = None
                self._is_connected = False
                self.onion_address = None
                self.service_id = None
    
    def __enter__(self):
        """Context manager entry"""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.disconnect()


def setup_tor_hidden_service(tor_config, local_port: int) -> Optional[TorHiddenService]:
    """
    Setup TOR hidden service for AISBF.
    
    Args:
        tor_config: TorConfig object
        local_port: Local port where AISBF is running
        
    Returns:
        TorHiddenService: Configured hidden service or None if disabled/failed
    """
    if not tor_config or not tor_config.enabled:
        logger.info("TOR hidden service is disabled")
        return None
    
    logger.info("Setting up TOR hidden service...")
    
    tor_service = TorHiddenService(tor_config)
    
    if not tor_service.connect():
        logger.error("Failed to connect to TOR control port")
        return None
    
    onion_address = tor_service.create_hidden_service(local_port)
    
    if onion_address:
        logger.info("=" * 80)
        logger.info("=== TOR HIDDEN SERVICE ACTIVE ===")
        logger.info("=" * 80)
        logger.info(f"Onion Address: {onion_address}")
        logger.info(f"Hidden Service Port: {tor_config.hidden_service_port}")
        logger.info(f"Local Port: {local_port}")
        logger.info("=" * 80)
        return tor_service
    else:
        logger.error("Failed to create TOR hidden service")
        tor_service.disconnect()
        return None
