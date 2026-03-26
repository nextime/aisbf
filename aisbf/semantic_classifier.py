"""
Copyleft (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

Semantic classification for model selection using hybrid BM25 + semantic re-ranking.

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

Semantic classifier for model selection.
"""
import logging
import threading
from typing import List, Dict, Optional, Tuple

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
            self._embedder = SentenceTransformer(self._model_name)
            self.logger.info("Semantic embedder loaded successfully")
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
