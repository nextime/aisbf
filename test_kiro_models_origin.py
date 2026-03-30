#!/usr/bin/env python3
"""
Test script to verify Kiro models retrieval with correct origin parameter.
"""
import asyncio
import sys
import os
import logging

# Add aisbf to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aisbf.providers import KiroProviderHandler
from aisbf.config import config

# Enable debug logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def test_kiro_models():
    """Test Kiro models retrieval with origin='Cli'"""
    print("=" * 80)
    print("Testing Kiro Models Retrieval")
    print("=" * 80)
    
    # Get Kiro provider config
    kiro_providers = [p for p in config.providers.keys() if config.providers[p].type == 'kiro']
    
    if not kiro_providers:
        print("ERROR: No Kiro providers configured")
        return
    
    provider_id = kiro_providers[0]
    print(f"Using provider: {provider_id}")
    print()
    
    # Create handler
    handler = KiroProviderHandler(provider_id, api_key=None)
    
    # Get models
    print("Calling get_models()...")
    print()
    
    try:
        models = await handler.get_models()
        
        print("=" * 80)
        print(f"SUCCESS: Retrieved {len(models)} models")
        print("=" * 80)
        print()
        
        for i, model in enumerate(models, 1):
            print(f"{i}. {model.id}")
            if model.name != model.id:
                print(f"   Name: {model.name}")
        
        print()
        print("=" * 80)
        print("Test completed successfully!")
        print("=" * 80)
        
    except Exception as e:
        print("=" * 80)
        print(f"ERROR: {e}")
        print("=" * 80)
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_kiro_models())
