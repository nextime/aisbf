"""
Copyleft (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

Streaming Response Optimization Module

This module provides:
- Chunk pooling for memory efficiency
- Backpressure handling for rate control
- Optimized SSE parsing for Kiro
- Incremental delta calculation for Google

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
import asyncio
import json
import logging
from typing import AsyncIterator, Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field
from collections import deque

logger = logging.getLogger(__name__)


@dataclass
class StreamingConfig:
    """Configuration for streaming optimization"""
    # Chunk pooling settings
    enable_chunk_pooling: bool = True
    max_pooled_chunks: int = 50
    chunk_reuse_enabled: bool = True
    
    # Backpressure settings
    enable_backpressure: bool = True
    max_pending_chunks: int = 20
    chunk_yield_delay_ms: float = 0.0  # 0 = no delay, yields immediately
    
    # Memory settings
    max_accumulated_text: int = 1024 * 1024 * 10  # 10MB max text accumulation
    enable_text_truncation: bool = True
    
    # Google streaming specific
    google_delta_calculation: bool = True
    google_accumulated_text_limit: int = 1024 * 1024  # 1MB
    
    # Kiro streaming specific
    kiro_sse_optimization: bool = True
    kiro_buffer_size: int = 8192


class ChunkPool:
    """
    Memory-efficient chunk pool for reusing chunk objects.
    
    Instead of creating new dictionaries for each chunk, we reuse
    a pool of pre-allocated or previously-used chunk objects.
    """
    
    def __init__(self, config: StreamingConfig):
        self.config = config
        self._pool: deque = deque()
        self._stats = {
            'acquired': 0,
            'released': 0,
            'created': 0
        }
    
    def acquire(self) -> Dict[str, Any]:
        """Acquire a chunk from the pool (or create new)"""
        if self._pool and self.config.chunk_reuse_enabled:
            chunk = self._pool.popleft()
            self._stats['acquired'] += 1
            # Reset chunk to initial state
            chunk.clear()
            return chunk
        
        self._stats['created'] += 1
        return {}
    
    def release(self, chunk: Dict[str, Any]) -> None:
        """Return a chunk to the pool for reuse"""
        if not self.config.enable_chunk_pooling:
            return
        
        if len(self._pool) < self.config.max_pooled_chunks:
            chunk.clear()
            self._pool.append(chunk)
            self._stats['released'] += 1
    
    def get_stats(self) -> Dict[str, int]:
        """Get pool statistics"""
        return {
            'pool_size': len(self._pool),
            **self._stats
        }


class BackpressureController:
    """
    Backpressure controller for streaming responses.
    
    Prevents the streaming from getting too far ahead of the consumer
    by limiting the number of pending chunks.
    """
    
    def __init__(self, config: StreamingConfig):
        self.config = config
        self._pending_count: int = 0
        self._total_yielded: int = 0
    
    async def wait_if_needed(self) -> None:
        """Wait if too many chunks are pending"""
        if not self.config.enable_backpressure:
            return
        
        while self._pending_count >= self.config.max_pending_chunks:
            logger.debug(f"Backpressure: waiting (pending: {self._pending_count})")
            await asyncio.sleep(0.01)  # Small sleep to avoid busy waiting
    
    def on_chunk_yielded(self) -> None:
        """Notify that a chunk was yielded to consumer"""
        self._pending_count += 1
        self._total_yielded += 1
    
    def on_chunk_processed(self) -> None:
        """Notify that a chunk was processed"""
        self._pending_count = max(0, self._pending_count - 1)
    
    async def apply_yield_delay(self) -> None:
        """Apply configured yield delay"""
        if self.config.chunk_yield_delay_ms > 0:
            await asyncio.sleep(self.config.chunk_yield_delay_ms / 1000.0)
    
    def get_stats(self) -> Dict[str, int]:
        """Get backpressure statistics"""
        return {
            'pending_chunks': self._pending_count,
            'total_yielded': self._total_yielded
        }


class StreamingOptimizer:
    """
    Main streaming optimization coordinator.
    
    Combines chunk pooling and backpressure control to provide
    optimized streaming with better memory usage and flow control.
    """
    
    def __init__(self, config: Optional[StreamingConfig] = None):
        self.config = config or StreamingConfig()
        self.chunk_pool = ChunkPool(self.config)
        self.backpressure = BackpressureController(self.config)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get all optimization statistics"""
        return {
            'chunk_pool': self.chunk_pool.get_stats(),
            'backpressure': self.backpressure.get_stats()
        }


# Global streaming optimizer instance
_streaming_optimizer: Optional[StreamingOptimizer] = None


def get_streaming_optimizer(config: Optional[StreamingConfig] = None) -> StreamingOptimizer:
    """Get or create the global streaming optimizer instance"""
    global _streaming_optimizer
    if _streaming_optimizer is None:
        _streaming_optimizer = StreamingOptimizer(config)
    return _streaming_optimizer


# Utility functions for streaming optimization

def optimize_sse_chunk(
    chunk_data: Dict[str, Any],
    optimizer: Optional[StreamingOptimizer] = None,
    is_first: bool = False
) -> bytes:
    """
    Optimize SSE chunk serialization.
    
    Uses the optimizer's chunk pool for efficient memory usage.
    """
    if optimizer:
        chunk = optimizer.chunk_pool.acquire()
    else:
        chunk = {}
    
    try:
        # Build optimized chunk
        chunk.update(chunk_data)
        
        # Serialize with optimized settings
        return f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode('utf-8')
    finally:
        if optimizer:
            optimizer.chunk_pool.release(chunk)


def calculate_google_delta(
    current_text: str,
    accumulated_text: str
) -> str:
    """
    Calculate delta text for Google streaming.
    
    Only returns the new text since the last chunk, reducing
    data transfer and processing overhead.
    """
    if current_text.startswith(accumulated_text):
        return current_text[len(accumulated_text):]
    return current_text


class KiroSSEParser:
    """
    Optimized SSE parser for Kiro streaming responses.
    
    Reduces string allocations by:
    - Parsing SSE data more efficiently
    - Avoiding repeated string operations
    - Using incremental parsing
    """
    
    # Pre-compiled patterns for SSE parsing
    SSE_DATA_PREFIX = b"data: "
    SSE_DONE = b"[DONE]"
    SSE_NEWLINE = b"\n\n"
    
    def __init__(self, buffer_size: int = 8192):
        self.buffer_size = buffer_size
        self._buffer = bytearray()
        self._pending_data = ""
    
    def feed(self, chunk: bytes) -> List[Dict[str, Any]]:
        """
        Feed raw bytes and extract SSE events.
        
        Optimized to reduce string allocations and copying.
        """
        # Extend buffer
        self._buffer.extend(chunk)
        
        events = []
        
        while True:
            # Find data: prefix
            prefix_pos = self._buffer.find(self.SSE_DATA_PREFIX)
            if prefix_pos == -1:
                break
            
            # Find end of SSE event (double newline)
            data_start = prefix_pos + len(self.SSE_DATA_PREFIX)
            end_pos = self._buffer.find(self.SSE_NEWLINE, data_start)
            
            if end_pos == -1:
                # Check for [DONE]
                done_pos = self._buffer.find(self.SSE_DONE, data_start)
                if done_pos != -1 and (end_pos == -1 or done_pos < end_pos):
                    # Handle [DONE]
                    self._buffer = self._buffer[done_pos + len(self.SSE_DONE):]
                    events.append({"type": "done"})
                    continue
                break
            
            # Extract data
            data_bytes = self._buffer[data_start:end_pos]
            self._buffer = self._buffer[end_pos + len(self.SSE_NEWLINE):]
            
            # Skip empty data
            if not data_bytes or data_bytes.strip() == b"":
                continue
            
            # Check for [DONE]
            if data_bytes == self.SSE_DONE:
                events.append({"type": "done"})
                continue
            
            # Try to parse as JSON
            try:
                data_str = data_bytes.decode('utf-8')
                if data_str.strip():
                    data = json.loads(data_str)
                    events.append({"type": "data", "data": data})
            except (json.JSONDecodeError, UnicodeDecodeError):
                # Not JSON, treat as raw text
                pass
        
        return events
    
    def reset(self) -> None:
        """Reset parser state"""
        self._buffer = bytearray()
        self._pending_data = ""


class OptimizedTextAccumulator:
    """
    Memory-efficient text accumulator for streaming.
    
    Handles truncation and memory management for long streams.
    """
    
    def __init__(
        self,
        max_size: int = 1024 * 1024 * 10,
        enable_truncation: bool = True
    ):
        self.max_size = max_size
        self.enable_truncation = enable_truncation
        self._chunks: List[str] = []
        self._total_length: int = 0
    
    def append(self, text: str) -> str:
        """Append text and return accumulated result"""
        self._chunks.append(text)
        self._total_length += len(text)
        
        # Handle truncation if enabled
        if self.enable_truncation and self._total_length > self.max_size:
            self._truncate()
        
        return self.get()
    
    def get(self) -> str:
        """Get accumulated text"""
        return "".join(self._chunks)
    
    def _truncate(self) -> None:
        """Truncate accumulated text to max size"""
        current = self.get()
        
        if len(current) > self.max_size:
            # Keep the last max_size characters (more relevant for response)
            truncated = current[-self.max_size:]
            self._chunks = [truncated]
            self._total_length = len(truncated)
            
            logger.warning(f"Text accumulator truncated to {self.max_size} bytes")
    
    def clear(self) -> None:
        """Clear accumulated text"""
        self._chunks = []
        self._total_length = 0
    
    def __len__(self) -> int:
        return self._total_length


# Factory function for creating optimized components

def create_streaming_components(
    config: Optional[StreamingConfig] = None
) -> tuple:
    """
    Create optimized streaming components.
    
    Returns:
        tuple: (optimizer, chunk_pool, backpressure, sse_parser, text_accumulator)
    """
    optimizer = get_streaming_optimizer(config)
    
    return (
        optimizer,
        optimizer.chunk_pool,
        optimizer.backpressure,
        KiroSSEParser(buffer_size=config.kiro_buffer_size if config else 8192),
        OptimizedTextAccumulator(
            max_size=config.max_accumulated_text if config else 1024 * 1024 * 10,
            enable_truncation=config.enable_text_truncation if config else True
        )
    )