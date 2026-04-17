# User Management Filters and Bulk Actions JavaScript - Design Document

## Overview
Add JavaScript functionality for advanced filtering and bulk actions to the user management dashboard.

## Requirements
- Filter change handlers for status and role dropdowns
- Bulk selection handlers (select all, individual checkboxes)
- Bulk action handlers (enable, disable, delete, tier change)
- Helper functions for selection management
- Integration with existing updateUsers() AJAX function

## Implementation Details

### Filter Handlers
```javascript
document.getElementById('status-filter').addEventListener('change', function() {
    updateUsers({ status_filter: this.value || null });
});

document.getElementById('role-filter').addEventListener('change', function() {
    updateUsers({ role_filter: this.value || null });
});
```

### Bulk Selection Handlers
```javascript
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

### Bulk Action Handlers
```javascript
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
        this.value = '';
    }
});
```

### Helper Functions
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
    // Implementation as provided in task
}
```

## Integration
- Call updateBulkActionsVisibility() on page load and after AJAX updates
- Uses existing updateUsers() function for filtering
- Integrates with existing notification system

## Error Handling
- Validation for selected users
- Confirmation dialogs for destructive operations
- Loading states during bulk operations
- Error messages for failed operations

## Testing
- JavaScript loads without console errors
- Filter dropdowns update URL and refresh data
- Bulk selection updates counters correctly
- Bulk actions perform correctly with proper confirmations