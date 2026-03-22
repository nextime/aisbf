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


class ContextManager:
    """
    Manages context size and performs condensation when needed.
    """
    
    def __init__(self, model_config: Dict, provider_handler=None, condensation_config=None):
        """
        Initialize the context manager.
        
        Args:
            model_config: Model configuration dictionary containing context_size, condense_context, condense_method
            provider_handler: Optional provider handler for making summarization requests (fallback)
            condensation_config: Optional condensation configuration for dedicated provider/model/rotation
        """
        self.context_size = model_config.get('context_size')
        self.condense_context = model_config.get('condense_context', 0)
        self.condense_method = model_config.get('condense_method')
        self.provider_handler = provider_handler
        self.condensation_config = condensation_config or config.get_condensation()
        
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
        logger = logging.getLogger(__name__)
        
        if self._internal_model is not None:
            return  # Already initialized
        
        try:
            import torch
            from transformers import AutoTokenizer, AutoModelForCausalLM
            import threading
            
            logger.info("=== INITIALIZING INTERNAL CONDENSATION MODEL ===")
            model_name = "huihui-ai/Qwen2.5-0.5B-Instruct-abliterated-v3"
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
        logger = logging.getLogger(__name__)
        logger.info(f"=== CONTEXT CONDENSATION START ===")
        logger.info(f"Original messages count: {len(messages)}")
        logger.info(f"Condensation methods: {self.condense_method}")
        
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
            else:
                logger.warning(f"Unknown condensation method: {method}")
        
        # Calculate token reduction
        original_tokens = count_messages_tokens(messages, model)
        condensed_tokens = count_messages_tokens(condensed_messages, model)
        reduction = original_tokens - condensed_tokens
        reduction_pct = (reduction / original_tokens * 100) if original_tokens > 0 else 0
        
        logger.info(f"=== CONTEXT CONDENSATION END ===")
        logger.info(f"Original tokens: {original_tokens}")
        logger.info(f"Condensed tokens: {condensed_tokens}")
        logger.info(f"Reduction: {reduction} tokens ({reduction_pct:.1f}%)")
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
        
        if len(messages) <= 2:
            # Not enough messages to condense
            return messages
        
        # Separate messages into categories
        system_messages = [m for m in messages if m.get('role') == 'system']
        user_messages = [m for m in messages if m.get('role') == 'user']
        assistant_messages = [m for m in messages if m.get('role') == 'assistant']
        
        # Keep all system messages (persistent state)
        persistent = system_messages.copy()
        
        # Keep recent messages (high fidelity - last 3 exchanges)
        recent_count = min(6, len(user_messages) + len(assistant_messages))
        recent_messages = []
        
        # Get last few messages in order
        all_messages_except_system = [m for m in messages if m.get('role') != 'system']
        recent_messages = all_messages_except_system[-recent_count:]
        
        # Middle messages to potentially summarize
        middle_messages = all_messages_except_system[:-recent_count]
        
        # For hierarchical, we keep persistent + recent, and summarize middle if needed
        condensed = persistent + middle_messages + recent_messages
        
        logger.info(f"Hierarchical: {len(persistent)} persistent, {len(middle_messages)} middle, {len(recent_messages)} recent")
        
        return condensed
    
    def _load_system_prompt(self, method: str) -> str:
        """Load system prompt from markdown file"""
        from pathlib import Path
        
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
        
        # Check if using internal model
        if self._use_internal_model:
            logger.info("Using internal model for conversational condensation")
        else:
            # Use dedicated condensation handler if available, otherwise fallback to provider_handler
            handler = self.condensation_handler if self.condensation_handler else self.provider_handler
            if not handler:
                logger.warning("No provider handler available for conversational condensation, skipping")
                return messages
            
            # Use dedicated condensation model if configured, otherwise use same model
            condense_model = self.condensation_model if self.condensation_model else model
        
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
        
        try:
            # If using rotation handler, call rotation handler's method
            if self._rotation_handler and not self.condensation_model:
                # Create a minimal request for condensation
                condensation_request = {
                    "messages": [{"role": "user", "content": summary_prompt}],
                    "temperature": 0.3,
                    "max_tokens": 1000,
                    "stream": False
                }
                # Call rotation handler to get condensation
                response = await self._rotation_handler.handle_rotation_request(self._rotation_id, condensation_request)
                # Extract summary content
                if isinstance(response, dict):
                    summary_content = response.get('choices', [{}])[0].get('message', {}).get('content', '')
                    
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
                        
                        logger.info(f"Conversational: Created summary via rotation ({len(summary_content)} chars)")
                        return condensed
            else:
                # Request summary from the model directly
                summary_messages = [{"role": "user", "content": summary_prompt}]
                summary_response = await handler.handle_request(
                    model=condense_model,
                    messages=summary_messages,
                    max_tokens=1000,
                    temperature=0.3,
                    stream=False
                )
                
                # Extract summary content
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
        
        # Use dedicated condensation handler if available, otherwise fallback to provider_handler
        handler = self.condensation_handler if self.condensation_handler else self.provider_handler
        if not handler:
            logger.warning("No provider handler available for semantic condensation, skipping")
            return messages
        
        # Use dedicated condensation model if configured, otherwise use same model
        condense_model = self.condensation_model if self.condensation_model else model
        
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
            # If using rotation handler, call rotation handler's method
            if self._rotation_handler and not self.condensation_model:
                # Create a minimal request for condensation
                condensation_request = {
                    "messages": [{"role": "user", "content": prune_prompt}],
                    "temperature": 0.2,
                    "max_tokens": 2000,
                    "stream": False
                }
                # Call rotation handler to get condensation
                response = await self._rotation_handler.handle_rotation_request(self._rotation_id, condensation_request)
                # Extract pruned content
                if isinstance(response, dict):
                    pruned_content = response.get('choices', [{}])[0].get('message', {}).get('content', '')
                    
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
                        
                        logger.info(f"Semantic: Pruned to relevant context via rotation ({len(pruned_content)} chars)")
                        return condensed
            else:
                # Request pruned context from the model directly
                prune_messages = [{"role": "user", "content": prune_prompt}]
                prune_response = await handler.handle_request(
                    model=condense_model,
                    messages=prune_messages,
                    max_tokens=2000,
                    temperature=0.2,
                    stream=False
                )
                
                # Extract pruned content
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
                
                # If very similar, skip
                if prev_content == curr_content:
                    logger.debug(f"Skipping duplicate message from {role}")
                    continue
            
            # Remove excessive whitespace
            if isinstance(content, str):
                content = ' '.join(content.split())
            
            condensed.append({
                "role": role,
                "content": content
            })
        
        logger.info(f"Algorithmic: Reduced from {len(messages)} to {len(condensed)} messages")
        
        return condensed


def get_context_config_for_model(
    model_name: str,
    provider_config: Any = None,
    rotation_model_config: Optional[Dict] = None
) -> Dict:
    """
    Get context configuration for a specific model.
    
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
    
    # Check rotation model config first (highest priority)
    if rotation_model_config:
        context_config['context_size'] = rotation_model_config.get('context_size')
        context_config['condense_context'] = rotation_model_config.get('condense_context', 0)
        context_config['condense_method'] = rotation_model_config.get('condense_method')
    
    # Fall back to provider config
    elif provider_config and hasattr(provider_config, 'models'):
        for model in provider_config.models:
            if model.get('name') == model_name:
                context_config['context_size'] = model.get('context_size')
                context_config['condense_context'] = model.get('condense_context', 0)
                context_config['condense_method'] = model.get('condense_method')
                break
    
    return context_config