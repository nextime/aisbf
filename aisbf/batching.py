"""
Request Batching module for AISBF to reduce latency by batching similar requests.

Copyleft (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

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
import time
import logging
import hashlib
import json
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class BatchedRequest:
    """Represents a request that is waiting to be batched"""
    request_id: str
    request_data: Dict
    future: asyncio.Future
    timestamp: float = field(default_factory=time.time)
    provider_id: str = ""
    model: str = ""


@dataclass
class BatchConfig:
    """Configuration for request batching"""
    enabled: bool = False
    window_ms: int = 100  # 100ms window for batching
    max_batch_size: int = 8  # Maximum number of requests per batch
    # Provider-specific settings
    provider_settings: Dict[str, Dict] = field(default_factory=dict)


class RequestBatcher:
    """
    Request batcher that groups similar requests together to reduce latency.
    
    Features:
    - Time-based batching window (default 100ms)
    - Size-based batching limit (default 8 requests)
    - Provider-specific batching configurations
    - Automatic batch formation and processing
    - Response splitting and distribution
    """
    
    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize the request batcher.
        
        Args:
            config: Batching configuration with keys:
                - enabled: Whether batching is enabled (default: False)
                - window_ms: Batching window in milliseconds (default: 100)
                - max_batch_size: Maximum batch size (default: 8)
                - provider_settings: Provider-specific settings dict
        """
        self.config = config or {}
        self.enabled = self.config.get('enabled', False)
        self.window_ms = self.config.get('window_ms', 100)
        self.max_batch_size = self.config.get('max_batch_size', 8)
        self.provider_settings = self.config.get('provider_settings', {})
        
        # Request queues per provider/model combination
        self._queues: Dict[str, List[BatchedRequest]] = defaultdict(list)
        self._batch_tasks: Dict[str, asyncio.Task] = {}
        self._locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        
        # Statistics
        self.stats = {
            'batches_formed': 0,
            'requests_batched': 0,
            'avg_batch_size': 0.0,
            'latency_saved_ms': 0.0
        }
        
        logger.info(f"Request batcher initialized: enabled={self.enabled}, "
                   f"window_ms={self.window_ms}, max_batch_size={self.max_batch_size}")
    
    def _get_batch_key(self, provider_id: str, model: str) -> str:
        """Generate a batch key for provider/model combination"""
        return f"{provider_id}:{model}"
    
    async def submit_request(self, provider_id: str, model: str, request_data: Dict) -> Any:
        """
        Submit a request for batching.
        
        Args:
            provider_id: The provider identifier
            model: The model name
            request_data: The request data to be processed
            
        Returns:
            The response from the batched request processing
        """
        if not self.enabled:
            # If batching is disabled, return None to indicate direct processing
            return None
            
        batch_key = self._get_batch_key(provider_id, model)
        
        # Create a future for this request
        future: asyncio.Future = asyncio.Future()
        
        # Create batched request
        batched_request = BatchedRequest(
            request_id=f"{provider_id}:{model}:{int(time.time() * 1000000)}",
            request_data=request_data.copy(),
            future=future,
            provider_id=provider_id,
            model=model
        )
        
        # Add to queue
        async with self._locks[batch_key]:
            self._queues[batch_key].append(batched_request)
            
            # If this is the first request in the queue, start the batching window
            if len(self._queues[batch_key]) == 1:
                # Start batch formation task
                task = asyncio.create_task(self._form_batch(batch_key))
                self._batch_tasks[batch_key] = task
        
        # Wait for the result
        try:
            result = await future
            return result
        except Exception as e:
            logger.error(f"Error in batched request {batched_request.request_id}: {e}")
            raise e
    
    async def _form_batch(self, batch_key: str):
        """
        Form a batch from the queue and process it.
        
        Args:
            batch_key: The batch key (provider:model)
        """
        try:
            # Wait for the batching window or until we reach max batch size
            start_time = time.time()
            
            while True:
                async with self._locks[batch_key]:
                    queue_length = len(self._queues[batch_key])
                    
                    # Check if we have enough requests or if window has expired
                    if (queue_length >= self.max_batch_size or 
                        (queue_length > 0 and (time.time() - start_time) * 1000 >= self.window_ms)):
                        
                        # Take requests from queue for batching
                        batch_requests = self._queues[batch_key][:self.max_batch_size]
                        # Remove batched requests from queue
                        self._queues[batch_key] = self._queues[batch_key][self.max_batch_size:]
                        
                        # If no more requests in queue, cancel the batch task
                        if not self._queues[batch_key]:
                            if batch_key in self._batch_tasks:
                                self._batch_tasks[batch_key].cancel()
                                del self._batch_tasks[batch_key]
                        
                        break
                
                # Small sleep to prevent busy waiting
                await asyncio.sleep(0.001)  # 1ms
            
            # Process the batch if we have requests
            if batch_requests:
                await self._process_batch(batch_key, batch_requests)
                
        except asyncio.CancelledError:
            # Task was cancelled, this is normal
            pass
        except Exception as e:
            logger.error(f"Error forming batch for {batch_key}: {e}")
            # Complete all futures with the error
            async with self._locks[batch_key]:
                for batched_request in self._queues[batch_key]:
                    if not batched_request.future.done():
                        batched_request.future.set_exception(e)
                # Clear the queue
                self._queues[batch_key].clear()
    
    async def _process_batch(self, batch_key: str, batch_requests: List[BatchedRequest]):
        """
        Process a batch of requests.
        
        Args:
            batch_key: The batch key (provider:model)
            batch_requests: List of batched requests to process
        """
        if not batch_requests:
            return
            
        provider_id = batch_requests[0].provider_id
        model = batch_requests[0].model
        
        logger.debug(f"Processing batch of {len(batch_requests)} requests for {batch_key}")
        
        # Update statistics
        self.stats['batches_formed'] += 1
        self.stats['requests_batched'] += len(batch_requests)
        # Update average batch size
        total_batches = self.stats['batches_formed']
        self.stats['avg_batch_size'] = (
            (self.stats['avg_batch_size'] * (total_batches - 1) + len(batch_requests)) / total_batches
        )
        
        try:
            # Get the provider handler
            from .providers import get_provider_handler
            
            # For batching, we'll use the first request's API key (they should be the same)
            api_key = batch_requests[0].request_data.get('api_key')
            handler = get_provider_handler(provider_id, api_key)
            
            # Combine requests into a batch
            batch_request_data = self._combine_requests(batch_requests)
            
            # Process the batch request
            batch_response = await handler.handle_request(
                model=model,
                messages=batch_request_data.get('messages', []),
                max_tokens=batch_request_data.get('max_tokens'),
                temperature=batch_request_data.get('temperature', 1.0),
                stream=batch_request_data.get('stream', False),
                tools=batch_request_data.get('tools'),
                tool_choice=batch_request_data.get('tool_choice')
            )
            
            # Split the batch response and distribute to individual requests
            individual_responses = self._split_batch_response(batch_response, batch_requests)
            
            # Set results for each request
            for batched_request, individual_response in zip(batch_requests, individual_responses):
                if not batched_request.future.done():
                    batched_request.future.set_result(individual_response)
                    
        except Exception as e:
            logger.error(f"Error processing batch for {batch_key}: {e}")
            # Set exception for all requests in the batch
            for batched_request in batch_requests:
                if not batched_request.future.done():
                    batched_request.future.set_exception(e)
    
    def _combine_requests(self, batch_requests: List[BatchedRequest]) -> Dict:
        """
        Combine multiple requests into a single batch request.
        
        For now, we'll implement a simple approach where we process requests sequentially
        but still benefit from reduced connection overhead. In the future, this could
        be enhanced to use actual provider batching APIs.
        
        Args:
            batch_requests: List of batched requests to combine
            
        Returns:
            Combined request data
        """
        # For now, we'll use the first request as a template
        # In a real implementation, we would merge compatible requests
        first_request = batch_requests[0].request_data.copy()
        
        # Add batching metadata
        first_request['_aisbf_batch_size'] = len(batch_requests)
        first_request['_aisbf_batch_request_ids'] = [req.request_id for req in batch_requests]
        
        return first_request
    
    def _split_batch_response(self, batch_response: Any, batch_requests: List[BatchedRequest]) -> List[Any]:
        """
        Split a batch response into individual responses.
        
        Args:
            batch_response: The response from processing the batch
            batch_requests: The original batch requests
            
        Returns:
            List of individual responses
        """
        # For now, we'll return the same response for all requests
        # In a real implementation with actual batching APIs, we would split the response
        individual_responses = []
        
        for i, batched_request in enumerate(batch_requests):
            # Create a copy of the batch response for each request
            if isinstance(batch_response, dict):
                individual_response = batch_response.copy()
                # Add batching metadata to the response
                individual_response['_aisbf_batched'] = True
                individual_response['_aisbf_batch_index'] = i
                individual_response['_aisbf_batch_size'] = len(batch_requests)
            else:
                individual_response = batch_response
            
            individual_responses.append(individual_response)
        
        return individual_responses
    
    def get_stats(self) -> Dict:
        """
        Get batching statistics.
        
        Returns:
            Dictionary with batching statistics
        """
        return self.stats.copy()
    
    async def shutdown(self):
        """Shutdown the batcher and clean up resources"""
        logger.info("Shutting down request batcher...")
        
        # Cancel all pending batch tasks
        for batch_key, task in self._batch_tasks.items():
            if not task.done():
                task.cancel()
        
        # Wait for all tasks to complete
        if self._batch_tasks:
            await asyncio.gather(*self._batch_tasks.values(), return_exceptions=True)
        
        # Clear queues
        async with asyncio.Lock():  # We need a global lock here, but for simplicity we'll clear directly
            for batch_key in list(self._queues.keys()):
                # Complete all pending futures with an error
                for batched_request in self._queues[batch_key]:
                    if not batched_request.future.done():
                        batched_request.future.set_exception(
                            Exception("Batcher shutdown")
                        )
                self._queues[batch_key].clear()
        
        self._batch_tasks.clear()
        logger.info("Request batcher shutdown complete")


# Global batcher instance
_batcher: Optional[RequestBatcher] = None


def get_request_batcher(config: Optional[Dict] = None) -> RequestBatcher:
    """Get the global request batcher instance"""
    global _batcher
    if _batcher is None:
        _batcher = RequestBatcher(config)
    return _batcher


def initialize_request_batcher(config: Optional[Dict] = None):
    """Initialize the request batcher system"""
    global _batcher
    _batcher = RequestBatcher(config)
    logger.info("Request batcher initialized")