"""Read metadata only; never query application rows or mutate the database."""

from fnmatch import fnmatchcase

from sqlalchemy import inspect


SECTIONS = {"indexes": "索引", "foreign_keys": "外键", "unique": "唯一约束", "checks": "检查约束"}


def table_names(inspector, schema=None, includes=(), excludes=()):
    available = sorted(inspector.get_table_names(schema=schema))
    for pattern in includes:
        if not any(fnmatchcase(name, pattern) for name in available):
            raise ValueError(f"找不到符合條件的資料表：{pattern}")
    names = [name for name in available
             if (not includes or any(fnmatchcase(name, p) for p in includes))
             and not any(fnmatchcase(name, p) for p in excludes)]
    if not names:
        raise ValueError("沒有可匯出的資料表，請檢查 schema、權限及篩選條件。")

    return names


def list_tables(connection, schema=None, includes=(), excludes=()):
    inspector = inspect(connection)
    catalog = []
    for name in table_names(inspector, schema, includes, excludes):
        try:
            comment = inspector.get_table_comment(name, schema=schema).get("text")
        except NotImplementedError:
            comment = None
        catalog.append({"name": name, "comment": comment})
    return catalog


def read_schema(connection, schema=None, includes=(), excludes=(), *, names=None, sections=None):
    inspector = inspect(connection)
    # Explicit selections are literal names, never glob patterns.
    if names is None:
        names = table_names(inspector, schema, includes, excludes)
    if not names:
        raise ValueError("请至少选择一张数据表。")
    sections = set(SECTIONS) if sections is None else set(sections)
    tables, warnings = [], []

    def optional(method, name, fallback, label):
        try:
            return method(name, schema=schema)
        except NotImplementedError:
            message = f"驱动不支持读取{label}，文档中的相关信息可能不完整。"
            if message not in warnings:
                warnings.append(message)
            return fallback

    for name in names:
        columns = inspector.get_columns(name, schema=schema)
        for column in columns:
            column["type"] = column["type"].compile(dialect=connection.dialect)
        tables.append({
            "name": name,
            "comment": optional(inspector.get_table_comment, name, {}, "表注释").get("text"),
            "columns": columns,
            "pk": inspector.get_pk_constraint(name, schema=schema).get("constrained_columns") or [],
            "foreign_keys": optional(inspector.get_foreign_keys, name, [], "外键") if "foreign_keys" in sections else [],
            "indexes": optional(inspector.get_indexes, name, [], "索引") if "indexes" in sections else [],
            "unique": optional(inspector.get_unique_constraints, name, [], "唯一约束") if "unique" in sections else [],
            "checks": optional(inspector.get_check_constraints, name, [], "检查约束") if "checks" in sections else [],
        })
    return tables, warnings
