"""
Modo Prueba (Dry-Run).
Intercepta todas las escrituras a base de datos y Salesforce.
Las conexiones y lecturas funcionan con normalidad.

Activación: importar este módulo ANTES de cualquier operación de BD.
El server.py lo inyecta automáticamente cuando U4O_DRY_RUN=1.

Qué se intercepta:
  - pyodbc        : INSERT, UPDATE, DELETE, TRUNCATE, DROP, ALTER, MERGE, EXEC
  - mysql-connector: ídem
  - simple_salesforce: create, update, upsert, delete
  - pandas.to_sql : cualquier escritura de DataFrame a tabla
"""

import logging
import re
import sys

_log = logging.getLogger("DRY-RUN")
if not _log.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(asctime)s [DRY-RUN] %(message)s", "%H:%M:%S"))
    _log.addHandler(_h)
_log.setLevel(logging.INFO)
_log.propagate = False

_WRITE_RE = re.compile(
    r"^\s*(INSERT|UPDATE|DELETE|TRUNCATE|DROP|CREATE\s+TABLE|ALTER|MERGE|EXEC(UTE)?)\b",
    re.IGNORECASE | re.DOTALL,
)


def _es_escritura(sql: str) -> bool:
    return bool(_WRITE_RE.match(sql or ""))


def _corto(sql: str, n: int = 140) -> str:
    s = " ".join(sql.split())
    return (s[:n] + "…") if len(s) > n else s


# ── Proxy de cursor DBAPI ────────────────────────────────────────────────────

class _Cursor:
    """Envuelve un cursor DBAPI2; intercepta escrituras y las descarta."""

    def __init__(self, cur):
        object.__setattr__(self, "_c", cur)
        object.__setattr__(self, "_skip", False)

    # -- escritura/lectura --------------------------------------------------
    def execute(self, sql, *args, **kwargs):
        if _es_escritura(str(sql)):
            _log.info(f"SALTADO execute: {_corto(str(sql))}")
            object.__setattr__(self, "_skip", True)
            return self
        object.__setattr__(self, "_skip", False)
        return self._c.execute(sql, *args, **kwargs)

    def executemany(self, sql, params=None):
        if _es_escritura(str(sql)):
            n = len(params) if params else "?"
            _log.info(f"SALTADO executemany ({n} filas): {_corto(str(sql))}")
            object.__setattr__(self, "_skip", True)
            return self
        object.__setattr__(self, "_skip", False)
        return self._c.executemany(sql, params)

    # -- fetch ---------------------------------------------------------------
    def fetchall(self):       return [] if self._skip else self._c.fetchall()
    def fetchone(self):       return None if self._skip else self._c.fetchone()
    def fetchmany(self, n=1): return [] if self._skip else self._c.fetchmany(n)

    # -- propiedades ---------------------------------------------------------
    @property
    def rowcount(self):    return 0 if self._skip else self._c.rowcount
    @property
    def description(self): return None if self._skip else self._c.description

    # -- ciclo de vida -------------------------------------------------------
    def close(self):         self._c.close()
    def __enter__(self):     return self
    def __exit__(self, *_):  self.close()
    def __iter__(self):
        return iter([]) if self._skip else iter(self._c)

    # -- proxy genérico ------------------------------------------------------
    def __getattr__(self, n):
        return getattr(object.__getattribute__(self, "_c"), n)

    def __setattr__(self, n, v):
        if n in ("_c", "_skip"):
            object.__setattr__(self, n, v)
        else:
            setattr(object.__getattribute__(self, "_c"), n, v)


# ── Proxy de conexión DBAPI ──────────────────────────────────────────────────

class _Conn:
    """Envuelve una conexión DBAPI2; anula commit y delega cursores al proxy."""

    def __init__(self, conn):
        object.__setattr__(self, "_conn", conn)

    def cursor(self):    return _Cursor(self._conn.cursor())
    def commit(self):    _log.info("SALTADO: commit()")
    def rollback(self):  self._conn.rollback()
    def close(self):     self._conn.close()

    def execute(self, sql, *args, **kwargs):
        """Algunas librerías llaman conn.execute() directamente."""
        if _es_escritura(str(sql)):
            _log.info(f"SALTADO conn.execute: {_corto(str(sql))}")
            return _Cursor(self._conn.cursor())
        return _Cursor(self._conn.execute(sql, *args, **kwargs))

    def __enter__(self):
        return self

    def __exit__(self, exc, *_):
        self.commit() if exc is None else self.rollback()
        self.close()

    def __getattr__(self, n):
        return getattr(object.__getattribute__(self, "_conn"), n)

    def __setattr__(self, n, v):
        if n == "_conn":
            object.__setattr__(self, n, v)
        else:
            # Propiedades como autocommit se redirigen a la conexión real
            setattr(object.__getattribute__(self, "_conn"), n, v)


# ── Parchear pyodbc ──────────────────────────────────────────────────────────
try:
    import pyodbc as _p

    _orig_p = _p.connect
    _p.connect = lambda *a, **kw: _Conn(_orig_p(*a, **kw))
    _log.info("pyodbc interceptado (SQL Server / ODBC)")
except ImportError:
    _log.warning("pyodbc no disponible — omitido")


# ── Parchear mysql-connector ─────────────────────────────────────────────────
try:
    import mysql.connector as _mc

    _orig_mc = _mc.connect
    _mc.connect = lambda *a, **kw: _Conn(_orig_mc(*a, **kw))
    _log.info("mysql-connector interceptado")
except ImportError:
    _log.warning("mysql-connector no disponible — omitido")


# ── Parchear pandas.to_sql ───────────────────────────────────────────────────
try:
    import pandas as _pd

    _orig_to_sql = _pd.DataFrame.to_sql

    def _dry_to_sql(self, name, con, *a, **kw):
        _log.info(f"SALTADO DataFrame.to_sql('{name}') — {len(self)} filas")

    _pd.DataFrame.to_sql = _dry_to_sql
    _log.info("pandas.to_sql interceptado")
except ImportError:
    _log.warning("pandas no disponible — omitido")


# ── Parchear simple-salesforce ───────────────────────────────────────────────
try:
    from simple_salesforce import api as _sfa

    def _sf_create(self, data, **_):
        _log.info(f"SALTADO SF.create en '{self.name}': {str(data)[:80]}")
        return {"success": True, "id": "DRY-RUN-ID", "errors": []}

    def _sf_update(self, record_id, data, **_):
        _log.info(f"SALTADO SF.update en '{self.name}' / {record_id}")
        return 204

    def _sf_upsert(self, record_id, data, **_):
        _log.info(f"SALTADO SF.upsert en '{self.name}' / {record_id}")
        return 204

    def _sf_delete(self, record_id, **_):
        _log.info(f"SALTADO SF.delete en '{self.name}' / {record_id}")
        return 204

    _sfa.SFType.create = _sf_create
    _sfa.SFType.update = _sf_update
    _sfa.SFType.upsert = _sf_upsert
    _sfa.SFType.delete = _sf_delete
    _log.info("simple_salesforce interceptado (create / update / upsert / delete)")
except (ImportError, AttributeError) as _e:
    _log.warning(f"simple_salesforce no disponible — omitido ({_e})")


_log.info("=" * 55)
_log.info("MODO PRUEBA ACTIVO")
_log.info("  ✓ Conexiones y lecturas: normales")
_log.info("  ✗ Escrituras a BD y Salesforce: bloqueadas")
_log.info("=" * 55)
