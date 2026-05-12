import pytest

from aisbf.database import DatabaseManager


@pytest.fixture
def db_manager(tmp_path):
    db_path = tmp_path / "users.db"
    db = DatabaseManager({
        'type': 'sqlite',
        'sqlite_path': str(db_path),
    })

    pro_tier_id = db.create_tier(
        name='Pro Tier',
        description='Paid plan',
        price_monthly=10.0,
        price_yearly=100.0,
    )

    users = {
        'alice': db.create_user(
            'alice',
            'hash',
            role='user',
            email='alice@example.com',
            display_name='Alice Exporter',
        ),
        'bob': db.create_user(
            'bob',
            'hash',
            role='user',
            email='bob@example.com',
            display_name='Bob Browser',
        ),
        'carol': db.create_user(
            'carol',
            'hash',
            role='admin',
            email='carol@example.com',
            display_name='Carol Admin',
        ),
        'dave': db.create_user(
            'dave',
            'hash',
            role='user',
            email='dave@example.com',
            display_name='Dave Disabled',
        ),
    }

    with db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE users SET tier_id = ? WHERE id = ?',
            (pro_tier_id, users['alice']),
        )
        cursor.execute(
            'UPDATE users SET is_active = 0 WHERE id = ?',
            (users['dave'],),
        )
        conn.commit()

    db.upsert_market_listing(
        users['alice'],
        'alice',
        {
            'source_scope': 'user',
            'source_type': 'provider',
            'source_id': 'alice-provider',
            'listing_key': 'provider:alice-provider',
            'title': 'Alice Provider',
            'description': 'Alice export listing',
            'provider_id': 'alice-provider',
            'model_id': None,
            'endpoint': 'https://example.test/alice',
            'currency_code': 'USD',
            'price_per_million_tokens': 2.5,
            'price_per_1000_requests': 0.0,
            'provider_price_per_million_tokens': 2.5,
            'provider_price_per_1000_requests': 0.0,
            'metadata': {'provider_type': 'openai'},
            'config_snapshot': {'provider': {'type': 'openai'}},
            'is_active': True,
        },
    )
    db.upsert_market_listing(
        users['carol'],
        'carol',
        {
            'source_scope': 'user',
            'source_type': 'provider',
            'source_id': 'carol-provider',
            'listing_key': 'provider:carol-provider',
            'title': 'Carol Provider',
            'description': 'Carol export listing',
            'provider_id': 'carol-provider',
            'model_id': None,
            'endpoint': 'https://example.test/carol',
            'currency_code': 'USD',
            'price_per_million_tokens': 4.0,
            'price_per_1000_requests': 0.0,
            'provider_price_per_million_tokens': 4.0,
            'provider_price_per_1000_requests': 0.0,
            'metadata': {'provider_type': 'openai'},
            'config_snapshot': {'provider': {'type': 'openai'}},
            'is_active': True,
        },
    )
    db.upsert_market_listing(
        users['dave'],
        'dave',
        {
            'source_scope': 'user',
            'source_type': 'provider',
            'source_id': 'dave-provider',
            'listing_key': 'provider:dave-provider',
            'title': 'Dave Provider',
            'description': 'Dave inactive export listing',
            'provider_id': 'dave-provider',
            'model_id': None,
            'endpoint': 'https://example.test/dave',
            'currency_code': 'USD',
            'price_per_million_tokens': 1.0,
            'price_per_1000_requests': 0.0,
            'provider_price_per_million_tokens': 1.0,
            'provider_price_per_1000_requests': 0.0,
            'metadata': {'provider_type': 'openai'},
            'config_snapshot': {'provider': {'type': 'openai'}},
            'is_active': False,
        },
    )

    return {
        'db': db,
        'pro_tier_id': pro_tier_id,
    }


def _usernames(result):
    return [user['username'] for user in result['users']]


def test_get_users_paginated_filters_by_tier_id(db_manager):
    result = db_manager['db'].get_users_paginated(
        tier_filter=db_manager['pro_tier_id'],
        order_by='username',
        direction='asc',
    )

    assert result['total'] == 1
    assert _usernames(result) == ['alice']


def test_get_users_paginated_nonexistent_tier_id_returns_no_matches(db_manager):
    result = db_manager['db'].get_users_paginated(
        tier_filter=999999,
        order_by='username',
        direction='asc',
    )

    assert result['total'] == 0
    assert _usernames(result) == []


def test_get_users_paginated_filters_users_with_market_exports(db_manager):
    result = db_manager['db'].get_users_paginated(
        market_export_filter='exporting',
        order_by='username',
        direction='asc',
    )

    assert result['total'] == 2
    assert _usernames(result) == ['alice', 'carol']


def test_get_users_paginated_filters_users_without_market_exports(db_manager):
    result = db_manager['db'].get_users_paginated(
        market_export_filter='not_exporting',
        order_by='username',
        direction='asc',
    )

    assert result['total'] == 2
    assert _usernames(result) == ['bob', 'dave']


def test_get_users_paginated_ignores_inactive_only_market_exports(db_manager):
    result = db_manager['db'].get_users_paginated(
        market_export_filter='exporting',
        search='dave',
        order_by='username',
        direction='asc',
    )

    assert result['total'] == 0
    assert _usernames(result) == []


def test_get_users_paginated_unsupported_market_export_filter_falls_back_to_unfiltered(db_manager):
    result = db_manager['db'].get_users_paginated(
        market_export_filter='maybe',
        order_by='username',
        direction='asc',
    )

    assert result['total'] == 4
    assert _usernames(result) == ['alice', 'bob', 'carol', 'dave']


def test_get_users_paginated_combines_market_export_and_existing_filters(db_manager):
    result = db_manager['db'].get_users_paginated(
        search='alice',
        status_filter='active',
        role_filter='user',
        market_export_filter='exporting',
        order_by='username',
        direction='asc',
    )

    assert result['total'] == 1
    assert _usernames(result) == ['alice']


def test_get_users_paginated_combines_tier_and_existing_filters(db_manager):
    result = db_manager['db'].get_users_paginated(
        search='alice',
        status_filter='active',
        role_filter='user',
        tier_filter=db_manager['pro_tier_id'],
        order_by='username',
        direction='asc',
    )

    assert result['total'] == 1
    assert _usernames(result) == ['alice']
