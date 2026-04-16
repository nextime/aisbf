"""
Multi-exchange cryptocurrency price aggregation service

Fetches prices from multiple exchanges (Coinbase, Binance, Kraken) and
averages them for accuracy. Includes caching to reduce API calls.
"""
import asyncio
import logging
import time
from typing import Dict, Optional, List, Tuple
from decimal import Decimal

import httpx

logger = logging.getLogger(__name__)


class CryptoPriceService:
    """
    Multi-exchange price aggregation service.
    
    Fetches cryptocurrency prices from multiple sources concurrently,
    averages successful responses, and caches results.
    """
    
    def __init__(self, db_manager, config: Dict):
        """
        Initialize price service.
        
        Args:
            db_manager: DatabaseManager instance
            config: Configuration dict with 'currency_code' (e.g., 'USD')
        """
        self.db = db_manager
        self.currency_code = config.get('currency_code', 'USD')
        self.cache: Dict[str, Tuple[float, float]] = {}  # {crypto_type: (price, timestamp)}
        self.cache_ttl = 60  # Cache for 60 seconds
        
    async def convert_crypto_to_fiat(self, crypto_type: str, amount: float) -> float:
        """
        Convert cryptocurrency amount to fiat currency.
        
        Args:
            crypto_type: Cryptocurrency code (e.g., 'btc', 'eth')
            amount: Amount in crypto
            
        Returns:
            Equivalent amount in fiat currency
            
        Raises:
            ValueError: If price cannot be fetched from any source
        """
        crypto_type = crypto_type.upper()
        
        # Check cache
        if crypto_type in self.cache:
            cached_price, cached_time = self.cache[crypto_type]
            if time.time() - cached_time < self.cache_ttl:
                logger.debug(f"Using cached price for {crypto_type}: ${cached_price}")
                return cached_price * amount
        
        # Fetch fresh price
        price = await self._fetch_average_price(crypto_type)
        
        # Update cache
        self.cache[crypto_type] = (price, time.time())
        
        return price * amount
    
    async def _fetch_average_price(self, crypto_type: str) -> float:
        """
        Fetch price from multiple sources and return average.
        
        Args:
            crypto_type: Cryptocurrency code (e.g., 'BTC', 'ETH')
            
        Returns:
            Average price across all successful sources
            
        Raises:
            ValueError: If no sources return valid prices
        """
        # Get enabled price sources from database
        sources = self._get_price_sources()
        
        # Fetch from all sources concurrently
        tasks = [
            self._fetch_price_from_source(source, crypto_type)
            for source in sources
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter successful results
        prices = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning(f"Failed to fetch from {sources[i]['name']}: {result}")
            elif result is not None:
                prices.append(result)
                logger.debug(f"Got price from {sources[i]['name']}: ${result}")
        
        if not prices:
            raise ValueError(f"Could not fetch price for {crypto_type} from any source")
        
        # Return average
        avg_price = sum(prices) / len(prices)
        logger.info(f"Average price for {crypto_type}: ${avg_price:.2f} (from {len(prices)} sources)")
        return avg_price
    
    def _get_price_sources(self) -> List[Dict]:
        """
        Get enabled price sources from database.
        
        Returns:
            List of price source configurations
        """
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT name, api_type, endpoint_url, api_key, priority
                FROM crypto_price_sources
                WHERE is_enabled = 1
                ORDER BY priority ASC
            ''')
            
            rows = cursor.fetchall()
            return [
                {
                    'name': row[0],
                    'api_type': row[1],
                    'endpoint_url': row[2],
                    'api_key': row[3],
                    'priority': row[4]
                }
                for row in rows
            ]
    
    async def _fetch_price_from_source(self, source: Dict, crypto_type: str) -> Optional[float]:
        """
        Fetch price from a single source.
        
        Args:
            source: Source configuration dict
            crypto_type: Cryptocurrency code (e.g., 'BTC')
            
        Returns:
            Price in fiat currency, or None if fetch fails
        """
        name = source['name']
        
        try:
            if name == 'Coinbase':
                return await self._fetch_coinbase(crypto_type)
            elif name == 'Binance':
                return await self._fetch_binance(crypto_type)
            elif name == 'Kraken':
                return await self._fetch_kraken(crypto_type)
            else:
                logger.warning(f"Unknown price source: {name}")
                return None
        except Exception as e:
            logger.error(f"Error fetching from {name}: {e}")
            return None
    
    async def _fetch_coinbase(self, crypto_type: str) -> Optional[float]:
        """
        Fetch price from Coinbase API.
        
        Args:
            crypto_type: Cryptocurrency code (e.g., 'BTC')
            
        Returns:
            Price in USD, or None if fetch fails
        """
        url = f"https://api.coinbase.com/v2/prices/{crypto_type}-{self.currency_code}/spot"
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
            
            price = float(data['data']['amount'])
            return price
    
    async def _fetch_binance(self, crypto_type: str) -> Optional[float]:
        """
        Fetch price from Binance API.
        
        Args:
            crypto_type: Cryptocurrency code (e.g., 'BTC')
            
        Returns:
            Price in USD/USDT, or None if fetch fails
        """
        # Binance uses USDT as the quote currency for most pairs
        symbol = f"{crypto_type}USDT"
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
            
            price = float(data['price'])
            return price
    
    async def _fetch_kraken(self, crypto_type: str) -> Optional[float]:
        """
        Fetch price from Kraken API.
        
        Args:
            crypto_type: Cryptocurrency code (e.g., 'BTC')
            
        Returns:
            Price in USD, or None if fetch fails
        """
        # Kraken uses different symbols (e.g., XXBTZUSD for BTC/USD)
        # Map common symbols
        symbol_map = {
            'BTC': 'XXBTZUSD',
            'ETH': 'XETHZUSD',
            'USDT': 'USDTZUSD',
            'USDC': 'USDCUSD'
        }
        
        kraken_symbol = symbol_map.get(crypto_type, f"X{crypto_type}ZUSD")
        url = f"https://api.kraken.com/0/public/Ticker?pair={kraken_symbol}"
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
            
            if data.get('error'):
                raise ValueError(f"Kraken API error: {data['error']}")
            
            # Kraken returns the pair name in the result
            result_key = list(data['result'].keys())[0]
            price = float(data['result'][result_key]['c'][0])  # 'c' is current price
            return price
