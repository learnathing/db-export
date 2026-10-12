import argparse
import getpass
import re
import sys
from pathlib import Path
from urllib.parse import quote, quote_plus

from sqlalchemy import create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import SQLAlchemyError

from .document import build_document, save_document
from .schema import read_schema
from .styles import THEMES


DRIVERS = {"mysql": ("mysql+pymysql", 3306), "postgresql": ("postgresql+psycopg", 5432),
           "sqlserver": ("mssql+pyodbc", 1433), "oracle": ("oracle+oracledb", 1521),
           "sqlite": ("sqlite", None)}


def parser():
    p = argparse.ArgumentParser(description="將資料庫表結構匯出為 Word 資料字典，不讀取業務資料。")
    group = p.add_mutually_exclusive_group()
    p.add_argument("--interactive", "-i", action="store_true", help="交互选择 schema、数据表和导出内容")
    group.add_argument("--url", help="SQLAlchemy 連線 URL；特殊字元需 URL 編碼")
    group.add_argument("--db-type", choices=DRIVERS, help="資料庫種類")
    p.add_argument("--host", help="伺服器位址，預設 localhost")
    p.add_argument("--port", type=int)
    p.add_argument("--user")
    p.add_argument("--password", help="密碼；省略時互動輸入，空密碼使用 --password ''")
    p.add_argument("--database", help="資料庫名稱；SQLite 檔案路徑；Oracle service name")
    p.add_argument("--odbc-driver", help="SQL Server ODBC 驅動，預設 ODBC Driver 18 for SQL Server")
    p.add_argument("--schema", help="指定 schema，省略使用連線預設值")
    p.add_argument("--include", action="append", default=[], metavar="PATTERN", help="表名 glob，可重複；例如 --include 'sys_*'")
    p.add_argument("--exclude", action="append", default=[], metavar="PATTERN", help="排除表名 glob，可重複；排除優先")
    p.add_argument("-o", "--output", type=Path, default=Path("output/database.docx"))
    p.add_argument("--theme", choices=THEMES, default="classic", help="Word 样式：classic 正式、compact 紧凑、monochrome 黑白")
    p.add_argument("--table-page-break", action=argparse.BooleanOptionalAction, default=None,
                   help="每张表另起一页；compact 默认连续，其余样式默认分页")
    p.add_argument("--title", default="数据库结构说明书")
    p.add_argument("--force", action="store_true", help="覆蓋已存在的輸出文件")
    return p


def connection_url(args):
    if args.url:
        if any(getattr(args, name) is not None for name in ("host", "port", "user", "password", "database", "odbc_driver")):
            raise ValueError("--url 不可與個別連線參數混用。")
        try:
            url = make_url(args.url)
        except (ValueError, SQLAlchemyError):
            raise ValueError("連線 URL 格式不正確。") from None
    else:
        if not args.database:
            raise ValueError("請提供 --database。")
        driver, port = DRIVERS[args.db_type]
        if args.db_type == "sqlite":
            if any(getattr(args, name) is not None for name in ("host", "port", "user", "password", "odbc_driver")):
                raise ValueError("SQLite 僅需 --database，不接受伺服器連線參數。")
            url = URL.create(driver, database=args.database)
        else:
            if not args.user:
                raise ValueError("請提供 --user。")
            if args.port is not None and not 1 <= args.port <= 65535:
                raise ValueError("--port 必須介於 1 到 65535。")
            if args.odbc_driver and args.db_type != "sqlserver":
                raise ValueError("--odbc-driver 僅適用於 SQL Server。")
            password = args.password
            if password is None:
                password = getpass.getpass("資料庫密碼：")
            query = {}
            database = args.database
            if args.db_type == "oracle":
                query["service_name"], database = database, None
            elif args.db_type == "sqlserver":
                query["driver"] = args.odbc_driver or "ODBC Driver 18 for SQL Server"
            elif args.db_type == "mysql":
                query["charset"] = "utf8mb4"
            url = URL.create(driver, username=args.user, password=password,
                             host=args.host or "localhost", port=args.port or port,
                             database=database, query=query)
    if url.get_backend_name() == "sqlite":
        if url.query:
            raise ValueError("SQLite 不接受 URL query，請提供一般檔案路徑。")
        if not url.database or not Path(url.database).is_file():
            raise ValueError("SQLite 資料庫檔案不存在；不會自動建立空資料庫。")
    return url


def safe_driver_message(exc, url):
    """Expose the driver reason without SQLAlchemy's SQL/parameter dump."""
    original = getattr(exc, "orig", None)
    if original is None:
        return "驅動未提供詳細原因。請檢查連線 URL 與 dialect 設定。"
    message = str(original)
    secrets = []
    if url is not None:
        secrets.extend([url.password, url.username])
        for value in url.query.values():
            secrets.extend(value if isinstance(value, tuple) else [value])
    variants = set()
    for secret in filter(None, secrets):
        variants.update((secret, quote(secret, safe=""), quote_plus(secret),
                         repr(secret)[1:-1]))
    if variants:
        message = re.sub("|".join(re.escape(s) for s in sorted(variants, key=len, reverse=True)),
                         "<REDACTED>", message, flags=re.IGNORECASE)
    # Also mask credentials in incidental URLs and connection strings.
    message = re.sub(r"(\b[\w+.-]+://)[^\s/]*@", r"\1<REDACTED>@", message)
    message = re.sub(r"(?i)\b(password|passwd|pwd|token|secret)\s*[=:]\s*(?:'[^']*'|\"[^\"]*\"|[^\s;,]+)",
                     r"\1=<REDACTED>", message)
    message = re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", message)
    return message[:2000]


def main(argv=None):
    argument_parser = parser()
    args = argument_parser.parse_args(argv)
    if not args.interactive and not (args.url or args.db_type):
        argument_parser.error("请提供 --url 或 --db-type，或使用 --interactive。")
    engine = None
    url = None
    stage = "建立連線設定"
    try:
        if args.interactive:
            if not sys.stdin.isatty() or not sys.stdout.isatty():
                raise ValueError("交互模式需要真实终端；管道或自动化请使用非交互参数。")
            from .interactive import configure_export, fill_connection
            fill_connection(args, DRIVERS)
        if not args.interactive and args.output.suffix.lower() != ".docx":
            raise ValueError("輸出檔案必須以 .docx 結尾。")
        if not args.interactive and args.output.exists() and not args.force:
            raise ValueError("輸出檔案已存在；如需覆蓋，請加上 --force。")
        url = connection_url(args)
        if url.get_backend_name() == "sqlite" and args.output.resolve() == Path(url.database).resolve():
            raise ValueError("輸出路徑不可與資料庫檔案相同。")
        engine = create_engine(url, hide_parameters=True)
        stage = "連接資料庫"
        with engine.connect() as connection:
            stage = "讀取表結構"
            if args.interactive:
                names, sections = configure_export(connection, args)
                if url.get_backend_name() == "sqlite" and args.output.resolve() == Path(url.database).resolve():
                    raise ValueError("输出路径不可与数据库文件相同。")
                tables, notices = read_schema(connection, args.schema, names=names, sections=sections)
            else:
                tables, notices = read_schema(connection, args.schema, args.include, args.exclude)
        for notice in notices:
            print(f"提醒：{notice}", file=sys.stderr)
        doc = build_document(tables, args.title, url.database or url.query.get("service_name"), args.schema, notices,
                             theme=args.theme, table_page_break=args.table_page_break)
        save_document(doc, args.output, args.force)
        print(f"已匯出 {len(tables)} 張資料表：{args.output.resolve()}")
        return 0
    except ValueError as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        return 2
    except (ModuleNotFoundError, ImportError):
        print("錯誤：缺少資料庫驅動或系統依賴，請依 README 安裝對應 extra／ODBC 驅動。", file=sys.stderr)
        return 1
    except SQLAlchemyError as exc:
        print(f"錯誤：{stage}失敗（{type(exc).__name__}）。", file=sys.stderr)
        print(f"驅動原因：{safe_driver_message(exc, url)}", file=sys.stderr)
        return 1
    except OSError:
        print("錯誤：無法存取資料庫檔案或寫入文件，請檢查路徑、權限及檔案是否被占用。", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("已取消；非互動環境請提供完整連線參數。", file=sys.stderr)
        return 130
    finally:
        if engine is not None:
            engine.dispose()
