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
            if model.get('name') == model_name:
                max_tokens = model.get('max_request_tokens')
                if max_tokens:
                    logger.info(f"Found max_request_tokens in provider model config: {max_tokens}")
                    return max_tokens
    
    logger.debug(f"No max_request_tokens configured for model {model_name}")
    return None