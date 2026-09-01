from app.config import Settings
from app.db.pool import resolve_pool_sizes


def test_resolve_pool_sizes_enforces_minimums():
    settings = Settings(
        zimbra_host="mail.example.com",
        zimbra_admin_user="admin@example.com",
        zimbra_admin_password="secret",
        db_pool_min_size=0,
        db_pool_max_size=0,
    )
    min_size, max_size = resolve_pool_sizes(settings)
    assert min_size == 1
    assert max_size == 1


def test_resolve_pool_sizes_keeps_max_at_least_min():
    settings = Settings(
        zimbra_host="mail.example.com",
        zimbra_admin_user="admin@example.com",
        zimbra_admin_password="secret",
        db_pool_min_size=2,
        db_pool_max_size=5,
    )
    min_size, max_size = resolve_pool_sizes(settings)
    assert min_size == 2
    assert max_size == 5
