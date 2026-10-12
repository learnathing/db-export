"""Interactive selection; selected identities survive filtering."""

import re
from fnmatch import fnmatchcase
from pathlib import Path

from prompt_toolkit.application import Application
from prompt_toolkit.filters import has_focus
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.shortcuts import radiolist_dialog
from prompt_toolkit.widgets import Label, TextArea
from sqlalchemy import inspect

from .schema import SECTIONS, list_tables
from .styles import THEMES


def display(value):
    return re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", str(value or ""))


class Selection:
    def __init__(self, items, selected=()):
        self.items = items
        self.selected = set(selected)
        self.query = ""
        self.only_selected = False

    def visible(self):
        query = self.query.casefold().strip()
        return [item for item in self.items
                if (not self.only_selected or item["name"] in self.selected)
                and (not query or query in item["name"].casefold()
                     or query in (item.get("comment") or "").casefold()
                     or fnmatchcase(item["name"].casefold(), query))]

    def toggle(self, name):
        if name in self.selected:
            self.selected.remove(name)
        else:
            self.selected.add(name)

    def result(self):
        return [item["name"] for item in self.items if item["name"] in self.selected]


def selection_app(items, title, *, selected=(), allow_empty=False, input=None, output=None):
    state = Selection(items, selected)
    cursor = 0
    notice = ""
    search = TextArea(height=1, prompt="搜索：", multiline=False)
    bindings = KeyBindings()

    def changed(_):
        nonlocal cursor
        state.query = search.text
        cursor = 0

    search.buffer.on_text_changed += changed

    def render():
        nonlocal cursor
        visible = state.visible()
        cursor = min(cursor, max(0, len(visible) - 1))
        if not visible:
            return [("", "没有匹配项；修改搜索或按 F2 返回全部视图。")]
        # Keep the active row visible, including on smaller terminals.
        height = max(1, app.output.get_size().rows - 9)
        start = max(0, cursor - height + 1)
        result = []
        for index in range(start, min(len(visible), start + height)):
            item = visible[index]
            checked = "✓" if item["name"] in state.selected else " "
            result.append(("reverse" if index == cursor else "",
                           f"[{checked}] {display(item['name'])}  {display(item.get('comment'))}\n"))
        return result

    control = FormattedTextControl(render, focusable=True)

    @bindings.add("tab")
    def focus(event):
        event.app.layout.focus(control if event.app.layout.has_focus(search) else search)

    @bindings.add("/", filter=has_focus(control))
    def focus_search(event):
        event.app.layout.focus(search)

    @bindings.add("up")
    def up(event):
        nonlocal cursor
        cursor = max(0, cursor - 1)
        event.app.layout.focus(control)

    @bindings.add("down")
    def down(event):
        nonlocal cursor
        cursor = min(max(0, len(state.visible()) - 1), cursor + 1)
        event.app.layout.focus(control)

    @bindings.add(" ", filter=has_focus(control))
    def toggle(event):
        visible = state.visible()
        if visible:
            state.toggle(visible[min(cursor, len(visible) - 1)]["name"])

    @bindings.add("f2")
    def selected_view(event):
        nonlocal cursor
        state.only_selected = not state.only_selected
        cursor = 0

    @bindings.add("f3")
    def select_visible(event):
        state.selected.update(item["name"] for item in state.visible())

    @bindings.add("f4")
    def clear(event):
        state.selected.clear()

    @bindings.add("enter", eager=True)
    def finish(event):
        nonlocal notice
        if event.app.layout.has_focus(search):
            event.app.layout.focus(control)
        elif state.selected or allow_empty:
            event.app.exit(result=state.result())
        else:
            notice = "请至少选择一张表。"

    @bindings.add("c-c")
    @bindings.add("c-d")
    def cancel(event):
        event.app.exit(exception=KeyboardInterrupt())

    body = HSplit([
        Label(title), search,
        Label(lambda: f"匹配 {len(state.visible())} / {len(items)} 项　已选 {len(state.selected)} 项　"
              f"视图：{'已选' if state.only_selected else '全部'}"),
        Window(control, wrap_lines=False),
        Label(lambda: notice),
        Label("Tab 切换搜索/列表 · ↑↓ 移动 · 空格 勾选 · Enter 下一步\n"
              "F2 已选视图 · F3 全选筛选结果 · F4 清除全部 · Ctrl+C 取消"),
    ])
    app = Application(layout=Layout(body, focused_element=search), key_bindings=bindings,
                      full_screen=True, input=input, output=output)
    return app


def fill_connection(args, db_types):
    if args.url:
        return
    if not args.db_type:
        args.db_type = radiolist_dialog(title="数据库类型", values=[(x, x) for x in db_types]).run()
        if args.db_type is None:
            raise KeyboardInterrupt
    if not args.database:
        args.database = input("数据库名称 / SQLite 路径 / Oracle service name：").strip()
    if args.db_type != "sqlite":
        if not args.host:
            args.host = input("服务器 [localhost]：").strip() or "localhost"
        if args.port is None:
            port = input("端口 [默认]：").strip()
            if port:
                args.port = int(port)
        if not args.user:
            args.user = input("用户名：").strip()


def configure_export(connection, args):
    inspector = inspect(connection)
    if args.schema is None:
        default = inspector.default_schema_name
        schemas = inspector.get_schema_names()
        schemas = sorted(set(schemas) | ({default} if default else set()))
        choice = radiolist_dialog(title="选择 Schema", values=[("", f"默认 ({display(default)})")]
                                  + [(s, display(s)) for s in schemas]).run()
        if choice is None:
            raise KeyboardInterrupt
        args.schema = choice or default
    print("正在读取表名和注释…", flush=True)
    catalog = list_tables(connection, args.schema, args.include, args.exclude)
    names = selection_app(catalog, f"选择导出的数据表 · Schema {display(args.schema)}").run()
    sections = selection_app([{"name": k, "comment": v} for k, v in SECTIONS.items()],
                             "选择附加内容（字段和主键标记始终保留）",
                             selected=SECTIONS, allow_empty=True).run()
    while True:
        path = input(f"输出文件 [{args.output}]：").strip()
        candidate = Path(path).expanduser() if path else args.output
        if candidate.suffix.lower() != ".docx":
            print("请使用 .docx 扩展名。")
            continue
        if candidate.exists() and not args.force:
            print("文件已存在；请选择其他路径，或退出后使用 --force。")
            continue
        args.output = candidate
        break
    args.title = input(f"文档标题 [{args.title}]：").strip() or args.title
    while True:
        choice = input(f"文档样式 classic / compact / monochrome [{args.theme}]：").strip() or args.theme
        if choice in THEMES:
            args.theme = choice
            break
        print("请选择 classic、compact 或 monochrome。")
    default_break = THEMES[args.theme].page_break if args.table_page_break is None else args.table_page_break
    while True:
        choice = input(f"每张表另起一页？[{'Y/n' if default_break else 'y/N'}]：").strip().lower()
        if choice in ("", "y", "yes", "n", "no"):
            args.table_page_break = default_break if not choice else choice in ("y", "yes")
            break
        print("请输入 y 或 n。")
    print(f"即将导出 {len(names)} 张表：{', '.join(display(n) for n in names)}")
    print(f"附加内容：{', '.join(SECTIONS[s] for s in sections) or '无'}")
    print(f"输出：{args.output}" + ("（覆盖已有文件）" if args.output.exists() else ""))
    if input("确认导出？[y/N]：").strip().lower() not in ("y", "yes"):
        raise KeyboardInterrupt
    return names, sections
