"""
Quota enforcement service

Enforces tier-based quotas on user configurations (rotations, autoselects).
Uses creation order - oldest configs are kept active when quota is exceeded.
Never deletes configs, only marks them inactive.
"""
import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


class QuotaEnforcer:
    """Enforce tier-based quotas on user configurations"""
    
    def __init__(self, db_manager):
        self.db = db_manager
        self._ensure_is_active_columns()
    
    def _ensure_is_active_columns(self):
        """Ensure is_active columns exist in config tables"""
        try:
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                
                # Check and add is_active to user_rotations
                if self.db.db_type == 'sqlite':
                    cursor.execute("PRAGMA table_info(user_rotations)")
                    columns = [row[1] for row in cursor.fetchall()]
                    if 'is_active' not in columns:
                        cursor.execute("ALTER TABLE user_rotations ADD COLUMN is_active BOOLEAN DEFAULT 1")
                        logger.info("Added is_active column to user_rotations")
                    
                    # Check and add is_active to user_autoselects
                    cursor.execute("PRAGMA table_info(user_autoselects)")
                    columns = [row[1] for row in cursor.fetchall()]
                    if 'is_active' not in columns:
                        cursor.execute("ALTER TABLE user_autoselects ADD COLUMN is_active BOOLEAN DEFAULT 1")
                        logger.info("Added is_active column to user_autoselects")
                else:  # mysql
                    # Check user_rotations
                    cursor.execute("""
                        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
                        WHERE TABLE_NAME = 'user_rotations' AND COLUMN_NAME = 'is_active'
                    """)
                    if not cursor.fetchone():
                        cursor.execute("ALTER TABLE user_rotations ADD COLUMN is_active TINYINT(1) DEFAULT 1")
                        logger.info("Added is_active column to user_rotations")
                    
                    # Check user_autoselects
                    cursor.execute("""
                        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
                        WHERE TABLE_NAME = 'user_autoselects' AND COLUMN_NAME = 'is_active'
                    """)
                    if not cursor.fetchone():
                        cursor.execute("ALTER TABLE user_autoselects ADD COLUMN is_active TINYINT(1) DEFAULT 1")
                        logger.info("Added is_active column to user_autoselects")
                
                conn.commit()
        except Exception as e:
            logger.warning(f"Error ensuring is_active columns: {e}")
    
    def enforce_quota(self, user_id: int, tier_limits: Dict) -> Dict:
        """
        Enforce quota limits for a user based on their tier.
        
        Args:
            user_id: User ID
            tier_limits: Dict with 'max_rotations' and 'max_autoselections'
        
        Returns:
            Dict with enforcement results
        """
        max_rotations = tier_limits.get('max_rotations', -1)
        max_autoselections = tier_limits.get('max_autoselections', -1)
        
        rotations_enforced = self._enforce_rotation_quota(user_id, max_rotations)
        autoselects_enforced = self._enforce_autoselect_quota(user_id, max_autoselections)
        
        return {
            'success': True,
            'rotations': rotations_enforced,
            'autoselects': autoselects_enforced
        }
    
    def _enforce_rotation_quota(self, user_id: int, max_rotations: int) -> Dict:
        """Enforce rotation quota for user"""
        if max_rotations < 0:
            # Unlimited
            return {'active': -1, 'inactive': 0, 'total': 0}
        
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
            
            # Get all rotations ordered by creation date
            cursor.execute(f"""
                SELECT id FROM user_rotations
                WHERE user_id = {placeholder}
                ORDER BY created_at ASC
            """, (user_id,))
            all_rotations = [row[0] for row in cursor.fetchall()]
        
        total = len(all_rotations)
        
        if total <= max_rotations:
            # Within quota, activate all
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
                cursor.execute(f"""
                    UPDATE user_rotations
                    SET is_active = 1
                    WHERE user_id = {placeholder}
                """, (user_id,))
                conn.commit()
            return {'active': total, 'inactive': 0, 'total': total}
        
        # Exceeds quota - keep oldest N active
        active_ids = all_rotations[:max_rotations]
        inactive_ids = all_rotations[max_rotations:]
        
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
            
            # Activate oldest N
            if active_ids:
                placeholders = ','.join([placeholder] * len(active_ids))
                cursor.execute(f"""
                    UPDATE user_rotations
                    SET is_active = 1
                    WHERE id IN ({placeholders})
                """, active_ids)
            
            # Deactivate rest
            if inactive_ids:
                placeholders = ','.join([placeholder] * len(inactive_ids))
                cursor.execute(f"""
                    UPDATE user_rotations
                    SET is_active = 0
                    WHERE id IN ({placeholders})
                """, inactive_ids)
            
            conn.commit()
        
        logger.info(f"Enforced rotation quota for user {user_id}: {len(active_ids)} active, {len(inactive_ids)} inactive")
        
        return {
            'active': len(active_ids),
            'inactive': len(inactive_ids),
            'total': total
        }
    
    def _enforce_autoselect_quota(self, user_id: int, max_autoselections: int) -> Dict:
        """Enforce autoselect quota for user"""
        if max_autoselections < 0:
            # Unlimited
            return {'active': -1, 'inactive': 0, 'total': 0}
        
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
            
            # Get all autoselects ordered by creation date
            cursor.execute(f"""
                SELECT id FROM user_autoselects
                WHERE user_id = {placeholder}
                ORDER BY created_at ASC
            """, (user_id,))
            all_autoselects = [row[0] for row in cursor.fetchall()]
        
        total = len(all_autoselects)
        
        if total <= max_autoselections:
            # Within quota, activate all
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
                cursor.execute(f"""
                    UPDATE user_autoselects
                    SET is_active = 1
                    WHERE user_id = {placeholder}
                """, (user_id,))
                conn.commit()
            return {'active': total, 'inactive': 0, 'total': total}
        
        # Exceeds quota - keep oldest N active
        active_ids = all_autoselects[:max_autoselections]
        inactive_ids = all_autoselects[max_autoselections:]
        
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
            
            # Activate oldest N
            if active_ids:
                placeholders = ','.join([placeholder] * len(active_ids))
                cursor.execute(f"""
                    UPDATE user_autoselects
                    SET is_active = 1
                    WHERE id IN ({placeholders})
                """, active_ids)
            
            # Deactivate rest
            if inactive_ids:
                placeholders = ','.join([placeholder] * len(inactive_ids))
                cursor.execute(f"""
                    UPDATE user_autoselects
                    SET is_active = 0
                    WHERE id IN ({placeholders})
                """, inactive_ids)
            
            conn.commit()
        
        logger.info(f"Enforced autoselect quota for user {user_id}: {len(active_ids)} active, {len(inactive_ids)} inactive")
        
        return {
            'active': len(active_ids),
            'inactive': len(inactive_ids),
            'total': total
        }
    
    def get_active_configs(self, user_id: int) -> Dict:
        """Get user's active configurations within quota"""
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            placeholder = '?' if self.db.db_type == 'sqlite' else '%s'
            
            # Get active rotations
            cursor.execute(f"""
                SELECT id, rotation_id FROM user_rotations
                WHERE user_id = {placeholder} AND is_active = 1
                ORDER BY created_at ASC
            """, (user_id,))
            rotations = [{'id': row[0], 'rotation_id': row[1]} for row in cursor.fetchall()]
            
            # Get active autoselects
            cursor.execute(f"""
                SELECT id, autoselect_id FROM user_autoselects
                WHERE user_id = {placeholder} AND is_active = 1
                ORDER BY created_at ASC
            """, (user_id,))
            autoselects = [{'id': row[0], 'autoselect_id': row[1]} for row in cursor.fetchall()]
        
        return {
            'rotations': rotations,
            'autoselects': autoselects
        }
    
    def reactivate_configs(self, user_id: int, new_limits: Dict) -> Dict:
        """
        Reactivate configs when user upgrades to higher tier.
        
        Args:
            user_id: User ID
            new_limits: Dict with 'max_rotations' and 'max_autoselections'
        
        Returns:
            Dict with reactivation results
        """
        # Simply re-enforce quota with new limits
        # This will reactivate configs up to the new limit
        return self.enforce_quota(user_id, new_limits)
