"""Read-only lookups against the Samasya Postgres (over an SSH tunnel).

The two SQL statements can be overridden in secrets ([sql] lookup / volumes) so you can match the
exact query you use for your extracts without touching this code.
lookup  -> one row: packer, assembler, packed_at [, n_items]      (parameter %s = order_id)
volumes -> many rows: day, role, person, orders   (role = 'packer' / 'assembler'; orders packed per day)
"""
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone

import pandas as pd
import psycopg2
import streamlit as st
from config import START_DATE
from sshtunnel import SSHTunnelForwarder

# Matches the extract script: packer = "checker", assembler = "pharmacist", order id = "active_id".
IST = timezone(timedelta(hours=5, minutes=30))
_TGS = "to_timestamp(NULLIF(\"TGS\"::text, 'NA')::bigint / 1000) AT TIME ZONE 'Asia/Kolkata'"
DEFAULT_LOOKUP = f"""
    SELECT checker AS packer, pharmacist AS assembler, {_TGS} AS packed_at, n_items
    FROM "past_orders" WHERE active_id::text = %s
    ORDER BY packed_at DESC NULLS LAST LIMIT 1;
"""
DEFAULT_VOLUMES = f"""
    WITH po AS (
        SELECT {_TGS} AS ts, checker AS packer, pharmacist AS assembler FROM "past_orders"
        WHERE NULLIF("TGS"::text, 'NA')::bigint >= %s AND NULLIF("TGS"::text, 'NA')::bigint < %s
    )
    SELECT to_char(ts, 'YYYY-MM-DD') AS day, 'packer' AS role, lower(trim(packer)) AS person, count(*) AS orders
    FROM po WHERE packer IS NOT NULL GROUP BY 1, 3
    UNION ALL
    SELECT to_char(ts, 'YYYY-MM-DD'), 'assembler', lower(trim(assembler)), count(*)
    FROM po WHERE assembler IS NOT NULL GROUP BY 1, 3;
"""


def _ms(d: date) -> int:
    """Midnight (IST) at the start of day d, in epoch milliseconds (the unit of the TGS column)."""
    return int(datetime.combine(d, time.min, tzinfo=IST).timestamp() * 1000)


def _sql(name, default):
    return (st.secrets.get("sql", {}) or {}).get(name) or default


@contextmanager
def _conn():
    """Same secrets layout as the efficiency dashboard: [db] host/port/user/password/name and an optional [ssh]
    (password or private_key, `enabled = false` to skip the tunnel)."""
    db = dict(st.secrets["db"])
    ssh = dict(st.secrets["ssh"]) if "ssh" in st.secrets and st.secrets["ssh"].get("enabled", True) else None
    host, port = db.get("host", "127.0.0.1"), int(db.get("port", 5432))

    def connect(h, p):
        return psycopg2.connect(host=h, port=p, user=db["user"], password=db["password"],
                                dbname=db["name"], connect_timeout=20)

    if not ssh:
        conn = connect(host, port)
        try:
            yield conn
        finally:
            conn.close()
        return
    kwargs = dict(ssh_username=ssh["user"], remote_bind_address=(host, port), allow_agent=False, host_pkey_directories=[])
    if ssh.get("private_key"):
        import io
        import paramiko
        kwargs["ssh_pkey"] = paramiko.RSAKey.from_private_key(io.StringIO(ssh["private_key"]))
    else:
        kwargs["ssh_password"] = ssh["password"]
    with SSHTunnelForwarder((ssh["host"], int(ssh.get("port", 22))), **kwargs) as tunnel:
        conn = connect("127.0.0.1", tunnel.local_bind_port)
        try:
            yield conn
        finally:
            conn.close()


def _clean(x):
    return None if x is None else str(x).strip().lower()


@st.cache_data(ttl=600, show_spinner=False)
def lookup_order(order_id: str):
    """{'packer','assembler','packed_at','n_items'} or None if the order isn't found."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(_sql("lookup", DEFAULT_LOOKUP), (order_id,))
        row = cur.fetchone()
    if not row:
        return None
    return {"packer": _clean(row[0]), "assembler": _clean(row[1]), "packed_at": row[2],
            "n_items": int(row[3]) if len(row) > 3 and row[3] is not None else None}


def normalise_volumes(df: pd.DataFrame) -> pd.DataFrame:
    """Rows of (packed_at, packer, assembler) -> daily long table: day, role, person, orders (from START_DATE)."""
    ts = pd.to_datetime(df["packed_at"], errors="coerce")
    d = pd.DataFrame({"day": ts.dt.strftime("%Y-%m-%d"),
                      "packer": df["packer"].astype(str).str.strip().str.lower(),
                      "assembler": df["assembler"].astype(str).str.strip().str.lower()})
    d = d[ts.notna() & (ts >= START_DATE)]
    parts = []
    for role in ("packer", "assembler"):
        g = d[~d[role].isin(["", "nan", "none"])]
        parts.append(g.groupby(["day", role]).size().rename("orders").reset_index()
                     .rename(columns={role: "person"}).assign(role=role))
    return pd.concat(parts, ignore_index=True)


@st.cache_data(ttl=600, show_spinner="Counting orders per person from the database...")
def load_volumes(start: date, end: date) -> pd.DataFrame:
    """Orders packed per day / role / person, only for start..end (inclusive), so a small range is a small query."""
    custom = (st.secrets.get("sql", {}) or {}).get("volumes")
    with _conn() as conn, conn.cursor() as cur:
        if custom:   # a hand-written query in secrets runs as-is (no date parameters); filtered below
            cur.execute(custom)
        else:
            cur.execute(DEFAULT_VOLUMES, (_ms(start), _ms(end + timedelta(days=1))))
        rows = cur.fetchall()
    v = pd.DataFrame(rows, columns=["day", "role", "person", "orders"])
    v["orders"] = pd.to_numeric(v["orders"])
    if custom:
        d = pd.to_datetime(v["day"]).dt.date
        v = v[(d >= start) & (d <= end)]
    return v
