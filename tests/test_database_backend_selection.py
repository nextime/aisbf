"""A configured backend must be the backend that gets used.

A legacy copy of DatabaseManager.__init__ was patched over the real constructor
at import time.  It never set self._mysql_pool, so the first query on a
MySQL-backed manager raised AttributeError; main.py swallows that into
"Failed to initialize database", leaves the registry empty, and the next
config-less get_config_database() call registers the DEFAULT SQLite database.
A MySQL deployment therefore migrated itself to an empty local file in silence.
On aisbf.cloud that happened on 2026-07-22 and was only noticed three months
later, with the user table split across two databases.
"""
import aisbf.database as database_module
from aisbf.database import DatabaseManager, DatabaseRegistry


def test_no_constructor_patch_shadows_the_real_init():
    assert not hasattr(database_module, 'DatabaseManager__init__')


def test_manager_always_has_a_pool_attribute(tmp_path):
    """_get_connection() reads self._mysql_pool; it must always exist."""
    db = DatabaseManager({'type': 'sqlite', 'sqlite_path': str(tmp_path / 'a.db')})
    assert db._mysql_pool is None


def test_mysql_config_is_not_silently_downgraded(tmp_path, monkeypatch):
    """A MySQL config must reach the manager as MySQL, or raise - never become SQLite."""
    captured = {}

    def fake_init_pool(self):
        captured['pooled'] = True
        self._mysql_pool = None

    def fake_initialize_database(self):
        captured['initialized'] = True

    monkeypatch.setattr(DatabaseManager, '_init_mysql_pool', fake_init_pool)
    monkeypatch.setattr(DatabaseManager, '_initialize_database', fake_initialize_database)
    monkeypatch.setattr(database_module, 'MYSQL_AVAILABLE', True)

    db = DatabaseManager({
        'type': 'mysql',
        'mysql_host': '127.0.0.1',
        'mysql_port': 3306,
        'mysql_user': 'aisbf',
        'mysql_password': 'x',
        'mysql_database': 'aisbf',
    })

    assert db.db_type == 'mysql'
    assert captured == {'pooled': True, 'initialized': True}


def test_config_less_cache_manager_keeps_its_own_file(tmp_path, monkeypatch):
    """A config-less cache manager must not fall back onto the permanent database."""
    monkeypatch.setattr(database_module.Path, 'home', staticmethod(lambda: tmp_path))

    config_db = DatabaseManager(None, database_type=DatabaseRegistry.TYPE_CONFIG)
    cache_db = DatabaseManager(None, database_type=DatabaseRegistry.TYPE_CACHE)

    assert config_db.db_config['sqlite_path'].endswith('aisbf.db')
    assert cache_db.db_config['sqlite_path'].endswith('cache.db')
    assert cache_db.db_config['mysql_database'] == 'aisbf_cache'
