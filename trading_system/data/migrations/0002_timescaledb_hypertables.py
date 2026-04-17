"""
Enable TimescaleDB extension and convert time-series tables to hypertables.

Hypertables automatically partition data by time for faster queries.
This migration is safe to run on plain PostgreSQL -- it will simply
skip if TimescaleDB is not installed.
"""

from django.db import migrations


ENABLE_EXTENSION = """
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
EXCEPTION
    WHEN OTHERS THEN
        RAISE NOTICE 'TimescaleDB extension not available — skipping.';
END
$$;
"""

CREATE_HYPERTABLE_MARKET = """
DO $$
BEGIN
    PERFORM create_hypertable(
        'data_marketdata', 'time',
        if_not_exists => TRUE,
        migrate_data  => TRUE
    );
EXCEPTION
    WHEN OTHERS THEN
        RAISE NOTICE 'Could not create hypertable for data_marketdata — skipping.';
END
$$;
"""

CREATE_HYPERTABLE_EQUITY = """
DO $$
BEGIN
    PERFORM create_hypertable(
        'data_equitycurve', 'timestamp',
        if_not_exists => TRUE,
        migrate_data  => TRUE
    );
EXCEPTION
    WHEN OTHERS THEN
        RAISE NOTICE 'Could not create hypertable for data_equitycurve — skipping.';
END
$$;
"""


def is_postgresql(schema_editor):
    return schema_editor.connection.vendor == "postgresql"


def run_if_pg(sql):
    """Only execute SQL on PostgreSQL backends (skip SQLite, etc.)."""
    def forwards(apps, schema_editor):
        if is_postgresql(schema_editor):
            schema_editor.execute(sql)

    def backwards(apps, schema_editor):
        pass

    return migrations.RunPython(forwards, backwards)


class Migration(migrations.Migration):

    dependencies = [
        ("data", "0001_initial"),
    ]

    operations = [
        run_if_pg(ENABLE_EXTENSION),
        run_if_pg(CREATE_HYPERTABLE_MARKET),
        run_if_pg(CREATE_HYPERTABLE_EQUITY),
    ]
