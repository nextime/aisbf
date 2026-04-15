# Username and Display Name Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement separate username and display_name fields to handle OAuth signup with full names while maintaining clean usernames for system use.

**Architecture:** Add display_name column to users table, update user creation and retrieval functions, modify OAuth callbacks to generate usernames from display names with email fallback, and update UI to display display_name where appropriate.

**Tech Stack:** Python, SQLite/MySQL, FastAPI, Jinja2 templates

---

## File Structure

**Modified Files:**
- `aisbf/database.py`: Add display_name column, update user CRUD operations
- `main.py`: Update OAuth callback handlers and user creation endpoints
- `templates/dashboard/users.html`: Display display_name in user lists
- `templates/dashboard/profile.html`: Allow display_name editing
- `templates/dashboard/signup.html`: Handle display_name in signup flow

**New Files:**
- `docs/superpowers/plans/2026-04-15-username-display-name-plan.md`: This plan document

---

### Task 1: Database Schema Migration

**Files:**
- Modify: `aisbf/database.py`

- [ ] **Step 1: Add display_name column to users table**

In `database.py`, find the users table creation in `init_database()` around line 2620. Add the display_name column:

```python
cursor.execute(f'''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY {auto_increment},
        username VARCHAR(255) UNIQUE NOT NULL,
        email VARCHAR(255) UNIQUE,
        display_name VARCHAR(255),
        password_hash VARCHAR(255) NOT NULL,
        role VARCHAR(50) DEFAULT 'user',
        created_by VARCHAR(255),
        created_at TIMESTAMP DEFAULT {timestamp_default},
        last_login TIMESTAMP NULL,
        is_active {boolean_type} DEFAULT 1,
        email_verified {boolean_type} DEFAULT 0,
        verification_token VARCHAR(255),
        verification_token_expires TIMESTAMP NULL,
        last_verification_email_sent TIMESTAMP NULL
    )
''')
```

- [ ] **Step 2: Add migration for existing users**

After table creation, add migration logic to populate display_name for existing users:

```python
# Migration for existing users
cursor.execute("UPDATE users SET display_name = username WHERE display_name IS NULL")
```

- [ ] **Step 3: Update user retrieval functions**

Update `get_user_by_id()`, `get_user_by_username()`, `get_user_by_email()` to include display_name in returned dict.

For example, in `get_user_by_id()`:

```python
cursor.execute('''
    SELECT id, username, email, display_name, role, is_active, email_verified, created_at, last_verification_email_sent
    FROM users
    WHERE id = ?
''', (user_id,))
```

And in the result processing:

```python
if row:
    return {
        'id': row[0],
        'username': row[1],
        'email': row[2],
        'display_name': row[3] or row[1],  # Default to username if display_name empty
        'role': row[4],
        'is_active': row[5],
        'email_verified': row[6],
        'created_at': row[7],
        'last_verification_email_sent': row[8]
    }
```

- [ ] **Step 4: Update create_user function**

Modify `create_user()` to accept display_name parameter:

```python
def create_user(self, username: str, password_hash: str, role: str = 'user', created_by: str = None,
                email: str = None, email_verified: bool = False, display_name: str = None):
```

In the INSERT statement:

```python
INSERT INTO users (username, email, password_hash, role, created_by, email_verified, display_name)
VALUES (?, ?, ?, ?, ?, ?, ?)
```

And parameters:

```python
(username, email, password_hash, role, created_by, 1 if email_verified else 0, display_name or username)
```

- [ ] **Step 5: Update user update functions**

Modify `update_user()` and `update_user_profile()` to handle display_name:

```python
def update_user(self, user_id: int, username: str, password_hash: str = None, role: str = 'user',
                is_active: bool = True, display_name: str = None):
```

In the UPDATE query:

```python
UPDATE users SET username = ?, password_hash = ?, role = ?, is_active = ?, display_name = ? WHERE id = ?
```

- [ ] **Step 6: Test database changes**

Run the application and check that users table has display_name column and existing users have it populated.

- [ ] **Step 7: Commit database changes**

```bash
git add aisbf/database.py
git commit -m "feat: add display_name column to users table"
```

### Task 2: Username Sanitization Utility

**Files:**
- Modify: `aisbf/database.py`

- [ ] **Step 1: Add sanitize_username function**

Add a utility function to sanitize usernames:

```python
def sanitize_username(self, input_str: str) -> str:
    """Sanitize string to valid username format."""
    if not input_str:
        return ""
    
    # Lowercase
    result = input_str.lower()
    
    # Replace spaces with underscores
    result = result.replace(" ", "_")
    
    # Remove invalid characters (keep a-z, 0-9, -, _, .)
    import re
    result = re.sub(r'[^a-z0-9\-_.]', '', result)
    
    # Trim and ensure length
    result = result.strip("._-")
    if len(result) < 3:
        return ""
    if len(result) > 50:
        result = result[:50].rstrip("._-")
    
    return result
```

- [ ] **Step 2: Add generate_username_from_display_name function**

Add function to generate username from display_name with email fallback:

```python
def generate_username_from_display_name(self, display_name: str, email: str) -> str:
    """Generate clean username from display_name, fallback to email."""
    # Try display_name first
    if display_name and display_name.strip():
        username_base = self.sanitize_username(display_name)
        if username_base:
            return username_base
    
    # Fallback to email prefix
    if email and '@' in email:
        email_prefix = email.split('@')[0]
        username_base = self.sanitize_username(email_prefix)
        if username_base:
            return username_base
    
    # Final fallback
    return "user"
```

- [ ] **Step 3: Add find_unique_username function**

Add function to ensure username uniqueness:

```python
def find_unique_username(self, base_username: str) -> str:
    """Find a unique username, appending counter if needed."""
    username = base_username
    counter = 1
    
    while self.get_user_by_username(username):
        username = f"{base_username}{counter}"
        counter += 1
        if counter > 100:  # Prevent infinite loop
            raise ValueError("Could not generate unique username")
    
    return username
```

- [ ] **Step 4: Test sanitization functions**

Create a simple test to verify sanitization works:

```python
# Test in Python REPL
db = Database()
print(db.sanitize_username('Stefy "nextime" Lanza'))  # Should output: 'stefy_nextime_lanza'
print(db.generate_username_from_display_name('Stefy "nextime" Lanza', 'test@example.com'))  # Should output: 'stefy_nextime_lanza'
```

- [ ] **Step 5: Commit utility functions**

```bash
git add aisbf/database.py
git commit -m "feat: add username sanitization and generation utilities"
```

### Task 3: Update OAuth Google Callback

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Update Google OAuth callback logic**

In `oauth2_google_callback()` around line 2950, modify username generation:

Replace:
```python
google_username = user_info.get('name') or email.split('@')[0]
```

With:
```python
display_name = user_info.get('name', '')
google_username = db.generate_username_from_display_name(display_name, email)
google_username = db.find_unique_username(google_username)
```

- [ ] **Step 2: Update user creation call**

In the user creation:
```python
user_id = db.create_user(final_username, password_hash, 'user', None, email, True)
```

Change to:
```python
user_id = db.create_user(google_username, password_hash, 'user', None, email, True, display_name)
```

- [ ] **Step 3: Update session setting**

```python
request.session['username'] = google_username
```

- [ ] **Step 4: Test Google OAuth signup**

Set up Google OAuth and test signup with a display name containing spaces/quotes.

- [ ] **Step 5: Commit Google OAuth changes**

```bash
git add main.py
git commit -m "feat: update Google OAuth to use display_name for username generation"
```

### Task 4: Update OAuth GitHub Callback

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Update GitHub OAuth callback logic**

In `oauth2_github_callback()` around line 3100, modify username generation:

Replace:
```python
github_username = user_info.get('login') or user_info.get('name') or email.split('@')[0]
```

With:
```python
display_name = user_info.get('name', '') or user_info.get('login', '')
github_username = db.generate_username_from_display_name(display_name, email)
github_username = db.find_unique_username(github_username)
```

- [ ] **Step 2: Update user creation call**

In the user creation:
```python
user_id = db.create_user(final_username, password_hash, 'user', None, email, True)
```

Change to:
```python
user_id = db.create_user(github_username, password_hash, 'user', None, email, True, display_name)
```

- [ ] **Step 3: Update session setting**

```python
request.session['username'] = github_username
```

- [ ] **Step 4: Test GitHub OAuth signup**

Set up GitHub OAuth and test signup with a display name containing spaces.

- [ ] **Step 5: Commit GitHub OAuth changes**

```bash
git add main.py
git commit -m "feat: update GitHub OAuth to use display_name for username generation"
```

### Task 5: Update User Management Endpoints

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Update admin user creation**

In `dashboard_users_add()` around line 4460, update create_user call:

```python
user_id = db.create_user(username, password_hash, role, admin_username, email, False, username)
```

The last parameter is display_name, defaulting to username.

- [ ] **Step 2: Update admin user editing**

In `dashboard_users_edit()` around line 4490, update update_user call:

```python
db.update_user(user_id, username, password_hash if password else None, role, is_active, username)
```

- [ ] **Step 3: Update user profile endpoint**

In the profile update endpoint around line 2554, update to handle display_name:

Add display_name parameter to form and update call:

```python
display_name: str = Form("")
# ...
db.update_user_profile(user_id, username, display_name)
```

And update the update_user_profile function in database.py to accept display_name.

- [ ] **Step 4: Update signup form handling**

In signup endpoint, ensure display_name is set to username initially.

- [ ] **Step 5: Test user management**

Test creating/editing users via admin panel and profile settings.

- [ ] **Step 6: Commit user management changes**

```bash
git add main.py aisbf/database.py
git commit -m "feat: update user management endpoints to handle display_name"
```

### Task 6: Update UI Templates

**Files:**
- Modify: `templates/dashboard/users.html`
- Modify: `templates/dashboard/profile.html`

- [ ] **Step 1: Update users list to show display_name**

In `users.html`, change username display to display_name where appropriate:

```html
<td>{{ user.display_name or user.username }}</td>
```

- [ ] **Step 2: Update profile template to allow display_name editing**

In `profile.html`, add display_name field:

```html
<label for="display_name">Display Name</label>
<input type="text" id="display_name" name="display_name" value="{{ user.display_name or user.username }}">
```

- [ ] **Step 3: Test UI changes**

Load user list and profile pages, verify display_name shows and can be edited.

- [ ] **Step 4: Commit UI changes**

```bash
git add templates/dashboard/users.html templates/dashboard/profile.html
git commit -m "feat: update UI to display and edit display_name"
```

### Task 7: Integration Testing

**Files:**
- N/A (manual testing)

- [ ] **Step 1: Test OAuth signup with various names**

Test Google/GitHub OAuth with names like:
- "John Doe"
- "Mary Jane Watson-Smith"
- "Dr. Strange"
- Names with quotes, apostrophes, etc.

- [ ] **Step 2: Test username conflicts**

Create users with similar names and verify counters work.

- [ ] **Step 3: Test admin user management**

Create/edit users via admin panel, verify display_name handling.

- [ ] **Step 4: Test profile editing**

Edit display_name in user profile, verify it saves and displays correctly.

- [ ] **Step 5: Test backward compatibility**

Verify existing users without display_name work correctly (should default to username).

- [ ] **Step 6: Final commit**

```bash
git commit -m "feat: complete username and display_name implementation"
```