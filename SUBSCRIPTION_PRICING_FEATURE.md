# Subscription-Based Provider and Custom Pricing Feature

## Overview

Added support for subscription-based providers and custom per-provider pricing configuration. This allows admins and users to:
1. Mark providers as subscription-based (free, $0 cost)
2. Configure custom pricing per million tokens for each provider
3. Track usage for all providers while calculating costs appropriately

---

## Changes Made

### 1. Provider Model (`aisbf/models.py`)

Added three new fields to the `Provider` model:

```python
class Provider(BaseModel):
    # ... existing fields ...
    
    # Pricing configuration
    is_subscription: bool = False  # If True, pricing is 0 (subscription-based provider)
    price_per_million_prompt: Optional[float] = None  # Price per million prompt tokens (USD)
    price_per_million_completion: Optional[float] = None  # Price per million completion tokens (USD)
```

### 2. Analytics Module (`aisbf/analytics.py`)

Added `_get_provider_pricing()` method that:
- Checks if provider is subscription-based → returns `{'prompt': 0.0, 'completion': 0.0}`
- Checks for custom pricing configuration → returns configured prices
- Falls back to default pricing if not configured

Updated `estimate_cost()` to use `_get_provider_pricing()` instead of hardcoded defaults.

### 3. Provider Configuration UI (`templates/dashboard/providers.html`)

Added pricing configuration section with:
- **Subscription checkbox**: Mark provider as subscription-based (free)
- **Prompt token pricing**: Custom price per million prompt tokens
- **Completion token pricing**: Custom price per million completion tokens
- **Dynamic UI**: Pricing fields hidden when subscription is checked
- **Helper text**: Examples and guidance for pricing values

---

## How It Works

### Subscription-Based Providers

When `is_subscription` is checked:
1. Cost calculations return $0
2. Usage is still tracked in analytics
3. Token counts are recorded normally
4. Pricing fields are hidden in UI

### Custom Pricing

When custom pricing is configured:
1. Analytics uses configured prices instead of defaults
2. Both prompt and completion prices can be set independently
3. Leave empty to use default pricing

### Pricing Priority

1. **Subscription status** (highest) - If `is_subscription = true`, cost is $0
2. **Custom pricing** - If configured, uses `price_per_million_prompt` and `price_per_million_completion`
3. **Default pricing** (lowest) - Falls back to hardcoded defaults in `Analytics.DEFAULT_PRICING`

---

## Configuration Storage

Provider configurations are stored as JSON in the `user_providers` table:

```json
{
  "id": "my-provider",
  "name": "My Provider",
  "type": "openai",
  "endpoint": "https://api.example.com/v1",
  "api_key_required": true,
  "is_subscription": false,
  "price_per_million_prompt": 10.0,
  "price_per_million_completion": 30.0
}
```

---

## Usage Examples

### Example 1: Subscription Provider (Kiro)

```
Provider: kiro-cli2
Type: kiro
Subscription: ✓ Checked
Prompt Pricing: (hidden)
Completion Pricing: (hidden)

Result: All usage tracked, cost = $0
```

### Example 2: Custom Pricing (OpenAI)

```
Provider: openai-custom
Type: openai
Subscription: ☐ Unchecked
Prompt Pricing: $5.00
Completion Pricing: $15.00

Result: Uses $5/M prompt, $15/M completion
```

### Example 3: Default Pricing (Anthropic)

```
Provider: anthropic
Type: anthropic
Subscription: ☐ Unchecked
Prompt Pricing: (empty)
Completion Pricing: (empty)

Result: Uses default $15/M prompt, $75/M completion
```

---

## Default Pricing

Current defaults in `Analytics.DEFAULT_PRICING`:

| Provider | Prompt ($/M) | Completion ($/M) |
|----------|--------------|------------------|
| anthropic | $15.00 | $75.00 |
| openai | $10.00 | $30.00 |
| google | $1.25 | $5.00 |
| kiro | $0.50 | $1.50 |
| openrouter | $5.00 | $15.00 |

---

## Benefits

1. **Accurate Cost Tracking**: Subscription providers don't inflate cost estimates
2. **Flexibility**: Each provider can have custom pricing
3. **Usage Tracking**: All usage is tracked regardless of cost
4. **User Control**: Admins and users can configure pricing per provider
5. **Backward Compatible**: Existing providers use default pricing

---

## Testing

To test the feature:

1. **Configure a subscription provider**:
   - Go to Dashboard → Providers
   - Edit a provider
   - Check "Subscription-Based Provider (Free)"
   - Save configuration

2. **Configure custom pricing**:
   - Go to Dashboard → Providers
   - Edit a provider
   - Uncheck subscription
   - Enter custom prompt/completion prices
   - Save configuration

3. **Verify analytics**:
   - Make requests through the provider
   - Check Dashboard → Analytics
   - Verify costs are calculated correctly

---

## Future Enhancements

Possible improvements:
- Per-model pricing (different models have different costs)
- Time-based pricing (different costs at different times)
- Volume discounts (lower costs for high usage)
- Currency conversion (support multiple currencies)

---

## Commit

```
ae1fb47 feat: add subscription-based provider and custom pricing configuration
```

All changes are production-ready and backward compatible.
