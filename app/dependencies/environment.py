"""
Database session dependencies.

get_db         -> tenant-specific database (DATABASE_URL)
get_control_db -> shared control-plane database (CONTROL_DATABASE_URL -> oms_db)

On the main pod both point at the same database.
On tenant pods get_control_db points back at oms_db so the environment
switcher can always see all organizations and environments.
"""
from app.database.postgres import get_db, get_control_db  # noqa: F401
