# User Management Page Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add pagination, search, and sorting capabilities to the admin user management page for better usability with large user bases.

**Architecture:** Server-side pagination with AJAX frontend updates. Database queries support LIMIT/OFFSET, WHERE filtering, and ORDER BY sorting. URL maintains state for bookmarking.

**Tech Stack:** Python/FastAPI backend, Jinja2 templates, vanilla JavaScript, SQLite database.

---

## File Structure

**Modified Files:**
- `aisbf/database.py` - Add pagination/search/sorting to get_users() function
- `main.py` - Update /dashboard/users route to handle query parameters
- `templates/dashboard/users.html` - Add search input, sortable headers, pagination controls, and AJAX JavaScript

**No New Files Created** - All changes are modifications to existing components.

---

### Task 1: Update Database Layer - get_users() Function

**Files:**
- Modify: `aisbf/database.py` (around line 1012)

- [ ] **Step 1: Add new get_users_paginated method signature**

```python
def get_users_paginated(self, page: int = 1, limit: int = 25, search: str = None,
                       order_by: str = 'created_at', direction: str = 'desc') -> Dict:
    """
    Get paginated users with search and sorting.

    Args:
        page: Page number (1-based)
        limit: Items per page
        search: Search term for username/email/display_name
        order_by: Column to sort by (username, last_login, created_at, tier_name)
        direction: Sort direction (asc, desc)

    Returns:
        Dict with 'users' list and 'total' count
    """
```

- [ ] **Step 2: Implement search and sorting logic**

```python
# Build WHERE clause for search
where_clause = ""
params = []
if search:
    search_term = f"%{search}%"
    where_clause = """WHERE (u.username LIKE ? OR u.email LIKE ? OR u.display_name LIKE ?)"""
    params.extend([search_term, search_term, search_term])

# Build ORDER BY clause
valid_columns = {'username', 'last_login', 'created_at', 'tier_name'}
if order_by not in valid_columns:
    order_by = 'created_at'
if direction not in ['asc', 'desc']:
    direction = 'desc'

order_clause = f"ORDER BY {order_by} {direction}"
```

- [ ] **Step 3: Implement pagination query**

```python
# Calculate offset
offset = (page - 1) * limit

# Build main query
query = f"""
    SELECT u.id, u.username, u.email, u.role, u.created_by, u.created_at,
           u.last_login, u.is_active, u.tier_id, t.name as tier_name
    FROM users u
    LEFT JOIN account_tiers t ON u.tier_id = t.id
    {where_clause}
    {order_clause}
    LIMIT ? OFFSET ?
"""

params.extend([limit, offset])
```

- [ ] **Step 4: Add total count query**

```python
# Get total count for pagination
count_query = f"""
    SELECT COUNT(*) as total
    FROM users u
    LEFT JOIN account_tiers t ON u.tier_id = t.id
    {where_clause}
"""

cursor.execute(count_query, params[:-2])  # Remove limit/offset params
total = cursor.fetchone()[0]
```

- [ ] **Step 5: Execute queries and return results**

```python
cursor.execute(query, params)

# Use column names from cursor description
columns = [col[0] for col in cursor.description]

users = []
for row in cursor.fetchall():
    user = dict(zip(columns, row))
    # Normalize boolean fields
    user['is_active'] = bool(user['is_active']) if user['is_active'] is not None else True
    users.append(user)

return {'users': users, 'total': total}
```

- [ ] **Step 6: Run basic test to verify function exists**

Run: `python -c "from aisbf.database import DatabaseRegistry; db = DatabaseRegistry.get_config_database(); print('Function exists:', hasattr(db, 'get_users_paginated'))"`
Expected: Function exists: True

- [ ] **Step 7: Commit database changes**

```bash
git add aisbf/database.py
git commit -m "feat: add get_users_paginated method to database layer

- Support pagination with LIMIT/OFFSET
- Case-insensitive search across username, email, display_name
- Sorting by username, last_login, created_at, tier_name
- Return both users list and total count for pagination"
```

---

### Task 2: Update API Route - /dashboard/users

**Files:**
- Modify: `main.py` (around line 4811)

- [ ] **Step 1: Update route signature to accept query parameters**

```python
@app.get("/dashboard/users", response_class=HTMLResponse)
async def dashboard_users(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100),
    search: str = Query(None, max_length=100),
    order_by: str = Query('created_at', regex='^(username|last_login|created_at|tier_name)$'),
    direction: str = Query('desc', regex='^(asc|desc)$')
):
```

- [ ] **Step 2: Update function to use new database method**

```python
auth_check = require_admin(request)
if auth_check:
    return auth_check

from aisbf.database import get_database
db = DatabaseRegistry.get_config_database()

# Get paginated users
result = db.get_users_paginated(
    page=page,
    limit=limit,
    search=search,
    order_by=order_by,
    direction=direction
)

users = result['users']
total_users = result['total']
```

- [ ] **Step 3: Calculate pagination metadata**

```python
# Calculate pagination info
total_pages = (total_users + limit - 1) // limit  # Ceiling division
current_page = min(page, total_pages) if total_pages > 0 else 1
start_item = (current_page - 1) * limit + 1
end_item = min(current_page * limit, total_users)

# Get all tiers for assignment dropdown
tiers = db.get_all_tiers()
```

- [ ] **Step 4: Update template context**

```python
return templates.TemplateResponse(
    request=request,
    name="dashboard/users.html",
    context={
        "request": request,
        "session": request.session,
        "users": users,
        "tiers": tiers,
        "pagination": {
            "current_page": current_page,
            "total_pages": total_pages,
            "total_users": total_users,
            "start_item": start_item,
            "end_item": end_item,
            "limit": limit,
            "has_prev": current_page > 1,
            "has_next": current_page < total_pages
        },
        "filters": {
            "search": search or "",
            "order_by": order_by,
            "direction": direction
        }
    }
)
```

- [ ] **Step 5: Test route loads without errors**

Start server with `python main.py` and visit `/dashboard/users` as admin user
Expected: Page loads without errors, shows users with pagination info

- [ ] **Step 6: Commit API changes**

```bash
git add main.py
git commit -m "feat: update /dashboard/users route for pagination and filtering

- Add query parameters: page, limit, search, order_by, direction
- Use new get_users_paginated database method
- Calculate pagination metadata (total pages, current range)
- Pass filters and pagination data to template"
```

---

### Task 3: Update Template - Search and Sorting UI

**Files:**
- Modify: `templates/dashboard/users.html` (around line 22)

- [ ] **Step 1: Add search and filter controls above table**

```html
<!-- Search and Filter Controls -->
<div style="margin-bottom: 20px; padding: 15px; background: #0f3460; border-radius: 8px;">
    <div style="display: flex; gap: 15px; align-items: center; flex-wrap: wrap;">
        <div style="flex: 1; min-width: 200px;">
            <label for="search-input" style="display: block; margin-bottom: 5px; color: #e0e0e0;">Search Users</label>
            <input type="text" id="search-input" placeholder="Search by username, email, or display name..."
                   value="{{ filters.search }}" style="width: 100%; padding: 8px; border-radius: 4px; border: 1px solid #0f3460; background: #1a1a2e; color: #e0e0e0;">
        </div>
        <div style="display: flex; gap: 10px; align-items: flex-end;">
            <button id="search-btn" class="btn" style="padding: 8px 16px;">Search</button>
            <button id="clear-btn" class="btn btn-secondary" style="padding: 8px 16px;">Clear</button>
        </div>
    </div>
</div>
```

- [ ] **Step 2: Update table headers to be sortable**

```html
<thead>
    <tr>
        <th>ID</th>
        <th class="sortable" data-column="username">
            Username
            <span class="sort-indicator" data-column="username">
                {% if filters.order_by == 'username' %}
                    {% if filters.direction == 'asc' %}▲{% else %}▼{% endif %}
                {% endif %}
            </span>
        </th>
        <th>Email</th>
        <th>Role</th>
        <th>Tier</th>
        <th>Created By</th>
        <th class="sortable" data-column="created_at">
            Created At
            <span class="sort-indicator" data-column="created_at">
                {% if filters.order_by == 'created_at' %}
                    {% if filters.direction == 'asc' %}▲{% else %}▼{% endif %}
                {% endif %}
            </span>
        </th>
        <th class="sortable" data-column="last_login">
            Last Login
            <span class="sort-indicator" data-column="last_login">
                {% if filters.order_by == 'last_login' %}
                    {% if filters.direction == 'asc' %}▲{% else %}▼{% endif %}
                {% endif %}
            </span>
        </th>
        <th>Active</th>
        <th>Actions</th>
    </tr>
</thead>
```

- [ ] **Step 3: Add pagination controls below table**

```html
<!-- Pagination Controls -->
{% if pagination.total_pages > 1 %}
<div style="margin-top: 20px; padding: 15px; background: #0f3460; border-radius: 8px;">
    <div style="display: flex; justify-content: between; align-items: center; flex-wrap: wrap; gap: 15px;">
        <div style="color: #e0e0e0;">
            Showing {{ pagination.start_item }}-{{ pagination.end_item }} of {{ pagination.total_users }} users
        </div>

        <div style="display: flex; gap: 10px; align-items: center;">
            <label for="page-size" style="color: #e0e0e0; margin-right: 5px;">Show:</label>
            <select id="page-size" style="padding: 5px; border-radius: 4px; border: 1px solid #0f3460; background: #1a1a2e; color: #e0e0e0;">
                <option value="10" {% if pagination.limit == 10 %}selected{% endif %}>10</option>
                <option value="25" {% if pagination.limit == 25 %}selected{% endif %}>25</option>
                <option value="50" {% if pagination.limit == 50 %}selected{% endif %}>50</option>
                <option value="100" {% if pagination.limit == 100 %}selected{% endif %}>100</option>
            </select>

            <div style="display: flex; gap: 5px;">
                <button id="prev-btn" class="btn btn-secondary" {% if not pagination.has_prev %}disabled{% endif %} style="padding: 8px 12px;">
                    ← Previous
                </button>

                <span style="color: #e0e0e0; padding: 8px 12px; background: #1a1a2e; border-radius: 4px;">
                    Page {{ pagination.current_page }} of {{ pagination.total_pages }}
                </span>

                <button id="next-btn" class="btn btn-secondary" {% if not pagination.has_next %}disabled{% endif %} style="padding: 8px 12px;">
                    Next →
                </button>
            </div>
        </div>
    </div>
</div>
{% endif %}
```

- [ ] **Step 4: Test template renders without errors**

Visit `/dashboard/users` page
Expected: Search input, sortable headers, and pagination controls visible

- [ ] **Step 5: Commit template changes**

```bash
git add templates/dashboard/users.html
git commit -m "feat: add search input and sortable headers to users template

- Add search input field with current search value
- Make username, created_at, last_login headers sortable with indicators
- Add pagination controls with page size selector
- Include 'showing X-Y of Z' counter"
```

---

### Task 4: Add JavaScript for AJAX Updates

**Files:**
- Modify: `templates/dashboard/users.html` (around line 167)

- [ ] **Step 1: Add utility functions for URL management**

```javascript
// Utility functions for URL parameter management
function updateURLParameter(url, param, paramVal) {
    var newAdditionalURL = "";
    var tempArray = url.split("?");
    var baseURL = tempArray[0];
    var additionalURL = tempArray[1];
    var temp = "";
    if (additionalURL) {
        tempArray = additionalURL.split("&");
        for (var i = 0; i < tempArray.length; i++) {
            if (tempArray[i].split('=')[0] != param) {
                newAdditionalURL += temp + tempArray[i];
                temp = "&";
            }
        }
    }
    var rows_txt = temp + "" + param + "=" + paramVal;
    return baseURL + "?" + newAdditionalURL + rows_txt;
}

function getURLParameter(name) {
    const urlParams = new URLSearchParams(window.location.search);
    return urlParams.get(name);
}
```

- [ ] **Step 2: Add search functionality**

```javascript
// Search functionality with debouncing
let searchTimeout;
document.getElementById('search-input').addEventListener('input', function() {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
        updateUsers({ search: this.value });
    }, 300);
});

document.getElementById('search-btn').addEventListener('click', function() {
    updateUsers({ search: document.getElementById('search-input').value });
});

document.getElementById('clear-btn').addEventListener('click', function() {
    document.getElementById('search-input').value = '';
    updateUsers({ search: '' });
});
```

- [ ] **Step 3: Add sorting functionality**

```javascript
// Sorting functionality
document.querySelectorAll('.sortable').forEach(header => {
    header.addEventListener('click', function() {
        const column = this.dataset.column;
        const currentOrder = getURLParameter('order_by');
        const currentDir = getURLParameter('direction') || 'desc';

        let newDir = 'asc';
        if (currentOrder === column && currentDir === 'asc') {
            newDir = 'desc';
        }

        updateUsers({ order_by: column, direction: newDir });
    });
});
```

- [ ] **Step 4: Add pagination functionality**

```javascript
// Pagination functionality
document.getElementById('prev-btn').addEventListener('click', function() {
    const currentPage = parseInt(getURLParameter('page') || '1');
    if (currentPage > 1) {
        updateUsers({ page: currentPage - 1 });
    }
});

document.getElementById('next-btn').addEventListener('click', function() {
    const currentPage = parseInt(getURLParameter('page') || '1');
    updateUsers({ page: currentPage + 1 });
});

document.getElementById('page-size').addEventListener('change', function() {
    updateUsers({ limit: this.value, page: 1 });
});
```

- [ ] **Step 5: Add updateUsers function**

```javascript
// Main function to update users list
function updateUsers(params) {
    // Show loading state
    const tableContainer = document.querySelector('table').parentElement;
    const originalContent = tableContainer.innerHTML;
    tableContainer.innerHTML = '<div style="text-align: center; padding: 20px; color: #e0e0e0;"><div class="spinner"></div> Loading...</div>';

    // Build query parameters
    const currentParams = new URLSearchParams(window.location.search);
    Object.keys(params).forEach(key => {
        if (params[key] !== '' && params[key] !== null && params[key] !== undefined) {
            currentParams.set(key, params[key]);
        } else {
            currentParams.delete(key);
        }
    });

    // Reset to page 1 if search/sort changed
    if (params.search !== undefined || params.order_by !== undefined) {
        currentParams.set('page', '1');
    }

    // Update URL
    const newURL = window.location.pathname + (currentParams.toString() ? '?' + currentParams.toString() : '');
    window.history.pushState({}, '', newURL);

    // Fetch updated content
    fetch(newURL, {
        headers: {
            'X-Requested-With': 'XMLHttpRequest'
        }
    })
    .then(response => response.text())
    .then(html => {
        // Parse and update just the table and pagination
        const parser = new DOMParser();
        const newDoc = parser.parseFromString(html, 'text/html');

        const newTable = newDoc.querySelector('table');
        const newPagination = newDoc.querySelectorAll('[style*="margin-top: 20px"]')[0];

        tableContainer.innerHTML = originalContent;
        document.querySelector('table').replaceWith(newTable);

        const existingPagination = document.querySelector('[style*="margin-top: 20px"]');
        if (existingPagination) {
            existingPagination.replaceWith(newPagination);
        } else if (newPagination) {
            document.querySelector('table').after(newPagination);
        }
    })
    .catch(error => {
        console.error('Error updating users:', error);
        tableContainer.innerHTML = originalContent;
        showNotification('Error loading users', 'error');
    });
}
```

- [ ] **Step 6: Add loading spinner styles**

```css
.spinner {
    border: 3px solid #0f3460;
    border-top: 3px solid #4ade80;
    border-radius: 50%;
    width: 20px;
    height: 20px;
    animation: spin 1s linear infinite;
    display: inline-block;
    margin-right: 10px;
}

@keyframes spin {
    0% { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
}
```

- [ ] **Step 7: Test JavaScript loads without errors**

Visit page and check browser console
Expected: No JavaScript errors, functions defined

- [ ] **Step 8: Commit JavaScript changes**

```bash
git add templates/dashboard/users.html
git commit -m "feat: add AJAX functionality for search, sorting, and pagination

- Debounced search input with clear functionality
- Clickable sortable headers with direction indicators
- Pagination controls with previous/next buttons and page size selector
- URL state management for bookmarking
- Loading states and error handling"
```

---

### Task 5: Test Complete Functionality

**Files:**
- Test: Manual testing of complete feature

- [ ] **Step 1: Test pagination**

Navigate through multiple pages, change page sizes
Expected: Correct user ranges displayed, URL updates

- [ ] **Step 2: Test search functionality**

Search for usernames, emails, display names
Expected: Results filtered correctly, case-insensitive

- [ ] **Step 3: Test sorting**

Click column headers, verify sort order and indicators
Expected: Users sorted correctly, arrows show direction

- [ ] **Step 4: Test URL state**

Bookmark URLs, refresh page, use browser back/forward
Expected: State preserved, page loads with correct filters

- [ ] **Step 5: Test edge cases**

Empty search, invalid page numbers, no users found
Expected: Graceful handling, appropriate messages

- [ ] **Step 6: Commit if all tests pass**

```bash
git commit --allow-empty -m "test: verify complete user management enhancement functionality

- Pagination works correctly across page sizes
- Search filters users by username, email, display name
- Sorting works for all columns in both directions
- URL state maintained for bookmarking
- Edge cases handled gracefully"
```