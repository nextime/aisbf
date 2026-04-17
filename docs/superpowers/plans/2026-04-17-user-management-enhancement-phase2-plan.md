# User Management Page Enhancement - Phase 2: Advanced Filtering & Batch Actions

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add advanced filtering by user status/role and batch operations for bulk user management.

**Architecture:** Extend existing database queries and API to support additional filters. Add bulk selection UI with confirmation dialogs for destructive operations.

**Tech Stack:** Python/FastAPI backend, Jinja2 templates, vanilla JavaScript, SQLite database.

---

## File Structure

**Modified Files:**
- `aisbf/database.py` - Add status/role filtering to get_users_paginated()
- `main.py` - Update /dashboard/users route to accept status/role filter parameters
- `templates/dashboard/users.html` - Add filter dropdowns and bulk action UI

**No New Files Created** - All changes are modifications to existing components.

---

### Task 1: Update Database Layer - Add Status/Role Filtering

**Files:**
- Modify: `aisbf/database.py` (around line 1048)

- [ ] **Step 1: Update get_users_paginated method signature**

```python
def get_users_paginated(self, page: int = 1, limit: int = 25, search: str = None,
                       order_by: str = 'created_at', direction: str = 'desc',
                       status_filter: str = None, role_filter: str = None) -> Dict:
```

- [ ] **Step 2: Add status/role filtering logic**

```python
# Add status and role filtering
additional_conditions = []
params = []

if status_filter is not None:
    if status_filter in ['active', 'inactive']:
        status_value = 1 if status_filter == 'active' else 0
        additional_conditions.append("u.is_active = ?")
        params.append(status_value)

if role_filter is not None:
    if role_filter in ['admin', 'user']:
        additional_conditions.append("u.role = ?")
        params.append(role_filter)

# Combine all conditions
where_conditions = []
if search:
    search_term = f"%{search}%"
    where_conditions.append("(u.username LIKE ? OR u.email LIKE ? OR u.display_name LIKE ?)")
    params.extend([search_term, search_term, search_term])

if additional_conditions:
    where_conditions.extend(additional_conditions)

where_clause = "WHERE " + " AND ".join(where_conditions) if where_conditions else ""
```

- [ ] **Step 3: Update queries to use new where clause**

```python
# Update main query and count query to use where_clause and params
query = f"""
    SELECT u.id, u.username, u.email, u.role, u.created_by, u.created_at,
           u.last_login, u.is_active, u.tier_id, t.name as tier_name
    FROM users u
    LEFT JOIN account_tiers t ON u.tier_id = t.id
    {where_clause}
    {order_clause}
    LIMIT ? OFFSET ?
"""

count_query = f"""
    SELECT COUNT(*) as total
    FROM users u
    LEFT JOIN account_tiers t ON u.tier_id = t.id
    {where_clause}
"""
```

- [ ] **Step 4: Test the updated method**

Run: `python -c "from aisbf.database import DatabaseRegistry; db = DatabaseRegistry.get_config_database(); result = db.get_users_paginated(status_filter='active'); print('Active users:', len(result['users']))"`

Expected: Returns only active users

- [ ] **Step 5: Commit database changes**

```bash
git add aisbf/database.py
git commit -m "feat: add status and role filtering to get_users_paginated method

- Add status_filter parameter (active/inactive)
- Add role_filter parameter (admin/user)
- Combine filters with existing search functionality
- Update both main query and count query"
```

---

### Task 2: Update API Route - Add Filter Parameters

**Files:**
- Modify: `main.py` (around line 4811)

- [ ] **Step 1: Update route signature with new filter parameters**

```python
@app.get("/dashboard/users", response_class=HTMLResponse)
async def dashboard_users(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100),
    search: str = Query(None, max_length=100),
    order_by: str = Query('created_at', regex='^(username|last_login|created_at|tier_name)$'),
    direction: str = Query('desc', regex='^(asc|desc)$'),
    status_filter: str = Query(None, regex='^(active|inactive)$'),
    role_filter: str = Query(None, regex='^(admin|user)$')
):
```

- [ ] **Step 2: Update database call with new parameters**

```python
result = db.get_users_paginated(
    page=page,
    limit=limit,
    search=search,
    order_by=order_by,
    direction=direction,
    status_filter=status_filter,
    role_filter=role_filter
)
```

- [ ] **Step 3: Update template context with filter values**

```python
return templates.TemplateResponse(
    request=request,
    name="dashboard/users.html",
    context={
        "request": request,
        "session": request.session,
        "users": users,
        "tiers": tiers,
        "pagination": { ... },
        "filters": {
            "search": search or "",
            "order_by": order_by,
            "direction": direction,
            "status_filter": status_filter,
            "role_filter": role_filter
        }
    }
)
```

- [ ] **Step 4: Test route with new parameters**

Start server and visit `/dashboard/users?status_filter=active&role_filter=user`
Expected: Page loads with filtered results

- [ ] **Step 5: Commit API changes**

```bash
git add main.py
git commit -m "feat: add status and role filter parameters to /dashboard/users route

- Add status_filter (active/inactive) and role_filter (admin/user) query parameters
- Pass filter values to database method and template context
- Update route validation with regex patterns"
```

---

### Task 3: Update Template - Add Filter Dropdowns

**Files:**
- Modify: `templates/dashboard/users.html` (around line 22)

- [ ] **Step 1: Add filter dropdowns to search controls**

```html
<div style="display: flex; gap: 15px; align-items: center; flex-wrap: wrap;">
    <!-- Existing search input -->

    <div style="display: flex; gap: 10px; align-items: center;">
        <label for="status-filter" style="color: #e0e0e0; margin-right: 5px;">Status:</label>
        <select id="status-filter" style="padding: 8px; border-radius: 4px; border: 1px solid #0f3460; background: #1a1a2e; color: #e0e0e0;">
            <option value="">All</option>
            <option value="active" {% if filters.status_filter == 'active' %}selected{% endif %}>Active</option>
            <option value="inactive" {% if filters.status_filter == 'inactive' %}selected{% endif %}>Inactive</option>
        </select>

        <label for="role-filter" style="color: #e0e0e0; margin-left: 10px; margin-right: 5px;">Role:</label>
        <select id="role-filter" style="padding: 8px; border-radius: 4px; border: 1px solid #0f3460; background: #1a1a2e; color: #e0e0e0;">
            <option value="">All</option>
            <option value="admin" {% if filters.role_filter == 'admin' %}selected{% endif %}>Admin</option>
            <option value="user" {% if filters.role_filter == 'user' %}selected{% endif %}>User</option>
        </select>
    </div>
</div>
```

- [ ] **Step 2: Add bulk selection checkbox to table header**

```html
<thead>
    <tr>
        <th style="width: 40px;">
            <input type="checkbox" id="select-all" title="Select all visible users">
        </th>
        <th>ID</th>
        <!-- existing headers -->
    </tr>
</thead>
```

- [ ] **Step 3: Add checkbox to each user row**

```html
{% for user in users %}
<tr>
    <td>
        <input type="checkbox" class="user-checkbox" value="{{ user.id }}" title="Select user {{ user.display_name or user.username }}">
    </td>
    <!-- existing columns -->
</tr>
{% endfor %}
```

- [ ] **Step 4: Add bulk action bar above table**

```html
<!-- Bulk Actions Bar (hidden by default) -->
<div id="bulk-actions" style="display: none; margin-bottom: 20px; padding: 15px; background: #0f3460; border-radius: 8px;">
    <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
        <div style="color: #e0e0e0;">
            <span id="selected-count">0</span> users selected
        </div>

        <div style="display: flex; gap: 10px; align-items: center;">
            <select id="bulk-tier-select" style="padding: 8px; border-radius: 4px; border: 1px solid #0f3460; background: #1a1a2e; color: #e0e0e0;">
                <option value="">Change Tier...</option>
                {% for tier in tiers %}
                <option value="{{ tier.id }}">{{ tier.name }}{% if not tier.is_visible %} (Hidden){% endif %}</option>
                {% endfor %}
            </select>

            <button id="bulk-enable" class="btn">Enable Selected</button>
            <button id="bulk-disable" class="btn">Disable Selected</button>
            <button id="bulk-delete" class="btn btn-danger">Delete Selected</button>
            <button id="bulk-clear" class="btn btn-secondary">Clear Selection</button>
        </div>
    </div>
</div>
```

- [ ] **Step 5: Test template renders without errors**

Visit `/dashboard/users` page
Expected: Filter dropdowns, checkboxes, and bulk action bar visible

- [ ] **Step 6: Commit template changes**

```bash
git add templates/dashboard/users.html
git commit -m "feat: add status/role filter dropdowns and bulk selection UI

- Add status filter (active/inactive) and role filter (admin/user) dropdowns
- Add select all checkbox and individual user checkboxes
- Add bulk action bar with tier change, enable/disable, delete buttons
- Include selection counter and clear selection button"
```

---

### Task 4: Add JavaScript for Filters and Bulk Actions

**Files:**
- Modify: `templates/dashboard/users.html` (around line 350)

- [ ] **Step 1: Add filter change handlers**

```javascript
// Filter change handlers
document.getElementById('status-filter').addEventListener('change', function() {
    updateUsers({ status_filter: this.value || null });
});

document.getElementById('role-filter').addEventListener('change', function() {
    updateUsers({ role_filter: this.value || null });
});
```

- [ ] **Step 2: Add bulk selection handlers**

```javascript
// Bulk selection handlers
document.getElementById('select-all').addEventListener('change', function() {
    const checkboxes = document.querySelectorAll('.user-checkbox');
    checkboxes.forEach(cb => cb.checked = this.checked);
    updateBulkActionsVisibility();
});

document.addEventListener('change', function(e) {
    if (e.target.classList.contains('user-checkbox')) {
        updateBulkActionsVisibility();
        updateSelectAllState();
    }
});
```

- [ ] **Step 3: Add bulk action handlers**

```javascript
// Bulk action handlers
document.getElementById('bulk-enable').addEventListener('click', function() {
    performBulkAction('enable', 'enable selected users');
});

document.getElementById('bulk-disable').addEventListener('click', function() {
    performBulkAction('disable', 'disable selected users');
});

document.getElementById('bulk-delete').addEventListener('click', function() {
    performBulkAction('delete', 'delete selected users', true);
});

document.getElementById('bulk-tier-select').addEventListener('change', function() {
    if (this.value) {
        performBulkAction('tier', `change tier for selected users`, false, this.value);
        this.value = ''; // Reset dropdown
    }
});

document.getElementById('bulk-clear').addEventListener('click', function() {
    clearSelection();
});
```

- [ ] **Step 4: Implement helper functions**

```javascript
function updateBulkActionsVisibility() {
    const selectedCount = document.querySelectorAll('.user-checkbox:checked').length;
    const bulkActions = document.getElementById('bulk-actions');
    const selectedCountEl = document.getElementById('selected-count');

    if (selectedCount > 0) {
        bulkActions.style.display = 'block';
        selectedCountEl.textContent = selectedCount;
    } else {
        bulkActions.style.display = 'none';
    }
}

function updateSelectAllState() {
    const checkboxes = document.querySelectorAll('.user-checkbox');
    const selectAll = document.getElementById('select-all');
    const checkedBoxes = document.querySelectorAll('.user-checkbox:checked');

    selectAll.checked = checkboxes.length > 0 && checkedBoxes.length === checkboxes.length;
    selectAll.indeterminate = checkedBoxes.length > 0 && checkedBoxes.length < checkboxes.length;
}

function clearSelection() {
    document.querySelectorAll('.user-checkbox, #select-all').forEach(cb => {
        cb.checked = false;
        cb.indeterminate = false;
    });
    updateBulkActionsVisibility();
}

function performBulkAction(action, description, destructive = false, extraData = null) {
    const selectedIds = Array.from(document.querySelectorAll('.user-checkbox:checked')).map(cb => parseInt(cb.value));

    if (selectedIds.length === 0) {
        showNotification('No users selected', 'error');
        return;
    }

    if (destructive && !confirm(`Are you sure you want to ${description}? This action cannot be undone.`)) {
        return;
    }

    // Show loading state
    const bulkActions = document.getElementById('bulk-actions');
    const originalContent = bulkActions.innerHTML;
    bulkActions.innerHTML = '<div style="text-align: center; padding: 10px; color: #e0e0e0;"><div class="spinner"></div> Processing...</div>';

    // Prepare request data
    const requestData = {
        action: action,
        user_ids: selectedIds
    };
    if (extraData) {
        requestData.extra_data = extraData;
    }

    fetch('/dashboard/users/bulk', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(requestData)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showNotification(data.message || `Successfully ${action}d ${selectedIds.length} users`, 'success');
            clearSelection();
            // Refresh the current page data
            updateUsers({});
        } else {
            showNotification(data.error || 'Bulk operation failed', 'error');
            bulkActions.innerHTML = originalContent;
        }
    })
    .catch(error => {
        console.error('Bulk action error:', error);
        showNotification('Error performing bulk action', 'error');
        bulkActions.innerHTML = originalContent;
    });
}
```

- [ ] **Step 5: Call updateBulkActionsVisibility on page load and after AJAX updates**

```javascript
// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    updateBulkActionsVisibility();
    // ... existing code
});

// After AJAX updates
function attachEventListeners() {
    // ... existing code
    updateBulkActionsVisibility();
}
```

- [ ] **Step 6: Test JavaScript loads without errors**

Visit page and check browser console
Expected: No JavaScript errors, bulk action functions defined

- [ ] **Step 7: Commit JavaScript changes**

```bash
git add templates/dashboard/users.html
git commit -m "feat: add JavaScript for advanced filtering and bulk actions

- Filter change handlers for status and role dropdowns
- Bulk selection with select all and individual checkboxes
- Bulk action handlers for enable/disable/delete/tier change
- Selection counter and clear selection functionality
- Confirmation dialogs for destructive operations"
```

---

### Task 5: Add Backend Bulk Operations API

**Files:**
- Modify: `main.py` (around line 4960)

- [ ] **Step 1: Add bulk operations route**

```python
@app.post("/dashboard/users/bulk")
async def dashboard_users_bulk(request: Request):
    """Handle bulk user operations"""
    auth_check = require_admin(request)
    if auth_check:
        return auth_check

    from aisbf.database import get_database
    db = DatabaseRegistry.get_config_database()

    try:
        body = await request.json()
        action = body.get('action')
        user_ids = body.get('user_ids', [])
        extra_data = body.get('extra_data')

        if not action or not user_ids:
            return JSONResponse({"success": False, "error": "Action and user_ids required"}, status_code=400)

        # Validate user_ids
        if not isinstance(user_ids, list) or not all(isinstance(uid, int) for uid in user_ids):
            return JSONResponse({"success": False, "error": "user_ids must be a list of integers"}, status_code=400)

        if action == 'enable':
            success_count = 0
            for user_id in user_ids:
                if db.update_user(user_id, None, None, None, True):
                    success_count += 1
            return JSONResponse({"success": True, "message": f"Enabled {success_count} of {len(user_ids)} users"})

        elif action == 'disable':
            success_count = 0
            for user_id in user_ids:
                if db.update_user(user_id, None, None, None, False):
                    success_count += 1
            return JSONResponse({"success": True, "message": f"Disabled {success_count} of {len(user_ids)} users"})

        elif action == 'delete':
            success_count = 0
            for user_id in user_ids:
                try:
                    db.delete_user(user_id)
                    success_count += 1
                except Exception:
                    pass  # Continue with other deletions
            return JSONResponse({"success": True, "message": f"Deleted {success_count} of {len(user_ids)} users"})

        elif action == 'tier':
            tier_id = extra_data
            if not tier_id:
                return JSONResponse({"success": False, "error": "tier_id required for tier action"}, status_code=400)

            # Verify tier exists
            tier = db.get_tier_by_id(tier_id)
            if not tier:
                return JSONResponse({"success": False, "error": "Tier not found"}, status_code=404)

            success_count = 0
            for user_id in user_ids:
                if db.set_user_tier(user_id, tier_id):
                    success_count += 1
            return JSONResponse({"success": True, "message": f"Changed tier for {success_count} of {len(user_ids)} users"})

        else:
            return JSONResponse({"success": False, "error": "Invalid action"}, status_code=400)

    except Exception as e:
        logger.error(f"Bulk operation error: {e}")
        return JSONResponse({"success": False, "error": "Internal server error"}, status_code=500)
```

- [ ] **Step 2: Test bulk operations endpoint**

Use curl or browser dev tools to test POST /dashboard/users/bulk
Expected: Returns JSON response with success/error

- [ ] **Step 3: Commit bulk operations API**

```bash
git add main.py
git commit -m "feat: add bulk operations API endpoint for user management

- POST /dashboard/users/bulk endpoint for bulk actions
- Support enable, disable, delete, and tier change operations
- Validate inputs and provide detailed success/error messages
- Handle partial failures gracefully"
```

---

### Task 6: Test Complete Advanced Features

**Files:**
- Test: Manual testing of advanced filtering and bulk actions

- [ ] **Step 1: Test status filtering**

Select "Active" filter - verify only active users shown
Select "Inactive" filter - verify only inactive users shown
Clear filter - verify all users shown

- [ ] **Step 2: Test role filtering**

Select "Admin" filter - verify only admin users shown
Select "User" filter - verify only regular users shown
Combine status + role filters - verify intersection works

- [ ] **Step 3: Test bulk selection**

Check individual checkboxes - verify selection counter updates
Check "select all" - verify all users selected
Uncheck some - verify select all becomes indeterminate
Clear selection - verify all unchecked and bar hidden

- [ ] **Step 4: Test bulk enable/disable**

Select users, click Enable - verify users become active
Select users, click Disable - verify users become inactive
Verify confirmation dialogs and success messages

- [ ] **Step 5: Test bulk tier change**

Select users, choose new tier - verify tier updates
Verify success messages and UI refresh

- [ ] **Step 6: Test bulk delete**

Select users, click Delete - verify confirmation dialog
Confirm deletion - verify users removed
Verify success messages

- [ ] **Step 7: Test error handling**

Try bulk operations with no users selected
Try invalid tier ID
Verify error messages displayed

- [ ] **Step 8: Test combined functionality**

Use filters + search + sorting + bulk actions together
Verify all features work seamlessly

- [ ] **Step 9: Commit if all tests pass**

```bash
git commit --allow-empty -m "test: verify advanced filtering and bulk actions functionality

- Status and role filters work correctly individually and combined
- Bulk selection with select all/individual checkboxes
- Bulk enable, disable, tier change, and delete operations
- Confirmation dialogs for destructive actions
- Error handling and success messages
- Combined functionality with existing search/sorting/pagination"
```