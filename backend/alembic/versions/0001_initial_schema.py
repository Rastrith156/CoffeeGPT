"""
alembic/versions/0001_initial_schema.py
=========================================
Task 5 — Initial Alembic migration.

Creates all core tables:
  - market_data      : price snapshots (arabica / robusta futures)
  - news_articles    : ingested coffee news
  - weather_records  : weather observations per region
  - forecast_results : prophet/xgboost forecast outputs
  - alert_events     : persisted spike/volatility alert log

upgrade()   → create tables
downgrade() → drop tables in reverse dependency order
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── market_data ──────────────────────────────────────────────────────────
    op.create_table(
        "market_data",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("commodity", sa.String(32), nullable=False, index=True),  # 'arabica' | 'robusta'
        sa.Column("price", sa.Numeric(12, 4), nullable=False),
        sa.Column("currency", sa.String(16), nullable=False, server_default="USc/lb"),
        sa.Column("change_pct", sa.Numeric(8, 4), nullable=True),
        sa.Column("volume", sa.BigInteger, nullable=True),
        sa.Column("source", sa.String(64), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_market_data_commodity_recorded_at", "market_data", ["commodity", "recorded_at"])

    # ── news_articles ────────────────────────────────────────────────────────
    op.create_table(
        "news_articles",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("content", sa.Text, nullable=True),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("source_url", sa.Text, nullable=False, unique=True),
        sa.Column("source_name", sa.String(128), nullable=True),
        sa.Column("author", sa.String(256), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("embedding_id", sa.Text, nullable=True),  # Qdrant point ID
        sa.Column("tags", sa.JSON, nullable=True),
    )
    op.create_index("ix_news_articles_published_at", "news_articles", ["published_at"])
    op.create_index("ix_news_articles_source_name", "news_articles", ["source_name"])

    # ── weather_records ──────────────────────────────────────────────────────
    op.create_table(
        "weather_records",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("region", sa.String(128), nullable=False, index=True),
        sa.Column("country", sa.String(64), nullable=True),
        sa.Column("temperature_c", sa.Numeric(6, 2), nullable=True),
        sa.Column("humidity_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("rainfall_mm", sa.Numeric(8, 2), nullable=True),
        sa.Column("wind_speed_kmh", sa.Numeric(6, 2), nullable=True),
        sa.Column("condition", sa.String(64), nullable=True),
        sa.Column("drought_risk", sa.String(16), nullable=True),  # low|medium|high|critical
        sa.Column("frost_risk", sa.Boolean, nullable=True, server_default="false"),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("raw_payload", sa.JSON, nullable=True),
    )
    op.create_index("ix_weather_records_region_recorded_at", "weather_records", ["region", "recorded_at"])

    # ── forecast_results ─────────────────────────────────────────────────────
    op.create_table(
        "forecast_results",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("commodity", sa.String(32), nullable=False, index=True),
        sa.Column("model_type", sa.String(32), nullable=False),  # 'prophet' | 'xgboost' | 'ensemble'
        sa.Column("horizon_days", sa.Integer, nullable=False),
        sa.Column("forecast_date", sa.Date, nullable=False),
        sa.Column("predicted_price", sa.Numeric(12, 4), nullable=False),
        sa.Column("lower_bound", sa.Numeric(12, 4), nullable=True),
        sa.Column("upper_bound", sa.Numeric(12, 4), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("metadata_json", sa.JSON, nullable=True),
    )
    op.create_index("ix_forecast_results_commodity_forecast_date", "forecast_results", ["commodity", "forecast_date"])

    # ── alert_events ─────────────────────────────────────────────────────────
    op.create_table(
        "alert_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("alert_type", sa.String(64), nullable=False),   # 'spike' | 'volatility' | 'drought' | 'forecast'
        sa.Column("severity", sa.String(16), nullable=False),      # 'low' | 'medium' | 'high' | 'critical'
        sa.Column("commodity", sa.String(32), nullable=True),
        sa.Column("region", sa.String(128), nullable=True),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("change_pct", sa.Numeric(8, 4), nullable=True),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("acknowledged", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("payload", sa.JSON, nullable=True),
    )
    op.create_index("ix_alert_events_triggered_at", "alert_events", ["triggered_at"])
    op.create_index("ix_alert_events_severity", "alert_events", ["severity"])


def downgrade() -> None:
    op.drop_table("alert_events")
    op.drop_table("forecast_results")
    op.drop_table("weather_records")
    op.drop_table("news_articles")
    op.drop_table("market_data")
