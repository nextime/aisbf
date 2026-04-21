"""
Copyleft (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

Context management and condensation for AISBF.

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

Context management and condensation for AISBF.
"""
import logging
from typing import Dict, List, Optional, Union, Any
from .utils import count_messages_tokens
from .config import config
from .providers import get_provider_handler
from .database import get_database


class ContextManager:
    """
    Manages context size and performs condensation when needed.
    """
    
    def __init__(self, model_config: Dict, provider_handler=None, condensation_config=None, user_id=None):
        """
        Initialize the context manager.
        
        Args:
            model_config: Model configuration dictionary containing context_size, condense_context, condense_method
            provider_handler: Optional provider handler for making summarization requests (fallback)
            condensation_config: Optional condensation configuration for dedicated provider/model/rotation
            user_id: Optional user ID for user-specific prompt overrides
        """
        self.context_size = model_config.get('context_size')
        self.condense_context = model_config.get('condense_context', 0)
        self.condense_method = model_config.get('condense_method')
        self.provider_handler = provider_handler
        self.condensation_config = condensation_config or config.get_condensation()
        self.user_id = user_id
        
        # Initialize condensation provider handler if configured
        self.condensation_handler = None
        self.condensation_model = None
        self._rotation_handler = None
        self._rotation_id = None
        self._internal_model = None
        self._internal_tokenizer = None
        self._internal_model_lock = None
        self._use_internal_model = False
        
        # Get max_context for condensation model
        self.condensation_max_context = None
        if self.condensation_config and hasattr(self.condensation_config, 'max_context'):
            self.condensation_max_context = self.condensation_config.max_context
        
        if (self.condensation_config and
            self.condensation_config.enabled):
            try:
                # Check if model is a rotation ID or direct model name
                model_value = self.condensation_config.model
                
                # Check for "internal" keyword
                if model_value == "internal":
                    logger = logging.getLogger(__name__)
                    logger.info(f"Condensation model is 'internal' - will use local HuggingFace model")
                    self._use_internal_model = True
                    # Set default max_context for internal model if not specified
                    if not self.condensation_max_context:
                        self.condensation_max_context = 4000  # Conservative default for small models
                else:
                    # Check if this model value is a rotation ID (exists in rotations config)
                    is_rotation = False
                    if model_value:
                        try:
                            rotation_config = config.get_rotation(model_value)
                            if rotation_config:
                                is_rotation = True
                                logger = logging.getLogger(__name__)
                                logger.info(f"Condensation model '{model_value}' is a rotation ID")
                        except:
                            pass  # Not a rotation, treat as direct model
                    
                    if is_rotation:
                        # Use rotation handler for condensation
                        # Import here to avoid circular import
                        from .handlers import RotationHandler
                        rotation_handler = RotationHandler()
                        # Store rotation handler and rotation_id for later use
                        self._rotation_handler = rotation_handler
                        self._rotation_id = model_value
                        # The actual model will be selected by rotation handler
                        self.condensation_model = None  # Will be determined by rotation
                        logger = logging.getLogger(__name__)
                        logger.info(f"Initialized condensation with rotation: rotation_id={model_value}")
                    elif self.condensation_config.provider_id and model_value:
                        # Use provider handler for condensation with direct model
                        provider_config = config.get_provider(self.condensation_config.provider_id)
                        if provider_config:
                            api_key = provider_config.api_key
                            self.condensation_handler = get_provider_handler(
                                self.condensation_config.provider_id,
                                api_key
                            )
                            self.condensation_model = model_value
                            logger = logging.getLogger(__name__)
                            logger.info(f"Initialized condensation handler: provider={self.condensation_config.provider_id}, model={model_value}")
            except Exception as e:
                logger = logging.getLogger(__name__)
                logger.warning(f"Failed to initialize condensation handler: {e}")
        
        # Normalize condense_context to 0-100 range
        if self.condense_context and self.condense_context > 100:
            self.condense_context = 100
        
        # Normalize condense_method to list
        if self.condense_method:
            if isinstance(self.condense_method, str):
                self.condense_method = [self.condense_method]
        else:
            self.condense_method = []
        
        # Track conversation history for summarization
        self.conversation_summary = None
        self.summary_token_count = 0
        
        logger = logging.getLogger(__name__)
        logger.info(f"ContextManager initialized:")
        logger.info(f"  context_size: {self.context_size}")
        logger.info(f"  condense_context: {self.condense_context}%")
        logger.info(f"  condense_method: {self.condense_method}")
        logger.info(f"  condensation_max_context: {self.condensation_max_context}")
        logger.info(f"  use_internal_model: {self._use_internal_model}")
    
    def _initialize_internal_model(self):
        """Initialize the internal HuggingFace model for condensation (lazy loading)"""
        import logging
        import json
        from pathlib import Path
        logger = logging.getLogger(__name__)
        
        if self._internal_model is not None:
            return  # Already initialized
        
        try:
            import torch
            from transformers import AutoTokenizer, AutoModelForCausalLM
            import threading
            
            logger.info("=== INITIALIZING INTERNAL CONDENSATION MODEL ===")
            
            # Load model name from config
            config_path = Path.home() / '.aisbf' / 'aisbf.json'
            if not config_path.exists():
                # Try installed locations
                installed_dirs = [
                    Path('/usr/share/aisbf'),
                    Path.home() / '.local' / 'share' / 'aisbf',
                ]
                for installed_dir in installed_dirs:
                    test_path = installed_dir / 'aisbf.json'
                    if test_path.exists():
                        config_path = test_path
                        break
                else:
                    # Fallback to source tree
                    config_path = Path(__file__).parent.parent / 'config' / 'aisbf.json'
            
            model_name = "huihui-ai/Qwen2.5-0.5B-Instruct-abliterated-v3"  # Default
            if config_path.exists():
                try:
                    with open(config_path) as f:
                        aisbf_config = json.load(f)
                        model_name = aisbf_config.get('internal_model', {}).get('condensation_model_id', model_name)
                except Exception as e:
                    logger.warning(f"Error loading condensation model config: {e}, using default")
            
            logger.info(f"Model: {model_name}")
            
            # Check for GPU availability
            device = "cuda" if torch.cuda.is_available() else "cpu"
            logger.info(f"Device: {device}")
            
            # Load tokenizer
            logger.info("Loading tokenizer...")
            self._internal_tokenizer = AutoTokenizer.from_pretrained(model_name)
            logger.info("Tokenizer loaded")
            
            # Load model
            logger.info("Loading model...")
            self._internal_model = AutoModelForCausalLM.from_pretrained(
                model_name,
                torch_dtype=torch.float16 if device == "cuda" else torch.float32,
                device_map="auto" if device == "cuda" else None
            )
            
            if device == "cpu":
                self._internal_model = self._internal_model.to(device)
            
            logger.info("Model loaded successfully")
            
            # Initialize thread lock for model access
            self._internal_model_lock = threading.Lock()
            
            # Warm up the model with a simple inference
            try:
                logger.info("Warming up internal condensation model...")
                with self._internal_model_lock:
                    inputs = self._internal_tokenizer("Warm up", return_tensors="pt")
                    device = next(self._internal_model.parameters()).device
                    inputs = {k: v.to(device) for k, v in inputs.items()}
                    with torch.no_grad():
                        _ = self._internal_model.generate(**inputs, max_new_tokens=1)
                logger.info("Model warm-up completed")
            except Exception as e:
                logger.warning(f"Model warm-up failed: {e}")
            
            logger.info("=== INTERNAL CONDENSATION MODEL READY ===")
        except ImportError as e:
            logger.error(f"Failed to import required libraries for internal model: {e}")
            logger.error("Please install: pip install torch transformers")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize internal model: {e}", exc_info=True)
            raise
    
    async def _run_internal_model_condensation(self, prompt: str) -> str:
        """Run the internal model for condensation in a separate thread"""
        import logging
        import asyncio
        from concurrent.futures import ThreadPoolExecutor
        logger = logging.getLogger(__name__)
        
        # Initialize model if needed
        if self._internal_model is None:
            self._initialize_internal_model()
        
        def run_inference():
            """Run inference in a separate thread"""
            with self._internal_model_lock:
                try:
                    import torch
                    
                    # Tokenize input
                    inputs = self._internal_tokenizer(prompt, return_tensors="pt")
                    
                    # Move to same device as model
                    device = next(self._internal_model.parameters()).device
                    inputs = {k: v.to(device) for k, v in inputs.items()}
                    
                    # Generate response
                    with torch.no_grad():
                        outputs = self._internal_model.generate(
                            **inputs,
                            max_new_tokens=500,
                            temperature=0.3,
                            top_p=0.8,
                            repetition_penalty=1.1,
                            do_sample=True,
                            pad_token_id=self._internal_tokenizer.eos_token_id
                        )
                    
                    # Decode response
                    response = self._internal_tokenizer.decode(outputs[0], skip_special_tokens=True)
                    
                    # Extract only the generated part (remove the prompt)
                    if response.startswith(prompt):
                        response = response[len(prompt):].strip()
                    
                    return response
                except Exception as e:
                    logger.error(f"Error during internal model inference: {e}", exc_info=True)
                    return None
        
        # Run in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as executor:
            result = await loop.run_in_executor(executor, run_inference)
        
        return result
    
    def should_condense(self, messages: List[Dict], model: str) -> bool:
        """
        Check if context condensation is needed.
        
        Args:
            messages: List of messages to check
            model: Model name for token counting
            
        Returns:
            True if condensation is needed, False otherwise
        """
        if not self.context_size or not self.condense_context or self.condense_context == 0:
            return False
        
        # Calculate current token count
        current_tokens = count_messages_tokens(messages, model)
        
        # Calculate threshold
        threshold = int(self.context_size * (self.condense_context / 100))
        
        logger = logging.getLogger(__name__)
        logger.info(f"Context check: {current_tokens} / {self.context_size} tokens (threshold: {threshold})")
        
        return current_tokens >= threshold
    
    async def condense_context(
        self,
        messages: List[Dict],
        model: str,
        current_query: Optional[str] = None
    ) -> List[Dict]:
        """
        Condense the context using configured methods.
        
        Args:
            messages: List of messages to condense
            model: Model name for token counting
            current_query: Optional current query for semantic pruning
            
        Returns:
            Condensed list of messages
        """
        import time
        logger = logging.getLogger(__name__)
        logger.info(f"=== CONTEXT CONDENSATION START ===")
        logger.info(f"Original messages count: {len(messages)}")
        logger.info(f"Condensation methods: {self.condense_method}")
        
        start_time = time.time()
        condensed_messages = messages.copy()
        
        # Apply each condensation method in sequence
        for method in self.condense_method:
            logger.info(f"Applying method: {method}")
            
            if method == "hierarchical":
                condensed_messages = self._hierarchical_condense(condensed_messages, model)
            elif method == "conversational":
                condensed_messages = await self._conversational_condense(condensed_messages, model)
            elif method == "semantic":
                condensed_messages = await self._semantic_condense(condensed_messages, model, current_query)
            elif method == "algorithmic":
                condensed_messages = self._algorithmic_condense(condensed_messages, model)
            elif method == "sliding_window":
                condensed_messages = self._sliding_window_condense(condensed_messages, model)
            elif method == "importance_based":
                condensed_messages = self._importance_based_condense(condensed_messages, model)
            elif method == "entity_aware":
                condensed_messages = self._entity_aware_condense(condensed_messages, model)
            elif method == "code_aware":
                condensed_messages = self._code_aware_condense(condensed_messages, model)
            else:
                logger.warning(f"Unknown condensation method: {method}")
        
        # Calculate token reduction
        original_tokens = count_messages_tokens(messages, model)
        condensed_tokens = count_messages_tokens(condensed_messages, model)
        reduction = original_tokens - condensed_tokens
        reduction_pct = (reduction / original_tokens * 100) if original_tokens > 0 else 0
        
        duration = time.time() - start_time
        
        logger.info(f"=== CONTEXT CONDENSATION END ===")
        logger.info(f"Original tokens: {original_tokens}")
        logger.info(f"Condensed tokens: {condensed_tokens}")
        logger.info(f"Reduction: {reduction} tokens ({reduction_pct:.1f}%)")
        logger.info(f"Duration: {duration:.2f}s")
        logger.info(f"Final messages count: {len(condensed_messages)}")
        
        return condensed_messages
    
    def _hierarchical_condense(self, messages: List[Dict], model: str) -> List[Dict]:
        """
        HIERARCHICAL CONTEXT ENGINEERING
        Separate context into 'Persistent' (long-term facts) and 'Transient' (immediate task).
        Uses "Step-Back Prompting" to identify core principles before answering.

        Structure:
        - PERSISTENT STATE (Architecture): System messages and early context
        - RECENT HISTORY (Summarized): Middle messages
        - ACTIVE CODE (High Fidelity): Recent messages
        - INSTRUCTION: Current task
        """
        logger = logging.getLogger(__name__)
        logger.info(f"Hierarchical condensation: {len(messages)} messages")

        if len(messages) <= 4:
            # Not enough messages to condense
            return messages

        # Separate messages into categories
        system_messages = [m for m in messages if m.get('role') == 'system']
        all_conversation = [m for m in messages if m.get('role') != 'system']

        if len(all_conversation) <= 6:
            # Keep all conversation messages if not too many
            return messages

        # PERSISTENT STATE: System messages + first 2 conversation exchanges (establish context)
        persistent = system_messages.copy()
        persistent_cutoff = min(4, len(all_conversation))  # First 2 exchanges (4 messages)
        persistent.extend(all_conversation[:persistent_cutoff])

        # ACTIVE CODE: Last 4 messages (2 exchanges) - high fidelity recent context
        active_cutoff = 4
        active_messages = all_conversation[-active_cutoff:] if len(all_conversation) > active_cutoff else all_conversation

        # MIDDLE SECTION: Messages between persistent and active - candidates for summarization
        middle_messages = all_conversation[persistent_cutoff:-active_cutoff] if len(all_conversation) > (persistent_cutoff + active_cutoff) else []

        # If middle section is large, create a hierarchical summary
        condensed_middle = []
        if middle_messages:
            # Group middle messages into logical chunks (every 6 messages = 3 exchanges)
            chunk_size = 6
            chunks = [middle_messages[i:i + chunk_size] for i in range(0, len(middle_messages), chunk_size)]

            for i, chunk in enumerate(chunks):
                if i == len(chunks) - 1 and len(chunk) <= 2:
                    # Last small chunk - keep as is
                    condensed_middle.extend(chunk)
                else:
                    # Create hierarchical summary for chunk
                    chunk_text = ""
                    for msg in chunk:
                        role = msg.get('role', 'unknown')
                        content = msg.get('content', '')
                        if content:
                            chunk_text += f"{role}: {content}\n"

                    # Create summary message with hierarchical context
                    summary_content = f"[HIERARCHICAL CONTEXT - Phase {i+1}]\nKey developments: {chunk_text[:200]}{'...' if len(chunk_text) > 200 else ''}"

                    condensed_middle.append({
                        "role": "system",
                        "content": summary_content
                    })

        # Combine all sections: persistent + condensed middle + active
        condensed = persistent + condensed_middle + active_messages

        logger.info(f"Hierarchical: {len(persistent)} persistent, {len(condensed_middle)} summarized middle, {len(active_messages)} active")

        return condensed
    
    def _load_system_prompt(self, method: str) -> str:
        """Load system prompt from markdown file"""
        from pathlib import Path
        from .database import DatabaseRegistry
        
        # Check for user-specific prompt first if user_id is present
        if self.user_id is not None:
            db = DatabaseRegistry.get_config_database()
            prompt_key = f'condensation_{method}'
            user_prompt = db.get_user_prompt(self.user_id, prompt_key)
            if user_prompt is not None:
                return user_prompt
        
        # Try installed locations first
        installed_dirs = [
            Path('/usr/share/aisbf'),
            Path.home() / '.local' / 'share' / 'aisbf',
        ]
        
        for installed_dir in installed_dirs:
            prompt_file = installed_dir / f'condensation_{method}.md'
            if prompt_file.exists():
                with open(prompt_file) as f:
                    return f.read()
        
        # Fallback to source tree config directory
        source_dir = Path(__file__).parent.parent / 'config'
        prompt_file = source_dir / f'condensation_{method}.md'
        if prompt_file.exists():
            with open(prompt_file) as f:
                return f.read()
        
        # Return empty string if not found
        return ""
    
    async def _conversational_condense(self, messages: List[Dict], model: str) -> List[Dict]:
        """
        CONVERSATIONAL SUMMARIZATION (MEMORY BUFFERING)
        Replace old messages with a high-density summary.
        Uses a maintenance prompt to summarize progress.
        """
        logger = logging.getLogger(__name__)
        logger.info(f"Conversational condensation: {len(messages)} messages")
        
        if len(messages) <= 4:
            # Not enough messages to condense
            return messages
        
        # Keep system messages
        system_messages = [m for m in messages if m.get('role') == 'system']
        
        # Keep last 2 exchanges (4 messages)
        recent_messages = messages[-4:]
        
        # Messages to summarize (everything between system and recent)
        messages_to_summarize = messages[len(system_messages):-4]
        
        if not messages_to_summarize:
            return messages
        
        # Load system prompt from markdown file
        system_prompt = self._load_system_prompt('conversational')
        
        # Build conversation text
        conversation_text = ""
        for msg in messages_to_summarize:
            role = msg.get('role', 'unknown')
            content = msg.get('content', '')
            if content:
                conversation_text += f"{role}: {content}\n"
        
        # Build summary prompt
        summary_prompt = f"{system_prompt}\n\nConversation to summarize:\n{conversation_text}"
        
        try:
            summary_content = None
            
            if self._use_internal_model:
                logger.info("Using internal model for conversational summarization")
                summary_content = await self._run_internal_model_condensation(summary_prompt)
            elif self._rotation_handler and not self.condensation_model:
                # Use rotation handler
                condensation_request = {
                    "messages": [{"role": "user", "content": summary_prompt}],
                    "temperature": 0.3,
                    "max_tokens": 1000,
                    "stream": False
                }
                response = await self._rotation_handler.handle_rotation_request(self._rotation_id, condensation_request, None, None)
                if isinstance(response, dict):
                    summary_content = response.get('choices', [{}])[0].get('message', {}).get('content', '')
            else:
                # Use dedicated condensation handler if available, otherwise fallback to provider_handler
                handler = self.condensation_handler if self.condensation_handler else self.provider_handler
                if handler:
                    condense_model = self.condensation_model if self.condensation_model else model
                    summary_messages = [{"role": "user", "content": summary_prompt}]
                    summary_response = await handler.handle_request(
                        model=condense_model,
                        messages=summary_messages,
                        max_tokens=1000,
                        temperature=0.3,
                        stream=False
                    )
                    if isinstance(summary_response, dict):
                        summary_content = summary_response.get('choices', [{}])[0].get('message', {}).get('content', '')

            if summary_content:
                # Create summary message
                summary_message = {
                    "role": "system",
                    "content": f"[CONVERSATION SUMMARY]\n{summary_content}"
                }
                
                # Build condensed messages: system + summary + recent
                condensed = system_messages + [summary_message] + recent_messages
                
                # Update stored summary
                self.conversation_summary = summary_content
                self.summary_token_count = count_messages_tokens([summary_message], model)
                
                logger.info(f"Conversational: Created summary ({len(summary_content)} chars)")
                return condensed
            
        except Exception as e:
            logger.error(f"Error during conversational condensation: {e}")
        
        # Fallback: return original messages
        return messages
    
    async def _semantic_condense(
        self,
        messages: List[Dict],
        model: str,
        current_query: Optional[str] = None
    ) -> List[Dict]:
        """
        SEMANTIC CONTEXT PRUNING (OBSERVATION MASKING)
        Remove or hide old, non-critical details that are irrelevant to the current task.
        Uses a smaller model as a "janitor" to extract only relevant info.
        """
        logger = logging.getLogger(__name__)
        logger.info(f"Semantic condensation: {len(messages)} messages")
        
        if len(messages) <= 2:
            return messages
        
        # Keep system messages
        system_messages = [m for m in messages if m.get('role') == 'system']
        
        # Get conversation history (excluding system)
        conversation = [m for m in messages if m.get('role') != 'system']
        
        if not conversation:
            return messages
        
        # Build conversation text
        conversation_text = ""
        for msg in conversation:
            role = msg.get('role', 'unknown')
            content = msg.get('content', '')
            if content:
                conversation_text += f"{role}: {content}\n"
        
        # Build pruning prompt
        if current_query:
            prune_prompt = f"""Given the current query: '{current_query}'

Extract ONLY the relevant facts from this conversation history. Ignore everything else that is not directly related to answering the current query.

Conversation History:
{conversation_text}

Provide only the relevant information in a concise format."""
        else:
            prune_prompt = f"""Extract the most important and relevant information from this conversation history. Focus on key facts, decisions, and context that would be needed for future queries.

Conversation History:
{conversation_text}

Provide only the relevant information in a concise format."""
        
        try:
            pruned_content = None
            
            if self._use_internal_model:
                logger.info("Using internal model for semantic pruning")
                pruned_content = await self._run_internal_model_condensation(prune_prompt)
            elif self._rotation_handler and not self.condensation_model:
                # Use rotation handler
                condensation_request = {
                    "messages": [{"role": "user", "content": prune_prompt}],
                    "temperature": 0.2,
                    "max_tokens": 2000,
                    "stream": False
                }
                response = await self._rotation_handler.handle_rotation_request(self._rotation_id, condensation_request, None, None)
                if isinstance(response, dict):
                    pruned_content = response.get('choices', [{}])[0].get('message', {}).get('content', '')
            else:
                # Use dedicated condensation handler if available, otherwise fallback to provider_handler
                handler = self.condensation_handler if self.condensation_handler else self.provider_handler
                if handler:
                    condense_model = self.condensation_model if self.condensation_model else model
                    prune_messages = [{"role": "user", "content": prune_prompt}]
                    prune_response = await handler.handle_request(
                        model=condense_model,
                        messages=prune_messages,
                        max_tokens=2000,
                        temperature=0.2,
                        stream=False
                    )
                    if isinstance(prune_response, dict):
                        pruned_content = prune_response.get('choices', [{}])[0].get('message', {}).get('content', '')

            if pruned_content:
                # Create pruned context message
                pruned_message = {
                    "role": "system",
                    "content": f"[RELEVANT CONTEXT]\n{pruned_content}"
                }
                
                # Build condensed messages: system + pruned + last user message
                last_message = messages[-1] if messages else None
                if last_message and last_message.get('role') != 'system':
                    condensed = system_messages + [pruned_message, last_message]
                else:
                    condensed = system_messages + [pruned_message]
                
                logger.info(f"Semantic: Pruned to relevant context ({len(pruned_content)} chars)")
                return condensed
            
        except Exception as e:
            logger.error(f"Error during semantic condensation: {e}")
        
        # Fallback: return original messages
        return messages
    
    def _algorithmic_condense(self, messages: List[Dict], model: str) -> List[Dict]:
        """
        ALGORITHMIC TOKEN COMPRESSION (LLMLingua-style)
        Mathematically remove "low-information" tokens.
        This is a simplified version that removes redundant content.
        """
        logger = logging.getLogger(__name__)
        logger.info(f"Algorithmic condensation: {len(messages)} messages")
        
        condensed = []
        
        for msg in messages:
            role = msg.get('role')
            content = msg.get('content')
            
            if not content:
                condensed.append(msg)
                continue
            
            # Skip empty or very short messages
            if len(str(content)) < 10:
                continue
            
            # Remove duplicate consecutive messages from same role
            if condensed and condensed[-1].get('role') == role:
                prev_content = str(condensed[-1].get('content', ''))
                curr_content = str(content)
                
                # If identical, skip
                if prev_content == curr_content:
                    logger.debug(f"Skipping duplicate message from {role}")
                    continue
                
                # Check for high similarity (potential duplicate)
                try:
                    import difflib
                    similarity = difflib.SequenceMatcher(None, prev_content, curr_content).ratio()
                    if similarity > 0.85:
                        logger.debug(f"Skipping similar message from {role} (similarity: {similarity:.2f})")
                        continue
                except ImportError:
                    pass  # difflib is standard library, but in case
            
            # Remove excessive whitespace
            if isinstance(content, str):
                content = ' '.join(content.split())
            
            condensed.append({
                "role": role,
                "content": content
            })
        
        logger.info(f"Algorithmic: Reduced from {len(messages)} to {len(condensed)} messages")
        
        return condensed
    
    def _sliding_window_condense(self, messages: List[Dict], model: str) -> List[Dict]:
        """
        SLIDING WINDOW WITH OVERLAP
        Keep recent messages with overlapping context from older parts.
        """
        logger = logging.getLogger(__name__)
        logger.info(f"Sliding window condensation: {len(messages)} messages")
        
        if len(messages) <= 6:
            return messages
        
        # Parameters
        window_size = 4  # messages to keep in recent window
        overlap_size = 2  # messages to keep from older windows
        
        # Keep all system messages
        system_messages = [m for m in messages if m.get('role') == 'system']
        conversation = [m for m in messages if m.get('role') != 'system']
        
        if len(conversation) <= window_size:
            return messages
        
        # Recent window
        recent = conversation[-window_size:]
        
        # Older parts with overlap
        older = conversation[:-window_size]
        
        # Take overlapping messages from older parts
        overlap = []
        if older:
            # Take last overlap_size from older
            overlap = older[-overlap_size:] if len(older) >= overlap_size else older
        
        # Combine
        condensed_conversation = overlap + recent
        condensed = system_messages + condensed_conversation
        
        logger.info(f"Sliding window: {len(overlap)} overlap + {len(recent)} recent = {len(condensed_conversation)} conversation messages")
        
        return condensed
    
    def _importance_based_condense(self, messages: List[Dict], model: str) -> List[Dict]:
        """
        IMPORTANCE-BASED PRUNING
        Keep messages based on importance scores.
        """
        logger = logging.getLogger(__name__)
        logger.info(f"Importance-based condensation: {len(messages)} messages")
        
        if len(messages) <= 4:
            return messages
        
        system_messages = [m for m in messages if m.get('role') == 'system']
        conversation = [m for m in messages if m.get('role') != 'system']
        
        if not conversation:
            return messages
        
        # Score messages by importance
        scored = []
        for i, msg in enumerate(conversation):
            role = msg.get('role', '')
            content = str(msg.get('content', ''))
            
            score = 0
            
            # Role-based scoring
            if role == 'user':
                score += 2  # User messages more important
            elif role == 'assistant':
                score += 1
            
            # Length-based (longer messages more important)
            content_length = len(content)
            if content_length > 100:
                score += 1
            if content_length > 500:
                score += 1
            
            # Question detection
            if '?' in content:
                score += 1
            
            # Recency bonus
            recency_bonus = (i / len(conversation)) * 2  # More recent = higher score
            score += recency_bonus
            
            scored.append((score, msg))
        
        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)
        
        # Keep top messages, but maintain order
        keep_count = max(4, len(conversation) // 2)  # Keep at least half, minimum 4
        top_scored = scored[:keep_count]
        
        # Sort back by original order
        top_scored.sort(key=lambda x: conversation.index(x[1]))
        
        kept_messages = [msg for score, msg in top_scored]
        
        condensed = system_messages + kept_messages
        
        logger.info(f"Importance-based: Kept {len(kept_messages)}/{len(conversation)} conversation messages")
        
        return condensed
    
    def _entity_aware_condense(self, messages: List[Dict], model: str) -> List[Dict]:
        """
        ENTITY-AWARE CONDENSATION
        Preserve messages that mention key entities.
        """
        logger = logging.getLogger(__name__)
        logger.info(f"Entity-aware condensation: {len(messages)} messages")
        
        if len(messages) <= 4:
            return messages
        
        system_messages = [m for m in messages if m.get('role') == 'system']
        conversation = [m for m in messages if m.get('role') != 'system']
        
        if not conversation:
            return messages
        
        # Simple entity extraction: capitalized words, numbers, emails, etc.
        import re
        
        entities = set()
        for msg in conversation:
            content = str(msg.get('content', ''))
            # Find capitalized words (potential names)
            caps = re.findall(r'\b[A-Z][a-z]+\b', content)
            entities.update(caps)
            # Find numbers
            nums = re.findall(r'\b\d+\b', content)
            entities.update(nums)
            # Find emails
            emails = re.findall(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', content)
            entities.update(emails)
        
        # Keep messages that mention entities or are recent
        kept = []
        for i, msg in enumerate(conversation):
            content = str(msg.get('content', ''))
            
            # Keep if mentions entities
            mentions_entity = any(entity in content for entity in entities)
            
            # Keep if recent (last 3 messages)
            is_recent = i >= len(conversation) - 3
            
            # Keep if system-like or important
            is_important = '?' in content or len(content) > 200
            
            if mentions_entity or is_recent or is_important:
                kept.append(msg)
        
        # If too few kept, add more recent ones
        if len(kept) < 4 and len(conversation) > 4:
            for msg in reversed(conversation):
                if msg not in kept:
                    kept.insert(0, msg)
                    if len(kept) >= 4:
                        break
        
        condensed = system_messages + kept
        
        logger.info(f"Entity-aware: Kept {len(kept)}/{len(conversation)} conversation messages, {len(entities)} entities found")
        
        return condensed
    
    def _code_aware_condense(self, messages: List[Dict], model: str) -> List[Dict]:
        """
        CODE-AWARE CONDENSATION
        Preserve messages containing code blocks.
        """
        logger = logging.getLogger(__name__)
        logger.info(f"Code-aware condensation: {len(messages)} messages")
        
        if len(messages) <= 4:
            return messages
        
        system_messages = [m for m in messages if m.get('role') == 'system']
        conversation = [m for m in messages if m.get('role') != 'system']
        
        if not conversation:
            return messages
        
        # Identify messages with code blocks
        code_messages = []
        non_code_messages = []
        
        for msg in conversation:
            content = str(msg.get('content', ''))
            
            # Check for code blocks (``` or indented code)
            has_code = '```' in content or '\n    ' in content or '\n\t' in content
            
            if has_code:
                code_messages.append(msg)
            else:
                non_code_messages.append(msg)
        
        # Keep all code messages, plus some recent non-code
        kept = code_messages.copy()
        
        # Add recent non-code messages
        recent_non_code = non_code_messages[-4:] if len(non_code_messages) > 4 else non_code_messages
        kept.extend(recent_non_code)
        
        # Remove duplicates (if any code message is also recent)
        kept = list(dict.fromkeys(kept))  # preserve order
        
        condensed = system_messages + kept
        
        logger.info(f"Code-aware: {len(code_messages)} code messages, {len(recent_non_code)} recent non-code, total {len(kept)} kept")
        
        return condensed


def get_context_config_for_model(
    model_name: str,
    provider_config: Any = None,
    rotation_model_config: Optional[Dict] = None
) -> Dict:
    """
    Get context configuration for a specific model with cascading fallback.
    
    Priority order for each field:
    1. Rotation model config (if explicitly set)
    2. Model-specific config in provider (if exists)
    3. First model in provider (auto-derived from dynamic fetch)
    4. Provider default config (fallback)
    5. System default (0 for condense_context, None for others)
    
    Args:
        model_name: Name of the model
        provider_config: Provider configuration (optional)
        rotation_model_config: Rotation model configuration (optional)
        
    Returns:
        Dictionary with context_size, condense_context, and condense_method
    """
    context_config = {
        'context_size': None,
        'condense_context': 0,
        'condense_method': None
    }
    
    # Step 1: Get provider-level defaults and model-specific config
    model_specific_config = None
    if provider_config:
        # Try to find model-specific config in provider
        if hasattr(provider_config, 'models') and provider_config.models:
            for model in provider_config.models:
                # Handle both Pydantic objects and dictionaries
                model_name_value = model.name if hasattr(model, 'name') else model.get('name')
                if model_name_value == model_name:
                    # Convert Pydantic object to dict if needed
                    if hasattr(model, 'model_dump'):
                        model_specific_config = model.model_dump()
                    elif hasattr(model, 'dict'):
                        model_specific_config = model.dict()
                    else:
                        model_specific_config = model
                    break
        
        # Build base config from provider (model-specific > first model > provider defaults)
        # context_size
        if model_specific_config and model_specific_config.get('context_size') is not None:
            context_config['context_size'] = model_specific_config.get('context_size')
        elif hasattr(provider_config, 'default_context_size') and provider_config.default_context_size is not None:
            context_config['context_size'] = provider_config.default_context_size
        else:
            # Auto-derive from first model in provider (has context_size from dynamic fetch)
            if provider_config.models and len(provider_config.models) > 0:
                first_model = provider_config.models[0]
                # Check for context_size in the first model (from dynamic fetch)
                if hasattr(first_model, 'context_size') and first_model.context_size:
                    context_config['context_size'] = first_model.context_size
                elif hasattr(first_model, 'context_window') and first_model.context_window:
                    context_config['context_size'] = first_model.context_window
                elif hasattr(first_model, 'context_length') and first_model.context_length:
                    context_config['context_size'] = first_model.context_length
        
        # condense_context
        if model_specific_config and model_specific_config.get('condense_context') is not None:
            context_config['condense_context'] = model_specific_config.get('condense_context')
        elif hasattr(provider_config, 'default_condense_context') and provider_config.default_condense_context is not None:
            context_config['condense_context'] = provider_config.default_condense_context
        else:
            context_config['condense_context'] = 0
        
        # condense_method
        if model_specific_config and model_specific_config.get('condense_method') is not None:
            context_config['condense_method'] = model_specific_config.get('condense_method')
        elif hasattr(provider_config, 'default_condense_method') and provider_config.default_condense_method is not None:
            context_config['condense_method'] = provider_config.default_condense_method
    
    # Step 2: Override with rotation model config (only if explicitly set)
    if rotation_model_config:
        # Only override if the field is explicitly set in rotation config
        if 'context_size' in rotation_model_config and rotation_model_config['context_size'] is not None:
            context_config['context_size'] = rotation_model_config['context_size']
        elif context_config.get('context_size') is None:
            # If context_size is still None, check if rotation_model_config has default_context_size
            # (This handles the case where rotation-level default should be used)
            if 'default_context_size' in rotation_model_config and rotation_model_config['default_context_size'] is not None:
                context_config['context_size'] = rotation_model_config['default_context_size']
        
        if 'condense_context' in rotation_model_config and rotation_model_config['condense_context'] is not None:
            context_config['condense_context'] = rotation_model_config['condense_context']
        elif context_config.get('condense_context') == 0:
            # If condense_context is still at default (0), check if rotation has default
            if 'default_condense_context' in rotation_model_config and rotation_model_config['default_condense_context'] is not None:
                context_config['condense_context'] = rotation_model_config['default_condense_context']
        
        if 'condense_method' in rotation_model_config and rotation_model_config['condense_method'] is not None:
            context_config['condense_method'] = rotation_model_config['condense_method']
    
    # Step 3: Final fallback if context_size is still None
    # Use inference based on model name patterns
    if context_config.get('context_size') is None:
        context_config['context_size'] = _infer_context_size_from_model(model_name)
    
    return context_config


def _infer_context_size_from_model(model_name: str) -> int:
    """
    Infer context window size from model name patterns.
    
    Args:
        model_name: Name of the model
        
    Returns:
        Inferred context size in tokens
    """
    model_lower = model_name.lower()
    
    # Known model patterns
    if 'gpt-4' in model_lower:
        if 'turbo' in model_lower or '1106' in model_lower or '0125' in model_lower:
            return 128000
        return 8192
    elif 'gpt-3.5' in model_lower:
        if 'turbo' in model_lower and ('1106' in model_lower or '0125' in model_lower):
            return 16385
        return 4096
    elif 'claude-3' in model_lower:
        return 200000
    elif 'claude-2' in model_lower:
        return 100000
    elif 'gemini' in model_lower:
        if '1.5' in model_lower:
            return 2000000 if 'pro' in model_lower else 1000000
        elif '2.0' in model_lower:
            return 1000000
        return 32000
    elif 'llama' in model_lower:
        if '3' in model_lower:
            return 128000
        return 4096
    elif 'mistral' in model_lower:
        if 'large' in model_lower:
            return 32000
        return 8192
    
    # Generic default
    return 8192