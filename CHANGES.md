# AISBF v0.99.33 - Changes Summary

## Fixed Issues

### 1. Analytics Token Counting for Kilo/Kilocode Providers
- **Problem**: Kilo providers return OpenAI `ChatCompletion` objects instead of dict responses, causing analytics to fail silently
- **Solution**: Added support for both dict and ChatCompletion object responses in analytics.py
- **Files Modified**: `aisbf/analytics.py`, `aisbf/handlers.py`

### 2. Database Migration for Missing Columns
- **Problem**: `token_usage` table was missing 4 columns: `success`, `latency_ms`, `error_type`, `token_id`
- **Solution**: Fixed migration code to run on startup and add all missing columns automatically
- **Files Modified**: `aisbf/database.py`

### 3. Model Retrieval from lisa.nexlab.net
- **Problem**: Missing `handle_model_list` method caused model retrieval to fail
- **Solution**: Restored handlers.py from git and added proper model list handling
- **Files Modified**: `aisbf/handlers.py`

### 4. Response Cache Serialization
- **Problem**: Cache failed to serialize ChatCompletion objects
- **Solution**: Added automatic object → dict conversion for response cache
- **Files Modified**: `aisbf/cache.py`

### 5. MySQL Timezone Issues
- **Problem**: Analytics queries used `.isoformat()` instead of UTC formatted timestamps, causing blank graphs on MySQL
- **Solution**: All timestamp queries now use `_format_timestamp()` method for proper UTC formatting
- **Files Modified**: `aisbf/analytics.py`

### 6. Cost Calculation Debug Logging
- **Problem**: Cost calculation breakdown was at DEBUG level and never called
- **Solution**: 
  - Changed all cost logging to INFO level
  - Added cost calculation call in handlers.py success path
  - Added kilo providers to DEFAULT_PRICING with $0.00 (subscription/free)
- **Files Modified**: `aisbf/analytics.py`, `aisbf/handlers.py`

### 7. Database Tracking Debug Logging
- **Problem**: Insufficient logging to debug tracking issues
- **Solution**: Added comprehensive trace logging for all database insert operations
- **Files Modified**: `aisbf/database.py`

### 8. Analytics Time Range Filter
- **Problem**: Analytics page lacked "Yesterday" option and proper time range handling
- **Solution**: 
  - Added "Yesterday" preset option
  - Improved time range handling in both frontend and backend
  - Fixed custom date range logic
  - Fixed graph title to dynamically show selected time range
- **Files Modified**: `templates/dashboard/analytics.html`, `main.py`, `aisbf/analytics.py`

### 9. Analytics Filters Not Applied to All Sections
- **Problem**: Cost overview, model performance, and recommendations ignored time range filters
- **Solution**: 
  - Added `from_datetime` and `to_datetime` parameters to `get_model_performance()`
  - Added `from_datetime` and `to_datetime` parameters to `get_optimization_recommendations()`
  - Model performance now uses date-filtered provider stats
  - All analytics sections now respect the selected time range
- **Files Modified**: `aisbf/analytics.py`, `main.py`

### 10. Cost Overview Hardcoded to 24 Hours
- **Problem**: Cost overview always showed last 24 hours regardless of selected time range
- **Solution**: Simplified logic to use tokens from provider stats which already respect date range
- **Files Modified**: `aisbf/analytics.py`

### 11. Model Performance Shows No Data
- **Problem**: `context_dimensions` table remained empty because `record_context_dimension` was never called
- **Solution**: 
  - Added fallback logic to query `token_usage` table when `context_dimensions` is empty
  - Added context dimension recording in request success path
  - Model performance now displays data even on fresh installations
- **Files Modified**: `aisbf/analytics.py`, `aisbf/handlers.py`

## New Features

### Enhanced Debug Logging
All tracking operations now log:
- Full parameter dump for every database insert
- SQL queries being executed
- Number of rows affected
- Full traceback on errors
- Cost calculation breakdown with 8 decimal precision

### Time Range Options
Analytics page now supports:
- Last 1 Hour
- Last 6 Hours
- Last 24 Hours (Default)
- Yesterday (NEW)
- Last 7 Days
- Last 30 Days
- Last 90 Days
- Custom Range (with date/time pickers)

Graph title and all analytics sections dynamically update based on selected range.

### Model Performance Tracking
- Automatically records context dimensions on each request
- Falls back to token_usage data when context_dimensions is empty
- Shows performance metrics for all providers with activity in selected time range

## Backwards Compatibility

All changes maintain 100% backwards compatibility:
- Fallback INSERT logic for old database schemas
- Support for both dict and object responses
- All existing providers continue to work
- Streaming requests remain functional

## Version Updates

Updated version to `0.99.33` in:
- `aisbf/__init__.py`
- `pyproject.toml`
- `setup.py`

## Testing Recommendations

1. Verify model retrieval from lisa.nexlab.net works correctly
2. Test analytics data displays correctly in web dashboard with MySQL
3. Confirm cost calculations show in logs for all provider types
4. Test "Yesterday" time range filter
5. Verify database migrations work on live MySQL instances
6. Test all existing providers (kiro-cli, claude, qwen, codex, kilo)
7. Verify graph title updates correctly for each time range selection
8. Confirm model performance shows data for selected time range
9. Verify cost overview reflects selected time period
10. Check that recommendations are based on filtered time range data
11. Test model performance displays on fresh installations with empty context_dimensions table
