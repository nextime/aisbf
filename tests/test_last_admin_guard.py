"""The database must never let the last admin disappear.

aisbf.cloud lost its only admin this way: /dashboard/delete-account checks the
password but not the role, nothing in the dashboard can mint a new admin, and
the installation sat with 782 users and zero admins until a row was written by
hand.  These tests pin the guard to the database layer so every caller -
self-service deletion, admin user management, role edits - is covered.
"""
import pytest

from aisbf.database import DatabaseManager, LastAdminError


@pytest.fixture
def db(tmp_path):
    return DatabaseManager({
        'type': 'sqlite',
        'sqlite_path': str(tmp_path / "users.db"),
    })


@pytest.fixture
def sole_admin(db):
    return db.create_user('admin', 'hash', role='admin', email='admin@example.com')


def test_last_admin_cannot_be_deleted(db, sole_admin):
    with pytest.raises(LastAdminError):
        db.delete_user(sole_admin)
    assert db.get_user_by_id(sole_admin) is not None


def test_last_admin_cannot_be_demoted(db, sole_admin):
    with pytest.raises(LastAdminError):
        db.update_user(sole_admin, 'admin', role='user')
    assert db.get_user_by_id(sole_admin)['role'] == 'admin'


def test_last_admin_cannot_be_deactivated(db, sole_admin):
    with pytest.raises(LastAdminError):
        db.update_user(sole_admin, 'admin', is_active=False)
    assert db.get_user_by_id(sole_admin)['is_active']


def test_second_admin_makes_the_first_deletable(db, sole_admin):
    other = db.create_user('admin2', 'hash', role='admin', email='admin2@example.com')
    db.delete_user(sole_admin)
    assert db.get_user_by_id(sole_admin) is None
    assert db.get_user_by_id(other)['role'] == 'admin'


def test_an_inactive_second_admin_does_not_count(db, sole_admin):
    disabled = db.create_user('admin2', 'hash', role='admin', email='admin2@example.com')
    db.update_user(disabled, 'admin2', is_active=False)
    with pytest.raises(LastAdminError):
        db.delete_user(sole_admin)


def test_plain_users_are_unaffected(db, sole_admin):
    user = db.create_user('bob', 'hash', role='user', email='bob@example.com')
    db.delete_user(user)
    assert db.get_user_by_id(user) is None


def test_renaming_the_last_admin_is_allowed(db, sole_admin):
    """The guard must only fire on demotion/deactivation, not on any edit."""
    db.update_user(sole_admin, 'admin', display_name='Stefy')
    assert db.get_user_by_id(sole_admin)['display_name'] == 'Stefy'


def test_promoting_the_last_admin_again_is_allowed(db, sole_admin):
    db.update_user(sole_admin, 'admin', role='admin')
    assert db.get_user_by_id(sole_admin)['role'] == 'admin'


def test_stale_signup_cleanup_still_works(db, sole_admin):
    """The sweep deletes plain users; the admin guard must not block it."""
    db.create_user('ghost', 'hash', role='user', email='ghost@example.com')
    with db._get_connection() as conn:
        conn.cursor().execute(
            "UPDATE users SET created_at = datetime('now', '-30 days') "
            "WHERE username = 'ghost'"
        )
        conn.commit()
    assert db.delete_stale_unverified_signup_users(inactivity_days=14) == 1
    assert db.get_user_by_username('ghost') is None
    assert db.get_user_by_id(sole_admin) is not None
