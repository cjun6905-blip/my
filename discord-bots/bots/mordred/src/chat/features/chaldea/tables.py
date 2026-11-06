"""SQLAlchemy Core tables isolated from the project's shared model module."""

from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    Index,
    Integer,
    JSON,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    func,
)


SCHEMA = "chaldea"
metadata = MetaData(schema=SCHEMA)

profiles = Table(
    "player_profiles",
    metadata,
    Column("user_id", String(50), primary_key=True),
    Column("quartz", Integer, nullable=False, default=30),
    Column("qp", Integer, nullable=False, default=2000),
    Column("training_exp", Integer, nullable=False, default=300),
    Column("pity_counter", Integer, nullable=False, default=0),
    Column("master_template_id", String(40), nullable=False, default="chaldea_uniform"),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    Column("updated_at", DateTime, nullable=False, server_default=func.now(), onupdate=func.now()),
)

currency_ledger = Table(
    "currency_ledger",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("user_id", String(50), nullable=False),
    Column("amount", Integer, nullable=False),
    Column("balance_after", Integer, nullable=False),
    Column("resource_type", String(30), nullable=False, default="quartz"),
    Column("reason", String(255), nullable=False),
    Column("idempotency_key", String(160), nullable=False, unique=True),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    Index("ix_chaldea_ledger_user_created", "user_id", "created_at"),
)

daily_claims = Table(
    "daily_claims",
    metadata,
    Column("user_id", String(50), primary_key=True),
    Column("claim_date", Date, primary_key=True),
    Column("amount", Integer, nullable=False),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
)

owned_servants = Table(
    "owned_servants",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("user_id", String(50), nullable=False),
    Column("servant_id", String(80), nullable=False),
    Column("level", Integer, nullable=False, default=1),
    Column("np_level", Integer, nullable=False, default=1),
    Column("shards", Integer, nullable=False, default=0),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    UniqueConstraint("user_id", "servant_id", name="uq_chaldea_owned_user_servant"),
    Index("ix_chaldea_owned_user", "user_id"),
)

teams = Table(
    "teams",
    metadata,
    Column("user_id", String(50), primary_key=True),
    Column("servant_ids", JSON, nullable=False),
    Column("updated_at", DateTime, nullable=False, server_default=func.now(), onupdate=func.now()),
)

summon_rolls = Table(
    "summon_rolls",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("user_id", String(50), nullable=False),
    Column("banner_id", String(80), nullable=False, default="story"),
    Column("interaction_id", String(80), nullable=False, unique=True),
    Column("draw_count", Integer, nullable=False),
    Column("cost", Integer, nullable=False),
    Column("results", JSON, nullable=False),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
)

battles = Table(
    "battles",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("challenger_id", String(50), nullable=False),
    Column("opponent_id", String(50), nullable=False),
    Column("status", String(20), nullable=False),
    Column("turn", Integer, nullable=False, default=0),
    Column("state", JSON, nullable=True),
    Column("winner_id", String(50), nullable=True),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    Column("updated_at", DateTime, nullable=False, server_default=func.now(), onupdate=func.now()),
    Index("ix_chaldea_battle_challenger_status", "challenger_id", "status"),
    Index("ix_chaldea_battle_opponent_status", "opponent_id", "status"),
)

battle_actions = Table(
    "battle_actions",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("battle_id", String(36), nullable=False),
    Column("turn", Integer, nullable=False),
    Column("user_id", String(50), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    UniqueConstraint("battle_id", "turn", "user_id", name="uq_chaldea_action_battle_turn_user"),
)

battle_comments = Table(
    "battle_comments",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("battle_id", String(36), nullable=False),
    Column("user_id", String(50), nullable=False),
    Column("content", String(60), nullable=False),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    Index("ix_chaldea_comments_battle_id", "battle_id", "id"),
    Index("ix_chaldea_comments_user_created", "user_id", "created_at"),
)
