# User Management Page Enhancement - Design Document

## Overview
Enhance the admin user management page with pagination, search functionality, and multi-column sorting capabilities.

## Requirements
- Add pagination with customizable page sizes (10, 25, 50, 100 users per page)
- Implement search by username, email, and display name (case-insensitive)
- Add sortable columns for username, last login, signup date, and tier (both directions)
- Maintain URL state for bookmarking and browser navigation
- Provide smooth AJAX-based updates without full page reloads

## Technical Architecture

### Database Layer Changes
- Update `get_users()` function in `aisbf/database.py` to support:
  - LIMIT/OFFSET for pagination
  - WHERE clause for search filtering
  - ORDER BY for multi-column sorting
  - JOIN with account_tiers table for tier information

### API Layer Changes
- Modify `/dashboard/users` route in `main.py` to:
  - Parse query parameters: `page`, `limit`, `search`, `order_by`, `direction`
  - Return paginated results with total count
  - Handle invalid parameters gracefully

### Frontend Layer Changes
- Update `templates/dashboard/users.html`:
  - Add search input field with debounced search
  - Make table headers clickable for sorting
  - Add pagination controls with page navigation
  - Include loading states and error handling
  - Add keyboard navigation support

## Implementation Details

### Database Query Structure
```sql
SELECT u.id, u.username, u.email, u.role, u.created_by, u.created_at,
       u.last_login, u.is_active, t.name as tier_name
FROM users u
LEFT JOIN account_tiers t ON u.tier_id = t.id
WHERE (u.username LIKE ? OR u.email LIKE ? OR u.display_name LIKE ?)
ORDER BY {order_by} {direction}
LIMIT {limit} OFFSET {offset}
```

### API Parameters
- `page`: Integer, 1-based page number (default: 1)
- `limit`: Integer, items per page (default: 25, options: 10, 25, 50, 100)
- `search`: String, search term for username/email/display name
- `order_by`: String, column to sort by (username, last_login, created_at, tier_name)
- `direction`: String, sort direction (asc, desc, default: desc)

### UI Components
- **Search Bar**: Debounced input with clear button
- **Sortable Headers**: Clickable th elements with sort indicators (▲/▼)
- **Pagination**: Previous/Next buttons + page number buttons
- **Results Counter**: "Showing X-Y of Z users"
- **Loading States**: Spinner during AJAX requests
- **Error Handling**: User-friendly error messages

### URL State Management
Query parameters are maintained in URL for bookmarking:
```
/dashboard/users?page=2&limit=50&search=admin&order_by=username&direction=asc
```

### Default Behavior
- Page size: 25 users per page
- Default sort: created_at DESC (newest users first)
- Search scope: username, email, display name
- Case-insensitive search

## Error Handling
- Invalid page numbers → redirect to page 1
- Database errors → show error message, don't crash
- Empty results → show "No users found" message
- Network errors → retry mechanism with user feedback

## Performance Considerations
- Database queries use proper indexing on searchable columns
- Pagination prevents loading all users at once
- Debounced search prevents excessive API calls
- AJAX updates prevent full page reloads

## Testing Requirements
- Unit tests for database query functions
- Integration tests for API endpoints
- UI tests for search, sorting, and pagination
- Edge case testing: empty results, invalid parameters, network failures

## Security Considerations
- Admin-only access maintained
- Input validation for all parameters
- SQL injection prevention through parameterized queries
- XSS protection in search results display

## Future Enhancements (Not Included)
- Bulk operations (delete, tier changes)
- Advanced filtering (status, role)
- Export functionality
- User avatars
- Mobile responsive design
- State persistence in localStorage

## Migration Notes
- Existing user management functionality remains unchanged
- New parameters are optional, maintaining backward compatibility
- Database schema changes: ensure tier_id column exists (migration already in place)

## Rollback Plan
- Feature can be disabled by removing query parameter handling
- Database changes are additive, no destructive migrations
- Template changes can be reverted to previous version</content>
<parameter name="filePath">docs/superpowers/specs/2026-04-17-user-management-enhancement-design.md