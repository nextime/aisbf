# Username and Display Name Handling Design

## Overview
Implement separate username and display_name fields to handle OAuth signup with full names while maintaining clean usernames for system use.

## Problem Statement
Google OAuth returns display names like "Stefy "nextime" Lanza" which contain spaces and special characters not allowed in usernames. Current system tries to use raw display name as username, causing validation failures.

## Solution
- Add `display_name` VARCHAR(255) column to users table
- Generate clean username from display_name (with email fallback)
- Store raw OAuth display name in display_name field
- Use display_name for UI display, username for system identification

## Database Schema Changes
### Users Table
```sql
ALTER TABLE users ADD COLUMN display_name VARCHAR(255);
UPDATE users SET display_name = username WHERE display_name IS NULL;
```

### Affected Queries
- All SELECT from users: include display_name
- INSERT users: accept display_name parameter
- UPDATE users: allow display_name changes

## Username Generation Logic
### OAuth Signup Flow
1. Get display_name from OAuth provider:
   - Google: `user_info.get('name')`
   - GitHub: `user_info.get('name')` or `user_info.get('login')`

2. Generate username:
   ```python
   if display_name and display_name.strip():
       # Sanitize display_name
       username_base = sanitize(display_name)
   else:
       # Fallback to email
       username_base = sanitize(email.split('@')[0])

   # Ensure unique
   username = find_unique_username(username_base)
   ```

3. Sanitization rules:
   - Lowercase
   - Remove invalid characters (keep a-z, A-Z, 0-9, -, _, .)
   - Replace spaces with underscores
   - Length 3-50 characters
   - Trim whitespace

4. Uniqueness handling:
   - Check if username exists
   - If conflict, append counter: username1, username2, etc.

## Code Changes Required
### Database Layer (database.py)
- Update table creation/migration
- Update user creation functions
- Update user retrieval functions

### OAuth Handlers (main.py)
- Update Google OAuth callback
- Update GitHub OAuth callback
- Pass display_name to user creation

### User Management
- Update admin user creation
- Update user profile editing
- Update signup form handling

### UI Changes
- Display display_name in user lists
- Allow display_name editing in profile
- Show username in technical contexts

## Migration Strategy
1. Add display_name column with NULL allowed initially
2. Populate existing users: display_name = username
3. Make display_name NOT NULL with default ''
4. Update all code to handle display_name
5. Test OAuth signup with display names

## Testing Requirements
- OAuth signup with names containing spaces/quotes
- Username conflict resolution
- Display name editing
- Backward compatibility with existing users
- UI displays display_name correctly

## Success Criteria
- OAuth signup works with any display name format
- Usernames are always valid and unique
- Display names preserve user identity
- Existing functionality unchanged
- UI shows appropriate names in context</content>
<parameter name="filePath">docs/superpowers/specs/2026-04-15-username-display-name-design.md