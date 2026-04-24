"""Seed the DuckDB backend with TPC-H-like demo data and register semantic layer entries."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.duckdb_backend import DuckDBBackend
from app.storage.registry import BackendRegistry
from app.models.semantic import SemanticMetric, SemanticDimension, SemanticSynonym, SemanticJoinPath

logger = logging.getLogger(__name__)

TPCH_DDL = """
CREATE SCHEMA IF NOT EXISTS tpch;

CREATE TABLE IF NOT EXISTS tpch.orders (
    o_orderkey INTEGER PRIMARY KEY,
    o_custkey INTEGER,
    o_orderstatus VARCHAR(1),
    o_totalprice DECIMAL(15,2),
    o_orderdate DATE,
    o_orderpriority VARCHAR(15),
    o_clerk VARCHAR(15),
    o_shippriority INTEGER,
    o_comment VARCHAR(79),
    o_region VARCHAR(25),
    o_category VARCHAR(25)
);

CREATE TABLE IF NOT EXISTS tpch.customer (
    c_custkey INTEGER PRIMARY KEY,
    c_name VARCHAR(25),
    c_address VARCHAR(40),
    c_nationkey INTEGER,
    c_phone VARCHAR(15),
    c_acctbal DECIMAL(15,2),
    c_mktsegment VARCHAR(10),
    c_comment VARCHAR(117),
    c_region VARCHAR(25)
);

CREATE TABLE IF NOT EXISTS tpch.lineitem (
    l_orderkey INTEGER,
    l_partkey INTEGER,
    l_suppkey INTEGER,
    l_linenumber INTEGER,
    l_quantity DECIMAL(15,2),
    l_extendedprice DECIMAL(15,2),
    l_discount DECIMAL(15,2),
    l_tax DECIMAL(15,2),
    l_returnflag VARCHAR(1),
    l_linestatus VARCHAR(1),
    l_shipdate DATE,
    l_commitdate DATE,
    l_receiptdate DATE,
    l_shipinstruct VARCHAR(25),
    l_shipmode VARCHAR(10),
    l_comment VARCHAR(44),
    PRIMARY KEY (l_orderkey, l_linenumber)
);
"""

DEMO_DATA = """
INSERT INTO tpch.orders VALUES
(1, 1, 'O', 15000.00, '2026-04-01', '1-URGENT', 'Clerk#1', 0, 'comment1', '北美', '电子产品'),
(2, 2, 'O', 22000.50, '2026-04-02', '2-HIGH', 'Clerk#2', 0, 'comment2', '北美', '服装'),
(3, 3, 'O', 8500.00, '2026-04-03', '3-MEDIUM', 'Clerk#3', 0, 'comment3', '欧洲', '电子产品'),
(4, 4, 'F', 31000.00, '2026-04-05', '1-URGENT', 'Clerk#1', 0, 'comment4', '北美', '食品'),
(5, 5, 'O', 12000.00, '2026-04-07', '5-LOW', 'Clerk#4', 0, 'comment5', '亚太', '电子产品'),
(6, 1, 'O', 9800.00, '2026-04-08', '3-MEDIUM', 'Clerk#2', 0, 'comment6', '欧洲', '服装'),
(7, 2, 'O', 45000.00, '2026-04-10', '1-URGENT', 'Clerk#5', 0, 'comment7', '北美', '电子产品'),
(8, 3, 'F', 7200.00, '2026-04-11', '4-NOT SPECIFIED', 'Clerk#3', 0, 'comment8', '亚太', '食品'),
(9, 6, 'O', 18500.00, '2026-04-12', '2-HIGH', 'Clerk#1', 0, 'comment9', '北美', '服装'),
(10, 7, 'O', 26000.00, '2026-04-13', '1-URGENT', 'Clerk#6', 0, 'comment10', '欧洲', '电子产品'),
(11, 1, 'O', 13500.00, '2026-03-01', '2-HIGH', 'Clerk#1', 0, 'prev1', '北美', '电子产品'),
(12, 2, 'O', 28000.00, '2026-03-05', '1-URGENT', 'Clerk#2', 0, 'prev2', '北美', '服装'),
(13, 3, 'O', 19000.00, '2026-03-10', '3-MEDIUM', 'Clerk#3', 0, 'prev3', '欧洲', '电子产品'),
(14, 4, 'O', 35000.00, '2026-03-15', '1-URGENT', 'Clerk#1', 0, 'prev4', '北美', '食品'),
(15, 5, 'O', 16000.00, '2026-03-20', '5-LOW', 'Clerk#4', 0, 'prev5', '亚太', '电子产品'),
(16, 6, 'O', 11000.00, '2026-03-22', '2-HIGH', 'Clerk#5', 0, 'prev6', '欧洲', '服装'),
(17, 7, 'O', 42000.00, '2026-03-25', '1-URGENT', 'Clerk#6', 0, 'prev7', '北美', '电子产品'),
(18, 1, 'O', 8800.00, '2026-03-28', '4-NOT SPECIFIED', 'Clerk#2', 0, 'prev8', '亚太', '食品');

INSERT INTO tpch.customer VALUES
(1, 'Customer#1', 'Address1', 1, '111-111', 1000.00, 'BUILDING', 'comment', '北美'),
(2, 'Customer#2', 'Address2', 2, '222-222', 2000.00, 'AUTOMOBILE', 'comment', '北美'),
(3, 'Customer#3', 'Address3', 3, '333-333', 1500.00, 'MACHINERY', 'comment', '欧洲'),
(4, 'Customer#4', 'Address4', 1, '444-444', 3000.00, 'HOUSEHOLD', 'comment', '北美'),
(5, 'Customer#5', 'Address5', 4, '555-555', 800.00, 'FURNITURE', 'comment', '亚太'),
(6, 'Customer#6', 'Address6', 3, '666-666', 1200.00, 'BUILDING', 'comment', '欧洲'),
(7, 'Customer#7', 'Address7', 2, '777-777', 2500.00, 'AUTOMOBILE', 'comment', '欧洲');

INSERT INTO tpch.lineitem VALUES
(1, 101, 201, 1, 10, 15000.00, 0.05, 0.08, 'N', 'O', '2026-04-05', '2026-04-03', '2026-04-06', 'DELIVER', 'TRUCK', 'comment'),
(2, 102, 202, 1, 20, 22000.50, 0.10, 0.08, 'N', 'O', '2026-04-06', '2026-04-04', '2026-04-07', 'COLLECT', 'SHIP', 'comment'),
(3, 103, 203, 1, 5, 8500.00, 0.00, 0.08, 'N', 'O', '2026-04-08', '2026-04-05', '2026-04-09', 'DELIVER', 'AIR', 'comment'),
(4, 104, 204, 1, 30, 31000.00, 0.15, 0.08, 'A', 'F', '2026-04-10', '2026-04-07', '2026-04-11', 'NONE', 'RAIL', 'comment'),
(5, 105, 205, 1, 8, 12000.00, 0.02, 0.08, 'N', 'O', '2026-04-12', '2026-04-09', '2026-04-13', 'DELIVER', 'TRUCK', 'comment');
"""


def seed_duckdb(backend: DuckDBBackend) -> None:
    """Create demo tables and insert sample data."""
    backend.execute_sql_sync("CREATE SCHEMA IF NOT EXISTS rover_meta")
    backend.execute_sql_sync(
        "CREATE TABLE IF NOT EXISTS rover_meta.seed_marker "
        "(name VARCHAR PRIMARY KEY, seeded_at TIMESTAMP DEFAULT current_timestamp)"
    )
    marker = backend.fetch_one_sql_sync(
        "SELECT name FROM rover_meta.seed_marker WHERE name = 'tpch-demo-v1'"
    )
    if marker is not None:
        logger.info("DuckDB demo data already seeded, skipping.")
        return

    logger.info("Seeding DuckDB with TPC-H demo data...")
    for statement in TPCH_DDL.strip().split(";"):
        stmt = statement.strip()
        if stmt:
            backend.execute_sql_sync(stmt)

    for statement in DEMO_DATA.strip().split(";"):
        stmt = statement.strip()
        if stmt:
            try:
                backend.execute_sql_sync(stmt)
            except Exception as e:
                if "Duplicate" in str(e) or "duplicate" in str(e).lower() or "already exists" in str(e).lower():
                    logger.debug("Skipping duplicate data: %s", e)
                else:
                    logger.warning("Seed data insertion warning: %s", e)

    backend.execute_sql_sync(
        "INSERT INTO rover_meta.seed_marker(name) VALUES ('tpch-demo-v1')"
    )
    logger.info("DuckDB seeding complete.")


async def seed_semantic_layer(db: AsyncSession) -> None:
    """Register semantic metrics, dimensions, synonyms and join paths."""
    from sqlalchemy import select

    existing = await db.execute(select(SemanticMetric).limit(1))
    if existing.scalar_one_or_none():
        logger.info("Semantic layer already seeded, skipping.")
        return

    logger.info("Seeding semantic layer...")

    metrics = [
        SemanticMetric(
            name="gmv", display_name="GMV", description="成交总额",
            calculation="SUM(o_totalprice)", source_table="orders",
            source_schema="tpch", backend_id="duckdb-local", data_type="decimal",
        ),
        SemanticMetric(
            name="order_count", display_name="订单量", description="订单总数",
            calculation="COUNT(*)", source_table="orders",
            source_schema="tpch", backend_id="duckdb-local", data_type="integer",
        ),
        SemanticMetric(
            name="avg_order_value", display_name="客单价", description="平均订单金额",
            calculation="AVG(o_totalprice)", source_table="orders",
            source_schema="tpch", backend_id="duckdb-local", data_type="decimal",
        ),
    ]

    dimensions = [
        SemanticDimension(
            name="region", display_name="地区",
            source_column="o_region", source_table="orders",
            source_schema="tpch", backend_id="duckdb-local",
        ),
        SemanticDimension(
            name="category", display_name="品类",
            source_column="o_category", source_table="orders",
            source_schema="tpch", backend_id="duckdb-local",
        ),
        SemanticDimension(
            name="order_date", display_name="订单日期",
            source_column="o_orderdate", source_table="orders",
            source_schema="tpch", backend_id="duckdb-local",
        ),
        SemanticDimension(
            name="order_status", display_name="订单状态",
            source_column="o_orderstatus", source_table="orders",
            source_schema="tpch", backend_id="duckdb-local",
        ),
    ]

    synonyms = [
        SemanticSynonym(term="成交额", canonical_name="gmv", entity_type="metric"),
        SemanticSynonym(term="成交总额", canonical_name="gmv", entity_type="metric"),
        SemanticSynonym(term="销售额", canonical_name="gmv", entity_type="metric"),
        SemanticSynonym(term="营收", canonical_name="gmv", entity_type="metric"),
        SemanticSynonym(term="revenue", canonical_name="gmv", entity_type="metric"),
        SemanticSynonym(term="订单数", canonical_name="order_count", entity_type="metric"),
        SemanticSynonym(term="订单数量", canonical_name="order_count", entity_type="metric"),
        SemanticSynonym(term="order count", canonical_name="order_count", entity_type="metric"),
        SemanticSynonym(term="均价", canonical_name="avg_order_value", entity_type="metric"),
        SemanticSynonym(term="平均订单金额", canonical_name="avg_order_value", entity_type="metric"),
        SemanticSynonym(term="区域", canonical_name="region", entity_type="dimension"),
        SemanticSynonym(term="地区", canonical_name="region", entity_type="dimension"),
        SemanticSynonym(term="品类", canonical_name="category", entity_type="dimension"),
        SemanticSynonym(term="类别", canonical_name="category", entity_type="dimension"),
        SemanticSynonym(term="日期", canonical_name="order_date", entity_type="dimension"),
    ]

    join_paths = [
        SemanticJoinPath(
            left_table="orders", right_table="customer",
            join_condition="orders.o_custkey = customer.c_custkey",
            join_type="INNER", source_schema="tpch", backend_id="duckdb-local",
        ),
        SemanticJoinPath(
            left_table="orders", right_table="lineitem",
            join_condition="orders.o_orderkey = lineitem.l_orderkey",
            join_type="INNER", source_schema="tpch", backend_id="duckdb-local",
        ),
    ]

    db.add_all(metrics + dimensions + synonyms + join_paths)
    await db.commit()
    logger.info("Semantic layer seeding complete.")
