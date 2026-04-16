import pytest
from aisbf.database import DatabaseManager
from aisbf.payments.migrations import PaymentMigrations
from aisbf.payments.subscription.quota import QuotaEnforcer


@pytest.fixture
def db_manager(tmp_path):
    """Create test database"""
    db_path = tmp_path / "test.db"
    db_config = {
        'type': 'sqlite',
        'sqlite_path': str(db_path)
    }
    db = DatabaseManager(db_config)
    migrations = PaymentMigrations(db)
    migrations.run_migrations()
    
    # Create test user
    user_id = db.create_user(email='test@example.com', username='testuser', password_hash='hash')
    
    return db


def test_quota_enforcement_creation_order(db_manager):
    """Test that oldest configs are used when quota exceeded"""
    enforcer = QuotaEnforcer(db_manager)
    
    # Create 3 rotations
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO user_rotations (user_id, rotation_id, config, created_at) VALUES (1, 'rotation1', '{}', datetime('now', '-3 days'))")
        cursor.execute("INSERT INTO user_rotations (user_id, rotation_id, config, created_at) VALUES (1, 'rotation2', '{}', datetime('now', '-2 days'))")
        cursor.execute("INSERT INTO user_rotations (user_id, rotation_id, config, created_at) VALUES (1, 'rotation3', '{}', datetime('now', '-1 day'))")
        conn.commit()
    
    # Enforce quota with max_rotations=2
    result = enforcer.enforce_quota(1, {'max_rotations': 2, 'max_autoselections': -1})
    
    assert result['success'] == True
    assert result['rotations']['active'] == 2
    assert result['rotations']['inactive'] == 1
    
    # Verify oldest 2 are active
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT rotation_id FROM user_rotations WHERE user_id = 1 AND is_active = 1 ORDER BY created_at")
        active = [row[0] for row in cursor.fetchall()]
    
    assert active == ['rotation1', 'rotation2']


def test_quota_enforcement_never_deletes(db_manager):
    """Test that configs are never deleted, only marked inactive"""
    enforcer = QuotaEnforcer(db_manager)
    
    # Create 3 rotations
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO user_rotations (user_id, rotation_id, config) VALUES (1, 'rotation1', '{}')")
        cursor.execute("INSERT INTO user_rotations (user_id, rotation_id, config) VALUES (1, 'rotation2', '{}')")
        cursor.execute("INSERT INTO user_rotations (user_id, rotation_id, config) VALUES (1, 'rotation3', '{}')")
        conn.commit()
    
    # Enforce quota with max_rotations=1
    enforcer.enforce_quota(1, {'max_rotations': 1, 'max_autoselections': -1})
    
    # Verify all configs still exist
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM user_rotations WHERE user_id = 1")
        total = cursor.fetchone()[0]
    
    assert total == 3  # All configs still exist
    
    # Verify only 1 is active
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM user_rotations WHERE user_id = 1 AND is_active = 1")
        active = cursor.fetchone()[0]
    
    assert active == 1


def test_quota_enforcement_on_downgrade(db_manager):
    """Test quota enforcement when downgrading tiers"""
    enforcer = QuotaEnforcer(db_manager)
    
    # Create 5 rotations (simulating premium tier with max 10)
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        for i in range(5):
            cursor.execute(f"INSERT INTO user_rotations (user_id, rotation_id, config) VALUES (1, 'rotation{i+1}', '{{}}')")
        conn.commit()
    
    # Initially all active (premium tier)
    enforcer.enforce_quota(1, {'max_rotations': 10, 'max_autoselections': -1})
    
    # Downgrade to basic tier (max 2)
    result = enforcer.enforce_quota(1, {'max_rotations': 2, 'max_autoselections': -1})
    
    assert result['rotations']['active'] == 2
    assert result['rotations']['inactive'] == 3
    assert result['rotations']['total'] == 5


def test_quota_enforcement_on_upgrade(db_manager):
    """Test quota expansion when upgrading tiers"""
    enforcer = QuotaEnforcer(db_manager)
    
    # Create 5 rotations
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        for i in range(5):
            cursor.execute(f"INSERT INTO user_rotations (user_id, rotation_id, config) VALUES (1, 'rotation{i+1}', '{{}}')")
        conn.commit()
    
    # Start with basic tier (max 2) - 3 inactive
    enforcer.enforce_quota(1, {'max_rotations': 2, 'max_autoselections': -1})
    
    # Verify 2 active, 3 inactive
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM user_rotations WHERE user_id = 1 AND is_active = 1")
        active_before = cursor.fetchone()[0]
    
    assert active_before == 2
    
    # Upgrade to premium tier (max 10)
    result = enforcer.reactivate_configs(1, {'max_rotations': 10, 'max_autoselections': -1})
    
    # All 5 should now be active
    assert result['rotations']['active'] == 5
    assert result['rotations']['inactive'] == 0


def test_get_active_configs(db_manager):
    """Test getting active configs within quota"""
    enforcer = QuotaEnforcer(db_manager)
    
    # Create rotations and autoselects
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO user_rotations (user_id, rotation_id, config) VALUES (1, 'rotation1', '{}')")
        cursor.execute("INSERT INTO user_rotations (user_id, rotation_id, config) VALUES (1, 'rotation2', '{}')")
        cursor.execute("INSERT INTO user_autoselects (user_id, autoselect_id, config) VALUES (1, 'autoselect1', '{}')")
        conn.commit()
    
    # Enforce quota
    enforcer.enforce_quota(1, {'max_rotations': 2, 'max_autoselections': 1})
    
    # Get active configs
    active = enforcer.get_active_configs(1)
    
    assert len(active['rotations']) == 2
    assert len(active['autoselects']) == 1


def test_unlimited_quota(db_manager):
    """Test that -1 means unlimited quota"""
    enforcer = QuotaEnforcer(db_manager)
    
    # Create 10 rotations
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        for i in range(10):
            cursor.execute(f"INSERT INTO user_rotations (user_id, rotation_id, config) VALUES (1, 'rotation{i+1}', '{{}}')")
        conn.commit()
    
    # Enforce with unlimited quota
    result = enforcer.enforce_quota(1, {'max_rotations': -1, 'max_autoselections': -1})
    
    # All should remain active
    with db_manager._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM user_rotations WHERE user_id = 1 AND is_active = 1")
        active = cursor.fetchone()[0]
    
    assert active == 10
