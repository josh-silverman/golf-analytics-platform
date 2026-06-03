"""DeclarativeBase + shared metadata.

A single ``Base`` so every ORM model registers on the same ``MetaData``,
which is what ``target_metadata`` in Alembic's ``env.py`` points at.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Naming convention so Alembic autogenerate produces stable constraint names
# and downgrades cleanly. Without this, Postgres assigns auto-generated names
# that change across runs and break diff-based migrations.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
