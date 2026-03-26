"""
Copyleft (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

Content classification for NSFW and privacy detection.

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

Content classifier for NSFW and privacy detection.
"""
import logging
import threading
from typing import Optional, Tuple

class ContentClassifier:
    """
    Content classifier for NSFW and privacy detection.
    Uses HuggingFace transformers for classification.
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        self._nsfw_classifier = None
        self._privacy_classifier = None
        self._classifier_lock = threading.Lock()
        self._nsfw_model_name = None
        self._privacy_model_name = None
        self.logger = logging.getLogger(__name__)
    
    def initialize(self, nsfw_model_name: Optional[str] = None, privacy_model_name: Optional[str] = None):
        """
        Initialize the classifiers with the specified model names.
        
        Args:
            nsfw_model_name: HuggingFace model name for NSFW classification
            privacy_model_name: HuggingFace model name for privacy classification
        """
        self._nsfw_model_name = nsfw_model_name
        self._privacy_model_name = privacy_model_name
        
        if nsfw_model_name:
            self._load_nsfw_classifier(nsfw_model_name)
        
        if privacy_model_name:
            self._load_privacy_classifier(privacy_model_name)
    
    def _load_nsfw_classifier(self, model_name: str):
        """Load the NSFW classifier model"""
        try:
            from transformers import pipeline
            self.logger.info(f"Loading NSFW classifier model: {model_name}")
            self._nsfw_classifier = pipeline("text-classification", model=model_name)
            self.logger.info("NSFW classifier loaded successfully")
        except Exception as e:
            self.logger.error(f"Failed to load NSFW classifier: {e}")
            self._nsfw_classifier = None
    
    def _load_privacy_classifier(self, model_name: str):
        """Load the privacy classifier model"""
        try:
            from transformers import pipeline
            self.logger.info(f"Loading privacy classifier model: {model_name}")
            self._privacy_classifier = pipeline("text-classification", model=model_name)
            self.logger.info("Privacy classifier loaded successfully")
        except Exception as e:
            self.logger.error(f"Failed to load privacy classifier: {e}")
            self._privacy_classifier = None
    
    def check_nsfw(self, text: str, threshold: float = 0.8) -> Tuple[bool, str]:
        """
        Check if the given text contains NSFW content.
        
        Args:
            text: The text to check
            threshold: Confidence threshold for NSFW detection (default: 0.8)
        
        Returns:
            Tuple of (is_safe, message)
            - is_safe: True if content is safe, False if NSFW
            - message: Description of the result
        """
        if self._nsfw_classifier is None:
            self.logger.warning("NSFW classifier not initialized, allowing content")
            return True, "NSFW classifier not available"
        
        try:
            # Truncate to first 512 characters for classification (avoid huge inputs)
            # This is enough to detect the intent/content type
            text_to_check = text[:512] if len(text) > 512 else text
            result = self._nsfw_classifier(text_to_check)[0]
            
            self.logger.debug(f"NSFW classification result: {result}")
            
            if result['label'] == 'NSFW' and result['score'] > threshold:
                return False, f"Content classified as NSFW (confidence: {result['score']:.2f})"
            
            return True, "Content is safe"
        except Exception as e:
            self.logger.error(f"Error during NSFW classification: {e}")
            # Default to safe on error
            return True, f"Error during classification: {str(e)}"
    
    def check_privacy(self, text: str, threshold: float = 0.8) -> Tuple[bool, str]:
        """
        Check if the given text contains privacy-sensitive information.
        
        Args:
            text: The text to check
            threshold: Confidence threshold for privacy detection (default: 0.8)
        
        Returns:
            Tuple of (is_safe, message)
            - is_safe: True if content is safe, False if contains sensitive info
            - message: Description of the result
        """
        if self._privacy_classifier is None:
            self.logger.warning("Privacy classifier not initialized, allowing content")
            return True, "Privacy classifier not available"
        
        try:
            # Truncate to first 512 characters for classification (avoid huge inputs)
            # This is enough to detect personal/sensitive information
            text_to_check = text[:512] if len(text) > 512 else text
            result = self._privacy_classifier(text_to_check)[0]
            
            self.logger.debug(f"Privacy classification result: {result}")
            
            # Common labels for sensitive/personal information
            sensitive_labels = ['personal', 'pii', 'sensitive', 'private', 'nlp/privacy']
            
            if result['label'].lower() in [l.lower() for l in sensitive_labels] and result['score'] > threshold:
                return False, f"Content contains privacy-sensitive information (confidence: {result['score']:.2f})"
            
            return True, "Content is safe"
        except Exception as e:
            self.logger.error(f"Error during privacy classification: {e}")
            # Default to safe on error
            return True, f"Error during classification: {str(e)}"
    
    def check_content(self, text: str, check_nsfw: bool = True, check_privacy: bool = True, 
                      threshold: float = 0.8) -> Tuple[bool, str]:
        """
        Check content for both NSFW and privacy concerns.
        
        Args:
            text: The text to check
            check_nsfw: Whether to check for NSFW content
            check_privacy: Whether to check for privacy-sensitive content
            threshold: Confidence threshold for detection
        
        Returns:
            Tuple of (is_safe, message)
        """
        if check_nsfw:
            is_safe, message = self.check_nsfw(text, threshold)
            if not is_safe:
                return False, f"NSFW: {message}"
        
        if check_privacy:
            is_safe, message = self.check_privacy(text, threshold)
            if not is_safe:
                return False, f"Privacy: {message}"
        
        return True, "All content is safe"


# Global classifier instance
content_classifier = ContentClassifier()