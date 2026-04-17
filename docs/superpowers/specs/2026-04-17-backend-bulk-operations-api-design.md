# Backend Bulk Operations API Design

## Overview
Add POST /dashboard/users/bulk endpoint to handle bulk user management operations (enable, disable, delete, tier change) with proper validation, error handling, and partial failure support.

## Architecture
- **New Endpoint**: POST /dashboard/users/bulk in main.py
- **Authentication**: Admin-only access using existing require_admin middleware
- **Input Validation**: JSON body with action, user_ids, extra_data (for tier operations)
- **Processing**: Sequential database operations with individual success/failure tracking
- **Response**: JSON with success status and operation summary message

## Components

### Input Validation
- Require admin authentication
- Parse JSON: `{"action": "enable|disable|delete|tier", "user_ids": [1,2,3], "extra_data": {"tier_id": 1}}`
- Validate action in allowed set: `["enable", "disable", "delete", "tier"]`
- Validate user_ids as non-empty list of integers
- For tier action: validate extra_data.tier_id exists and references valid tier

### Action Processing
- **enable**: Call `db.update_user(user_id, None, None, None, True)` for each user
- **disable**: Call `db.update_user(user_id, None, None, None, False)` for each user  
- **delete**: Call `db.delete_user(user_id)` for each user
- **tier**: Call `db.set_user_tier(user_id, tier_id)` for each user (after tier validation)

### Error Handling
- Individual operation failures don't stop processing others
- Track successful vs failed operations per user
- Return 500 for unexpected exceptions with error details
- Log errors for debugging

### Response Format
- Success: `{"success": true, "message": "Enabled 3 of 3 users"}`
- Partial failure: `{"success": true, "message": "Enabled 2 of 3 users (1 failed)"}`
- Total failure: `{"success": false, "error": "All operations failed"}`
- Validation error: `{"success": false, "error": "Invalid action"}`

## Data Flow
1. Request → require_admin auth check
2. Parse/validate JSON body
3. Validate tier existence (if tier action)
4. Process each user_id sequentially:
   - Execute appropriate db operation
   - Track success/failure
5. Generate summary message
6. Return JSON response

## Testing
- Unit test with curl: `curl -X POST -H "Authorization: Bearer <token>" -H "Content-Type: application/json" -d '{"action":"enable","user_ids":[1,2]}' http://localhost:8000/dashboard/users/bulk`
- Verify response format and database state changes
- Test partial failures and error cases

## Security Considerations
- Admin-only endpoint (enforced by require_admin)
- Input validation prevents SQL injection
- No sensitive data in responses
- Operations logged for audit trail

## Implementation Notes
- Follow existing main.py patterns for route definition and error handling
- Use DatabaseRegistry.get_config_database() for db access
- Maintain compatibility with existing individual user operation endpoints