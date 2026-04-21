"""
Payment system database migrations

Creates all tables required for the complete payment system including:
- Crypto wallet management (master keys, user addresses, transactions)
- Payment methods and transactions
- Subscriptions and billing
- Background job management (locks, queues)
- Configuration tables (price sources, consolidation settings, email config)
"""
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aisbf.database import DatabaseManager

logger = logging.getLogger(__name__)


class PaymentMigrations:
    """Payment system database migrations"""
    
    def __init__(self, db_manager: 'DatabaseManager'):
        """
        Initialize migrations with database manager.
        
        Args:
            db_manager: DatabaseManager instance
        """
        self.db = db_manager
        self.db_type = db_manager.db_type
        
    def run_migrations(self):
        """Run all payment system migrations"""
        logger.info("Starting payment system migrations...")
        
        with self.db._get_connection() as conn:
            cursor = conn.cursor()
            
            # Determine SQL syntax based on database type
            if self.db_type == 'sqlite':
                auto_increment = 'AUTOINCREMENT'
                timestamp_default = 'CURRENT_TIMESTAMP'
                boolean_type = 'BOOLEAN'
                text_type = 'TEXT'
                decimal_type = 'DECIMAL(18,8)'
            else:  # mysql
                auto_increment = 'AUTO_INCREMENT'
                timestamp_default = 'CURRENT_TIMESTAMP'
                boolean_type = 'TINYINT(1)'
                text_type = 'TEXT'
                decimal_type = 'DECIMAL(18,8)'
            
            # Create all payment system tables
            self._create_account_tiers_table(cursor, auto_increment, timestamp_default, boolean_type)
            self._create_crypto_tables(cursor, auto_increment, timestamp_default, boolean_type, text_type, decimal_type)
            self._create_payment_tables(cursor, auto_increment, timestamp_default, boolean_type, text_type, decimal_type)
            self._create_subscription_tables(cursor, auto_increment, timestamp_default, boolean_type, text_type, decimal_type)
            self._create_job_tables(cursor, auto_increment, timestamp_default, boolean_type, text_type, decimal_type)
            self._create_config_tables(cursor, auto_increment, timestamp_default, boolean_type, text_type, decimal_type)
            self._create_notification_tables(cursor, auto_increment, timestamp_default, boolean_type, text_type, decimal_type)
            self._create_wallet_tables(cursor, auto_increment, timestamp_default, boolean_type, text_type, decimal_type)
            self._add_stripe_customer_id_column(cursor)
            self._insert_default_data(cursor)
            
            conn.commit()
            logger.info("✅ Payment system migrations completed successfully")
    
    def _create_account_tiers_table(self, cursor, auto_increment, timestamp_default, boolean_type):
        """Create account_tiers table if it doesn't exist"""
        
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS account_tiers (
                id INTEGER PRIMARY KEY {auto_increment},
                name VARCHAR(255) UNIQUE NOT NULL,
                description TEXT,
                price_monthly DECIMAL(10,2) DEFAULT 0.00,
                price_yearly DECIMAL(10,2) DEFAULT 0.00,
                is_default {boolean_type} DEFAULT 0,
                is_active {boolean_type} DEFAULT 1,
                is_visible {boolean_type} DEFAULT 1,
                max_requests_per_day INTEGER DEFAULT -1,
                max_requests_per_month INTEGER DEFAULT -1,
                max_providers INTEGER DEFAULT -1,
                max_rotations INTEGER DEFAULT -1,
                max_autoselections INTEGER DEFAULT -1,
                max_rotation_models INTEGER DEFAULT -1,
                max_autoselection_models INTEGER DEFAULT -1,
                created_at TIMESTAMP DEFAULT {timestamp_default},
                updated_at TIMESTAMP DEFAULT {timestamp_default}
            )
        ''')
        logger.info("✅ Created/verified account_tiers table")
    
    def _create_crypto_tables(self, cursor, auto_increment, timestamp_default, boolean_type, text_type, decimal_type):
        """Create cryptocurrency-related tables"""
        
        # Crypto master keys (encrypted BIP39 seeds)
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS crypto_master_keys (
                id INTEGER PRIMARY KEY {auto_increment},
                crypto_type VARCHAR(20) NOT NULL UNIQUE,
                encrypted_seed {text_type} NOT NULL,
                encryption_key_id VARCHAR(50) NOT NULL,
                derivation_path VARCHAR(100) NOT NULL,
                created_at TIMESTAMP DEFAULT {timestamp_default},
                updated_at TIMESTAMP DEFAULT {timestamp_default}
            )
        ''')
        
        # User crypto addresses (derived from master keys)
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS user_crypto_addresses (
                id INTEGER PRIMARY KEY {auto_increment},
                user_id INTEGER NOT NULL,
                crypto_type VARCHAR(20) NOT NULL,
                address VARCHAR(255) NOT NULL UNIQUE,
                derivation_path VARCHAR(100) NOT NULL,
                derivation_index INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT {timestamp_default},
                FOREIGN KEY (user_id) REFERENCES users(id),
                UNIQUE(user_id, crypto_type)
            )
        ''')
        
        # User crypto wallets (balance tracking)
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS user_crypto_wallets (
                id INTEGER PRIMARY KEY {auto_increment},
                user_id INTEGER NOT NULL,
                crypto_type VARCHAR(20) NOT NULL,
                balance_crypto {decimal_type} DEFAULT 0,
                balance_fiat {decimal_type} DEFAULT 0,
                last_updated TIMESTAMP DEFAULT {timestamp_default},
                FOREIGN KEY (user_id) REFERENCES users(id),
                UNIQUE(user_id, crypto_type)
            )
        ''')
        
        # Crypto transactions (incoming payments)
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS crypto_transactions (
                id INTEGER PRIMARY KEY {auto_increment},
                user_id INTEGER NOT NULL,
                address_id INTEGER NOT NULL,
                crypto_type VARCHAR(20) NOT NULL,
                tx_hash VARCHAR(255) NOT NULL UNIQUE,
                amount_crypto {decimal_type} NOT NULL,
                amount_fiat {decimal_type},
                confirmations INTEGER DEFAULT 0,
                required_confirmations INTEGER DEFAULT 3,
                status VARCHAR(20) DEFAULT 'pending',
                detected_at TIMESTAMP DEFAULT {timestamp_default},
                confirmed_at TIMESTAMP NULL,
                credited_at TIMESTAMP NULL,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (address_id) REFERENCES user_crypto_addresses(id)
            )
        ''')
        
        # Crypto webhooks (registered webhook IDs)
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS crypto_webhooks (
                id INTEGER PRIMARY KEY {auto_increment},
                crypto_type VARCHAR(20) NOT NULL,
                address VARCHAR(255) NOT NULL,
                webhook_id VARCHAR(255) NOT NULL,
                provider VARCHAR(50) NOT NULL,
                created_at TIMESTAMP DEFAULT {timestamp_default},
                UNIQUE(crypto_type, address, provider)
            )
        ''')
        
        # Create indexes
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_crypto_tx_user ON crypto_transactions(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_crypto_tx_status ON crypto_transactions(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_user_addresses_user ON user_crypto_addresses(user_id)')
        except:
            pass
    
    def _create_payment_tables(self, cursor, auto_increment, timestamp_default, boolean_type, text_type, decimal_type):
        """Create payment-related tables"""
        
        # Payment methods table
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS payment_methods (
                id INTEGER PRIMARY KEY {auto_increment},
                user_id INTEGER NOT NULL,
                type VARCHAR(50) NOT NULL,
                gateway VARCHAR(50),
                identifier VARCHAR(255),
                crypto_type VARCHAR(20),
                last4 VARCHAR(4),
                brand VARCHAR(50),
                paypal_email VARCHAR(255),
                is_default {boolean_type} DEFAULT 0,
                status VARCHAR(20) DEFAULT 'active',
                metadata {text_type},
                created_at TIMESTAMP DEFAULT {timestamp_default},
                updated_at TIMESTAMP DEFAULT {timestamp_default},
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        
        # Payment transactions table
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS payment_transactions (
                id INTEGER PRIMARY KEY {auto_increment},
                user_id INTEGER NOT NULL,
                subscription_id INTEGER,
                payment_method_id INTEGER,
                amount {decimal_type} NOT NULL,
                currency VARCHAR(10) DEFAULT 'USD',
                status VARCHAR(50) NOT NULL,
                transaction_type VARCHAR(50) NOT NULL,
                external_transaction_id VARCHAR(255),
                metadata {text_type},
                created_at TIMESTAMP DEFAULT {timestamp_default},
                completed_at TIMESTAMP NULL,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (subscription_id) REFERENCES subscriptions(id),
                FOREIGN KEY (payment_method_id) REFERENCES payment_methods(id)
            )
        ''')
        
        # Payment retry queue
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS payment_retry_queue (
                id INTEGER PRIMARY KEY {auto_increment},
                subscription_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                payment_method_type VARCHAR(50) NOT NULL,
                amount {decimal_type} NOT NULL,
                currency VARCHAR(10) DEFAULT 'USD',
                attempt_count INTEGER DEFAULT 0,
                max_attempts INTEGER DEFAULT 3,
                next_retry_at TIMESTAMP NULL,
                last_error {text_type},
                status VARCHAR(20) DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT {timestamp_default},
                completed_at TIMESTAMP NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        
        # API requests (for quota tracking)
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS api_requests (
                id INTEGER PRIMARY KEY {auto_increment},
                user_id INTEGER NOT NULL,
                endpoint VARCHAR(255) NOT NULL,
                method VARCHAR(10) NOT NULL,
                status_code INTEGER,
                created_at TIMESTAMP DEFAULT {timestamp_default},
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        
        # Create indexes
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_payment_methods_user ON payment_methods(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_payment_transactions_user ON payment_transactions(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_payment_retry_status ON payment_retry_queue(status, next_retry_at)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_api_requests_user_time ON api_requests(user_id, created_at)')
        except:
            pass
        
        logger.info("✅ Created/verified payment tables")
    
    def _create_subscription_tables(self, cursor, auto_increment, timestamp_default, boolean_type, text_type, decimal_type):
        """Create subscription-related tables"""
        
        # Subscriptions table (enhanced version)
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY {auto_increment},
                user_id INTEGER NOT NULL,
                tier_id INTEGER NOT NULL,
                payment_method_id INTEGER,
                status VARCHAR(20) DEFAULT 'active',
                billing_cycle VARCHAR(20) DEFAULT 'monthly',
                current_period_start TIMESTAMP DEFAULT {timestamp_default},
                current_period_end TIMESTAMP NOT NULL,
                cancel_at_period_end {boolean_type} DEFAULT 0,
                pending_tier_id INTEGER,
                created_at TIMESTAMP DEFAULT {timestamp_default},
                updated_at TIMESTAMP DEFAULT {timestamp_default},
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (tier_id) REFERENCES account_tiers(id),
                FOREIGN KEY (payment_method_id) REFERENCES payment_methods(id),
                FOREIGN KEY (pending_tier_id) REFERENCES account_tiers(id)
            )
        ''')
        
        # Create indexes
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_subscriptions_status ON subscriptions(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_subscriptions_period_end ON subscriptions(current_period_end)')
        except:
            pass
    
    def _create_job_tables(self, cursor, auto_increment, timestamp_default, boolean_type, text_type, decimal_type):
        """Create background job management tables"""
        
        # Job locks (distributed locking)
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS job_locks (
                id INTEGER PRIMARY KEY {auto_increment},
                job_name VARCHAR(100) NOT NULL UNIQUE,
                instance_id VARCHAR(255) NOT NULL,
                acquired_at TIMESTAMP DEFAULT {timestamp_default},
                expires_at TIMESTAMP NOT NULL
            )
        ''')
        
        # Crypto consolidation queue
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS crypto_consolidation_queue (
                id INTEGER PRIMARY KEY {auto_increment},
                crypto_type VARCHAR(20) NOT NULL,
                total_balance {decimal_type} NOT NULL,
                address_count INTEGER NOT NULL,
                status VARCHAR(20) DEFAULT 'pending',
                tx_hash VARCHAR(255),
                error_message {text_type},
                created_at TIMESTAMP DEFAULT {timestamp_default},
                processed_at TIMESTAMP NULL
            )
        ''')
        
        # Email notification queue
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS email_notification_queue (
                id INTEGER PRIMARY KEY {auto_increment},
                user_id INTEGER NOT NULL,
                notification_type VARCHAR(50) NOT NULL,
                recipient_email VARCHAR(255) NOT NULL,
                subject VARCHAR(255) NOT NULL,
                body {text_type} NOT NULL,
                attempt_count INTEGER DEFAULT 0,
                max_attempts INTEGER DEFAULT 3,
                next_retry_at TIMESTAMP NULL,
                status VARCHAR(20) DEFAULT 'pending',
                error_message {text_type},
                created_at TIMESTAMP DEFAULT {timestamp_default},
                sent_at TIMESTAMP NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        
        # Create indexes
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_job_locks_expires ON job_locks(expires_at)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_consolidation_status ON crypto_consolidation_queue(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_email_queue_status ON email_notification_queue(status, next_retry_at)')
        except:
            pass
    
    def _create_config_tables(self, cursor, auto_increment, timestamp_default, boolean_type, text_type, decimal_type):
        """Create configuration tables for payment system"""
        
        # Admin settings table (for payment gateway configs, encryption keys, etc.)
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS admin_settings (
                id INTEGER PRIMARY KEY {auto_increment},
                setting_key VARCHAR(255) UNIQUE NOT NULL,
                setting_value {text_type},
                updated_at TIMESTAMP DEFAULT {timestamp_default}
            )
        ''')
        
        # Crypto price sources
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS crypto_price_sources (
                id INTEGER PRIMARY KEY {auto_increment},
                name VARCHAR(100) NOT NULL UNIQUE,
                api_type VARCHAR(20) NOT NULL,
                endpoint_url VARCHAR(500) NOT NULL,
                api_key VARCHAR(255),
                priority INTEGER DEFAULT 1,
                is_enabled {boolean_type} DEFAULT 1,
                created_at TIMESTAMP DEFAULT {timestamp_default},
                updated_at TIMESTAMP DEFAULT {timestamp_default}
            )
        ''')
        
        # Crypto consolidation settings
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS crypto_consolidation_settings (
                id INTEGER PRIMARY KEY {auto_increment},
                crypto_type VARCHAR(20) NOT NULL UNIQUE,
                threshold_amount {decimal_type} NOT NULL,
                admin_address VARCHAR(255) NOT NULL,
                is_enabled {boolean_type} DEFAULT 1,
                created_at TIMESTAMP DEFAULT {timestamp_default},
                updated_at TIMESTAMP DEFAULT {timestamp_default}
            )
        ''')
        
        # Payment gateway config
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS payment_gateway_config (
                id INTEGER PRIMARY KEY {auto_increment},
                gateway_name VARCHAR(50) NOT NULL UNIQUE,
                config_json {text_type} NOT NULL,
                is_enabled {boolean_type} DEFAULT 1,
                created_at TIMESTAMP DEFAULT {timestamp_default},
                updated_at TIMESTAMP DEFAULT {timestamp_default}
            )
        ''')
        
        # Crypto API config
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS crypto_api_config (
                id INTEGER PRIMARY KEY {auto_increment},
                crypto_type VARCHAR(20) NOT NULL,
                api_provider VARCHAR(50) NOT NULL,
                api_key VARCHAR(255),
                config_json {text_type},
                is_enabled {boolean_type} DEFAULT 1,
                created_at TIMESTAMP DEFAULT {timestamp_default},
                updated_at TIMESTAMP DEFAULT {timestamp_default},
                UNIQUE(crypto_type, api_provider)
            )
        ''')
    
    def _create_notification_tables(self, cursor, auto_increment, timestamp_default, boolean_type, text_type, decimal_type):
        """Create email notification configuration tables"""
        
        # Email notification settings
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS email_notification_settings (
                id INTEGER PRIMARY KEY {auto_increment},
                notification_type VARCHAR(50) NOT NULL UNIQUE,
                is_enabled {boolean_type} DEFAULT 1,
                subject_template VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT {timestamp_default},
                updated_at TIMESTAMP DEFAULT {timestamp_default}
            )
        ''')
        
        # Email templates
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS email_templates (
                id INTEGER PRIMARY KEY {auto_increment},
                notification_type VARCHAR(50) NOT NULL UNIQUE,
                template_html {text_type} NOT NULL,
                template_text {text_type},
                created_at TIMESTAMP DEFAULT {timestamp_default},
                updated_at TIMESTAMP DEFAULT {timestamp_default}
            )
        ''')
        
        # Email config
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS email_config (
                id INTEGER PRIMARY KEY {auto_increment},
                smtp_host VARCHAR(255) NOT NULL,
                smtp_port INTEGER NOT NULL,
                smtp_username VARCHAR(255),
                smtp_password VARCHAR(255),
                from_email VARCHAR(255) NOT NULL,
                from_name VARCHAR(255),
                use_tls {boolean_type} DEFAULT 1,
                created_at TIMESTAMP DEFAULT {timestamp_default},
                updated_at TIMESTAMP DEFAULT {timestamp_default}
            )
        ''')
    
    def _add_stripe_customer_id_column(self, cursor):
        """Add Stripe customer ID column to users table"""
        try:
            if self.db_type == 'sqlite':
                # Check if column exists
                cursor.execute("PRAGMA table_info(users)")
                columns = [row[1] for row in cursor.fetchall()]
                if 'stripe_customer_id' not in columns:
                    cursor.execute("""
                        ALTER TABLE users ADD COLUMN stripe_customer_id VARCHAR(100)
                    """)
                    logger.info("✅ Added stripe_customer_id column to users table")
            else:  # mysql
                cursor.execute("""
                    SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_NAME = 'users' AND COLUMN_NAME = 'stripe_customer_id'
                """)
                if not cursor.fetchone():
                    cursor.execute("""
                        ALTER TABLE users ADD COLUMN stripe_customer_id VARCHAR(100)
                    """)
                    logger.info("✅ Added stripe_customer_id column to users table")
        except Exception as e:
            logger.warning(f"Migration check for stripe_customer_id column: {e}")
    
    def _insert_default_data(self, cursor):
        """Insert default configuration data (only if not already present)"""
        
        # Insert default price sources (INSERT OR IGNORE = only if not exists)
        default_sources = [
            ('Coinbase', 'rest', 'https://api.coinbase.com/v2/prices', None, 1),
            ('Binance', 'rest', 'https://api.binance.com/api/v3/ticker/price', None, 2),
            ('Kraken', 'rest', 'https://api.kraken.com/0/public/Ticker', None, 3)
        ]
        
        for name, api_type, endpoint, api_key, priority in default_sources:
            try:
                if self.db_type == 'sqlite':
                    cursor.execute('''
                        INSERT OR IGNORE INTO crypto_price_sources (name, api_type, endpoint_url, api_key, priority)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (name, api_type, endpoint, api_key, priority))
                else:
                    cursor.execute('''
                        INSERT IGNORE INTO crypto_price_sources (name, api_type, endpoint_url, api_key, priority)
                        VALUES (%s, %s, %s, %s, %s)
                    ''', (name, api_type, endpoint, api_key, priority))
            except:
                pass
        
        # Insert default consolidation settings (INSERT OR IGNORE = only if not exists)
        default_consolidation = [
            ('BTC', '0.1', ''),
            ('ETH', '1.0', ''),
            ('USDT', '1000.0', ''),
            ('USDC', '1000.0', '')
        ]
        
        for crypto_type, threshold, address in default_consolidation:
            try:
                if self.db_type == 'sqlite':
                    cursor.execute('''
                        INSERT OR IGNORE INTO crypto_consolidation_settings (crypto_type, threshold_amount, admin_address, is_enabled)
                        VALUES (?, ?, ?, 0)
                    ''', (crypto_type, threshold, address))
                else:
                    cursor.execute('''
                        INSERT IGNORE INTO crypto_consolidation_settings (crypto_type, threshold_amount, admin_address, is_enabled)
                        VALUES (%s, %s, %s, 0)
                    ''', (crypto_type, threshold, address))
            except:
                pass
        
        # Insert default email notification settings (INSERT OR IGNORE = only if not exists)
        default_notifications = [
            ('payment_failed', 'Payment Failed'),
            ('payment_retry_success', 'Payment Successful'),
            ('subscription_created', 'Subscription Created'),
            ('subscription_renewed', 'Subscription Renewed'),
            ('subscription_upgraded', 'Subscription Upgraded'),
            ('subscription_downgrade_scheduled', 'Subscription Downgrade Scheduled'),
            ('subscription_canceled', 'Subscription Canceled'),
            ('subscription_downgraded', 'Subscription Downgraded'),
            ('crypto_wallet_credited', 'Crypto Payment Received')
        ]
        
        for notif_type, subject in default_notifications:
            try:
                if self.db_type == 'sqlite':
                    cursor.execute('''
                        INSERT OR IGNORE INTO email_notification_settings (notification_type, subject_template, is_enabled)
                        VALUES (?, ?, 1)
                    ''', (notif_type, subject))
                else:
                    cursor.execute('''
                        INSERT IGNORE INTO email_notification_settings (notification_type, subject_template, is_enabled)
                        VALUES (%s, %s, 1)
                    ''', (notif_type, subject))
            except:
                pass
        
        logger.info("✅ Default payment system data checked (existing records preserved)")
        
        # Insert default free tier ONLY if account_tiers table is completely empty
        try:
            cursor.execute('SELECT COUNT(*) FROM account_tiers')
            tier_count = cursor.fetchone()[0]
            
            if tier_count == 0:
                # Table is empty, insert default free tier
                if self.db_type == 'sqlite':
                    cursor.execute('''
                        INSERT INTO account_tiers
                        (name, description, price_monthly, price_yearly, is_default, is_active, is_visible,
                         max_requests_per_day, max_requests_per_month, max_providers, max_rotations,
                         max_autoselections, max_rotation_models, max_autoselection_models)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', ('Free Tier', 'Default free account tier with unlimited access', 0.00, 0.00, 1, 1, 1,
                          -1, -1, -1, -1, -1, -1, -1))
                else:
                    cursor.execute('''
                        INSERT INTO account_tiers
                        (name, description, price_monthly, price_yearly, is_default, is_active, is_visible,
                         max_requests_per_day, max_requests_per_month, max_providers, max_rotations,
                         max_autoselections, max_rotation_models, max_autoselection_models)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ''', ('Free Tier', 'Default free account tier with unlimited access', 0.00, 0.00, 1, 1, 1,
                          -1, -1, -1, -1, -1, -1, -1))
                logger.info("✅ Inserted default free tier (table was empty)")
            else:
                logger.info(f"✅ Account tiers table has {tier_count} record(s), skipping default tier insertion")
        except Exception as e:
            logger.warning(f"Failed to check/insert default free tier: {e}")
     
    def _create_wallet_tables(self, cursor, auto_increment, timestamp_default, boolean_type, text_type, decimal_type):
        """Create unified user wallet and transaction tables"""
        
        # Unified user fiat wallet table
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS user_wallets (
                id INTEGER PRIMARY KEY {auto_increment},
                user_id INTEGER UNIQUE NOT NULL,
                balance DECIMAL(10,2) NOT NULL DEFAULT 0.00,
                currency_code VARCHAR(3) NOT NULL DEFAULT 'USD',
                auto_topup_enabled {boolean_type} NOT NULL DEFAULT 0,
                auto_topup_amount DECIMAL(10,2),
                auto_topup_threshold DECIMAL(10,2),
                auto_topup_payment_method_id INTEGER,
                created_at TIMESTAMP NOT NULL DEFAULT {timestamp_default},
                updated_at TIMESTAMP NOT NULL DEFAULT {timestamp_default},
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (auto_topup_payment_method_id) REFERENCES payment_methods(id)
            )
        ''')
        
        # Wallet transactions history table
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS wallet_transactions (
                id INTEGER PRIMARY KEY {auto_increment},
                user_id INTEGER NOT NULL,
                wallet_id INTEGER NOT NULL,
                amount DECIMAL(10,2) NOT NULL,
                type VARCHAR(32) NOT NULL,
                status VARCHAR(32) NOT NULL,
                payment_method_id INTEGER,
                payment_gateway VARCHAR(32),
                gateway_transaction_id VARCHAR(255),
                description TEXT,
                metadata {text_type},
                created_at TIMESTAMP NOT NULL DEFAULT {timestamp_default},
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (wallet_id) REFERENCES user_wallets(id),
                FOREIGN KEY (payment_method_id) REFERENCES payment_methods(id)
            )
        ''')
        
        # Create indexes
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_user_wallets_user ON user_wallets(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_wallet_transactions_wallet ON wallet_transactions(wallet_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_wallet_transactions_user ON wallet_transactions(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_wallet_transactions_created ON wallet_transactions(created_at)')
        except:
            pass
        
        logger.info("✅ Created/verified wallet system tables")
