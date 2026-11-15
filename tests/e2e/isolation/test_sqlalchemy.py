"""SQLAlchemy 2 on the postgresql+psycopg dialect: connect, Core CRUD, ORM CRUD.

PostgreSQL 16's answers, measured on iris-pgwire-pgref on 2026-11-14: ``engine.connect()``
initialises the dialect with ``select pg_catalog.version()``, ``select current_schema()``
(``public``), ``show transaction isolation level``, ``show standard_conforming_strings`` and
psycopg's TypeInfo lookup for ``hstore`` (no row, so native hstore is off).
``MetaData.create_all()`` asks ``has_table()`` through pg_class and pg_namespace. The ORM inserts
several new rows in one ``INSERT ... SELECT ... FROM (VALUES ...) ... RETURNING`` statement
(SQLAlchemy's "insertmanyvalues") and one new row with ``INSERT ... RETURNING``.

Every check reads the rows back, so "no error" is never the whole answer. Savepoints
(``begin_nested``) are in test_savepoints.py.
"""

from __future__ import annotations

import uuid

from .harness import BOTH_SERVERS, sqlalchemy_engine, sqlstate_of


def _fresh_name(stem: str) -> str:
    """A table name no pooled connection has seen. A DBAPI connection that had an error on a
    table later recreated reports "<LIST ERROR>" (XX000) in place of IRIS's real error."""
    return f"{stem}_{uuid.uuid4().hex[:8]}"


@BOTH_SERVERS
def test_connect(target, expect, server):
    from sqlalchemy import text

    engine = sqlalchemy_engine(target)
    observed = {"select_1": None, "default_schema": None, "native_hstore": None, "error": None}
    try:
        with engine.connect() as conn:
            observed["select_1"] = conn.execute(text("select 1")).scalar()
        observed["default_schema"] = engine.dialect.default_schema_name
        observed["native_hstore"] = engine.dialect._has_native_hstore
    except Exception as e:  # noqa: BLE001 - the error is the observation
        observed["error"] = sqlstate_of(e)
    finally:
        engine.dispose()
    expect.check(
        "connect",
        observed,
        {"select_1": 1, "default_schema": "public", "native_hstore": False, "error": None},
    )
    expect.done()


@BOTH_SERVERS
def test_core_crud(target, expect, server):
    """Core: create_all (has_table), a multi-row insert, an update, a delete, then a select."""
    from sqlalchemy import (
        Column,
        Integer,
        MetaData,
        String,
        Table,
        delete,
        insert,
        inspect,
        select,
        update,
    )

    name = _fresh_name("sqla_core")
    metadata = MetaData()
    table = Table(
        name, metadata, Column("id", Integer, primary_key=True), Column("name", String(50))
    )
    engine = sqlalchemy_engine(target)
    observed = {"existed_after_create": None, "rows": None, "error": None}
    try:
        metadata.create_all(engine)
        observed["existed_after_create"] = inspect(engine).has_table(name)
        with engine.begin() as conn:
            conn.execute(
                insert(table),
                [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}, {"id": 3, "name": "c"}],
            )
            conn.execute(update(table).where(table.c.id == 2).values(name="B"))
            conn.execute(delete(table).where(table.c.id == 3))
        with engine.connect() as conn:
            observed["rows"] = [
                list(r) for r in conn.execute(select(table.c.id, table.c.name).order_by(table.c.id))
            ]
    except Exception as e:  # noqa: BLE001 - the error is the observation
        observed["error"] = sqlstate_of(e)
    finally:
        try:
            metadata.drop_all(engine)
        finally:
            engine.dispose()
    expect.check(
        "core_crud",
        observed,
        {"existed_after_create": True, "rows": [[1, "a"], [2, "B"]], "error": None},
    )
    expect.done()


@BOTH_SERVERS
def test_orm_crud(target, expect, server):
    """ORM with database-generated keys: two new objects in one flush, one more alone, an update,
    a delete, then a fresh Session reads the table back. The keys the flush returned must be
    the keys the rows have."""
    from sqlalchemy import Column, Integer, String, select
    from sqlalchemy.orm import DeclarativeBase, Session

    class Base(DeclarativeBase):
        pass

    class Item(Base):
        __tablename__ = _fresh_name("sqla_orm")
        id = Column(Integer, primary_key=True)
        name = Column(String(50), nullable=False)

    engine = sqlalchemy_engine(target)
    observed = {"distinct_keys": None, "rows": None, "error": None}
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            x, y = Item(name="x"), Item(name="y")
            session.add_all([x, y])
            session.commit()
            z = Item(name="z")
            session.add(z)
            session.commit()
            keys = {"x": x.id, "y": y.id, "z": z.id}
            session.get(Item, keys["x"]).name = "X"
            session.delete(session.get(Item, keys["y"]))
            session.commit()
        observed["distinct_keys"] = len(set(keys.values())) == 3 and None not in keys.values()
        with Session(engine) as session:
            by_key = {v: k for k, v in keys.items()}
            observed["rows"] = [
                [by_key.get(i.id), i.name] for i in session.scalars(select(Item).order_by(Item.id))
            ]
    except Exception as e:  # noqa: BLE001 - the error is the observation
        observed["error"] = sqlstate_of(e)
    finally:
        try:
            Base.metadata.drop_all(engine)
        finally:
            engine.dispose()
    expect.check(
        "orm_crud",
        observed,
        # Each row read back is identified by the key its own flush returned for it.
        {"distinct_keys": True, "rows": [["x", "X"], ["z", "z"]], "error": None},
    )
    expect.done()
