import asyncio
import sqlite3

from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from sqlalchemy import create_engine, event

from db_export.cli import main
from db_export.interactive import Selection, selection_app
from db_export.schema import list_tables, read_schema


def test_filter_retains_selections():
    state = Selection([{"name": "orders", "comment": "订单"}, {"name": "users", "comment": "用户"}])
    state.toggle("users")
    state.query = "订单"
    assert [x["name"] for x in state.visible()] == ["orders"]
    state.toggle("orders")
    state.query = "user*"
    assert state.result() == ["orders", "users"]
    state.only_selected = True
    state.toggle("users")
    assert state.visible() == []


def test_real_key_bindings_select_and_keep_hidden_items():
    async def run():
        with create_pipe_input() as pipe:
            app = selection_app([{"name": "orders"}, {"name": "users"}], "表选择",
                                input=pipe, output=DummyOutput())
            # Filter, move into list, select; return to search and replace filter.
            pipe.send_text("orders\r \t\x15users\r \r")
            return await asyncio.wait_for(app.run_async(), timeout=3)
    assert asyncio.run(run()) == ["orders", "users"]


def test_empty_selection_blocks_enter_and_cancel_exits():
    async def run():
        with create_pipe_input() as pipe:
            app = selection_app([{"name": "a"}], "选择", input=pipe, output=DummyOutput())
            pipe.send_text("\r\r\x03")
            try:
                await asyncio.wait_for(app.run_async(), timeout=3)
            except KeyboardInterrupt:
                return "cancelled"
    assert asyncio.run(run()) == "cancelled"


def test_catalog_is_lazy_and_explicit_names_are_literal(tmp_path):
    path = tmp_path / "schema.db"
    with sqlite3.connect(path) as db:
        db.executescript('CREATE TABLE "a*" (id INTEGER PRIMARY KEY); CREATE TABLE abc (id INTEGER);')
    engine = create_engine(f"sqlite:///{path}")
    statements = []
    event.listen(engine, "before_cursor_execute", lambda c, cu, st, p, ctx, many: statements.append(st))
    try:
        with engine.connect() as connection:
            assert len(list_tables(connection)) == 2
            assert not any("table_xinfo" in s or "index_list" in s for s in statements)
            tables, notices = read_schema(connection, names=["a*"], sections=[])
        assert [t["name"] for t in tables] == ["a*"]
        assert tables[0]["indexes"] == [] and tables[0]["foreign_keys"] == []
        assert not any("index_list" in s or "foreign_key_list" in s for s in statements)
    finally:
        engine.dispose()


def test_interactive_rejects_pipes(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert main(["--interactive"]) == 2
    assert "真实终端" in capsys.readouterr().err


def test_interactive_export_applies_selection_and_sections(tmp_path, monkeypatch):
    from docx import Document
    import db_export.interactive as ui

    path = tmp_path / "sample.db"
    output = tmp_path / "selected.docx"
    with sqlite3.connect(path) as db:
        db.executescript('CREATE TABLE orders (id INTEGER); CREATE INDEX ix_orders ON orders(id); '
                         'CREATE TABLE users (id INTEGER);')
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    choices = iter([["orders"], []])

    class App:
        def run(self):
            return next(choices)

    monkeypatch.setattr(ui, "selection_app", lambda *a, **kw: App())
    answers = iter(["", "", "", "", "y"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    assert main(["-i", "--db-type", "sqlite", "--database", str(path), "--schema", "main",
                 "-o", str(output)]) == 0
    doc = Document(output)
    cells = " ".join(c.text for t in doc.tables for r in t.rows for c in r.cells)
    assert "orders" in cells and "users" not in cells and "ix_orders" not in cells
