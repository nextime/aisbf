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
            try:
                self._nsfw_classifier = pipeline("text-classification", model=model_name, local_files_only=True)
                self.logger.info("NSFW classifier loaded from local cache")
            except (OSError, EnvironmentError):
                self.logger.info("NSFW model not cached, downloading from HuggingFace...")
                self._nsfw_classifier = pipeline("text-classification", model=model_name)
                self.logger.info("NSFW classifier downloaded and cached")
        except Exception as e:
            self.logger.error(f"Failed to load NSFW classifier: {e}")
            self._nsfw_classifier = None

    def _load_privacy_classifier(self, model_name: str):
        """Load the privacy classifier model"""
        try:
            from transformers import pipeline
            self.logger.info(f"Loading privacy classifier model: {model_name}")
            try:
                self._privacy_classifier = pipeline("text-classification", model=model_name, local_files_only=True)
                self.logger.info("Privacy classifier loaded from local cache")
            except (OSError, EnvironmentError):
                self.logger.info("Privacy model not cached, downloading from HuggingFace...")
                self._privacy_classifier = pipeline("text-classification", model=model_name)
                self.logger.info("Privacy classifier downloaded and cached")
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
    
    def reset(self):
        """Unload models from memory so they are re-loaded on next use."""
        with self._classifier_lock:
            self._nsfw_classifier = None
            self._privacy_classifier = None

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


# =============================================================================
# Semantic Classifier - Model selection using hybrid BM25 + semantic re-ranking
# (merged from semantic_classifier.py)
# =============================================================================

from typing import List, Dict


class SemanticClassifier:
    """
    Semantic classifier for model selection using hybrid BM25 + semantic re-ranking.
    Uses BM25 for fast keyword search and semantic embeddings for re-ranking.
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
        self._embedder = None
        self._embedder_lock = threading.Lock()
        self._model_name = None
        self.logger = logging.getLogger(__name__)
    
    def initialize(self, model_name: Optional[str] = None):
        """
        Initialize the semantic embedder.
        
        Args:
            model_name: HuggingFace model name for semantic embeddings
        """
        self._model_name = model_name or "sentence-transformers/all-MiniLM-L6-v2"
        self._load_embedder()
    
    def _load_embedder(self):
        """Load the semantic embedder model"""
        try:
            from sentence_transformers import SentenceTransformer
            self.logger.info(f"Loading semantic embedder model: {self._model_name}")
            try:
                self._embedder = SentenceTransformer(self._model_name, local_files_only=True)
                self.logger.info("Semantic embedder loaded from local cache")
            except (OSError, EnvironmentError):
                self.logger.info("Embedder not cached, downloading from HuggingFace...")
                self._embedder = SentenceTransformer(self._model_name)
                self.logger.info("Semantic embedder downloaded and cached")
        except Exception as e:
            self.logger.error(f"Failed to load semantic embedder: {e}")
            self._embedder = None
    
    def hybrid_model_search(
        self, 
        query: str, 
        chat_history: List[str],
        model_library: Dict[str, str],
        top_k: int = 3
    ) -> List[Tuple[str, float]]:
        """
        Perform hybrid BM25 + semantic search to find the best matching models.
        
        Args:
            query: The current user query
            chat_history: Recent chat history (last 3 messages)
            model_library: Dict of {model_id: description}
            top_k: Number of top candidates to return
        
        Returns:
            List of (model_id, score) tuples sorted by relevance
        """
        if self._embedder is None:
            self.logger.warning("Semantic embedder not initialized, falling back to simple matching")
            return [(list(model_library.keys())[0], 1.0)] if model_library else []
        
        try:
            from rank_bm25 import BM25Okapi
            from sentence_transformers import util
            import numpy as np
            
            # STEP 1: Build active window (last 3 messages + current query)
            active_window = " ".join(chat_history[-3:] + [query])
            self.logger.debug(f"Active window: {len(active_window.split())} words")
            
            # STEP 2: BM25 keyword search on model descriptions
            model_ids = list(model_library.keys())
            descriptions = list(model_library.values())
            
            # Tokenize corpus for BM25
            tokenized_corpus = [desc.lower().split() for desc in descriptions]
            bm25 = BM25Okapi(tokenized_corpus)
            
            # Get BM25 scores for all models
            tokenized_query = active_window.lower().split()
            bm25_scores = bm25.get_scores(tokenized_query)
            
            # Get top candidates based on BM25 (limit to top_k * 2 for re-ranking)
            num_candidates = min(len(model_ids), top_k * 2)
            top_bm25_indices = np.argsort(bm25_scores)[::-1][:num_candidates]
            
            self.logger.debug(f"BM25 selected {len(top_bm25_indices)} candidates for re-ranking")
            
            # STEP 3: Semantic re-ranking of BM25 candidates
            # Vectorize active window (intent)
            intent_vector = self._embedder.encode([active_window], convert_to_tensor=True)
            
            # Vectorize only the candidate descriptions
            candidate_descriptions = [descriptions[i] for i in top_bm25_indices]
            candidate_vectors = self._embedder.encode(candidate_descriptions, convert_to_tensor=True)
            
            # Compute cosine similarity
            cosine_scores = util.cos_sim(intent_vector, candidate_vectors)[0]
            
            # Get top_k from re-ranked candidates
            top_semantic_indices = np.argsort(cosine_scores.cpu().numpy())[::-1][:top_k]
            
            # Build results with scores
            results = []
            for idx in top_semantic_indices:
                original_idx = top_bm25_indices[idx]
                model_id = model_ids[original_idx]
                score = float(cosine_scores[idx])
                results.append((model_id, score))
                self.logger.debug(f"Model: {model_id}, Score: {score:.4f}")
            
            self.logger.info(f"Hybrid search completed: {len(results)} models ranked")
            return results
            
        except ImportError as e:
            self.logger.error(f"Missing dependencies for hybrid search: {e}")
            self.logger.error("Please install: pip install rank-bm25 sentence-transformers")
            # Fallback to first model
            return [(list(model_library.keys())[0], 1.0)] if model_library else []
        except Exception as e:
            self.logger.error(f"Error during hybrid model search: {e}")
            # Fallback to first model
            return [(list(model_library.keys())[0], 1.0)] if model_library else []
    
    def reset(self):
        """Unload the embedder from memory so it is re-loaded on next use."""
        with self._embedder_lock:
            self._embedder = None

    def select_best_model(
        self,
        query: str,
        chat_history: List[str],
        model_library: Dict[str, str]
    ) -> Optional[str]:
        """
        Select the best model based on semantic similarity.
        
        Args:
            query: The current user query
            chat_history: Recent chat history
            model_library: Dict of {model_id: description}
        
        Returns:
            The best matching model_id or None
        """
        results = self.hybrid_model_search(query, chat_history, model_library, top_k=1)
        if results:
            best_model, score = results[0]
            self.logger.info(f"Selected model: {best_model} (score: {score:.4f})")
            return best_model
        return None


# Global semantic classifier instance
semantic_classifier = SemanticClassifier()