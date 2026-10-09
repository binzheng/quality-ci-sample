"""CI レポート用の共通部品 (枠の一覧・JSON/XML 読み込み・HTML 部品).

標準ライブラリのみで動作する。ci_report.py と pages_site.py から import する。
"""
from __future__ import annotations

import html
import json
import os
import shutil
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))

# FE のパッケージ。増やしたらここと ci.yml の fe ジョブ (matrix) に追加する
FE_PACKAGES = ["demo-fe"]

# 状態: (アイコン, 表示名)
STATUS = {
    "pass": ("✅", "成功"),
    "warn": ("🟡", "警告あり"),
    "fail": ("❌", "失敗"),
    "info": ("ℹ️", "集計"),
    "missing": ("⚠️", "成果物なし"),
    "na": ("➖", "対象外"),
    "omitted": ("✂️", "容量のため省略"),
}


# --------------------------------------------------------------------------- 枠 (スロット)
def build_catalog() -> list[dict]:
    """Pages に載せる枠の一覧.

    id       Artifact 名は pages-<id>。Artifact の根 = その枠のサイトの根
    group    be / fe / docs
    package  FE のパッケージ名 (be / docs は None)
    path     Pages 上のパス (末尾 / 付き)
    priority 容量予算を超えたときに大きいほど残す
    """
    slots = [
        {"id": "be-tests", "group": "be", "package": None, "title": "テスト結果 (JUnit)",
         "path": "be/tests/", "priority": 80},
        {"id": "be-jacoco", "group": "be", "package": None, "title": "カバレッジ (JaCoCo)",
         "path": "be/jacoco/", "priority": 70},
        {"id": "be-javadoc", "group": "be", "package": None, "title": "Javadoc",
         "path": "be/javadoc/", "priority": 40},
        {"id": "be-checkstyle", "group": "be", "package": None, "title": "Checkstyle",
         "path": "be/checkstyle/", "priority": 35},
        {"id": "be-spotbugs", "group": "be", "package": None, "title": "SpotBugs",
         "path": "be/spotbugs/", "priority": 35},
    ]
    for pkg in FE_PACKAGES:
        slots += [
            {"id": f"fe-{pkg}-vitest", "group": "fe", "package": pkg, "title": "テスト結果＋カバレッジ (Vitest)",
             "short": "Vitest", "path": f"fe/{pkg}/vitest/", "priority": 80},
            {"id": f"fe-{pkg}-storybook", "group": "fe", "package": pkg, "title": "Storybook",
             "short": "Storybook", "path": f"fe/{pkg}/storybook/", "priority": 60},
            {"id": f"fe-{pkg}-eslint", "group": "fe", "package": pkg, "title": "ESLint",
             "short": "ESLint", "path": f"fe/{pkg}/eslint/", "priority": 35},
            {"id": f"fe-{pkg}-audit", "group": "fe", "package": pkg, "title": "npm audit",
             "short": "npm audit", "path": f"fe/{pkg}/audit/", "priority": 30},
            {"id": f"fe-{pkg}-sloc", "group": "fe", "package": pkg, "title": "SLOCCount (cloc)",
             "short": "SLOC", "path": f"fe/{pkg}/sloc/", "priority": 20},
        ]
    slots.append({"id": "docs", "group": "docs", "package": None, "title": "ドキュメント",
                  "path": "docs/", "priority": 100})
    return slots


def catalog_by_id() -> dict[str, dict]:
    return {s["id"]: s for s in build_catalog()}


# --------------------------------------------------------------------------- 読み込み
def load_json(path: Path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_xml(path: Path):
    try:
        return ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return None


def to_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def to_float(value, default: float = 0.0) -> float:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return default


def pct(covered: float, total: float) -> float:
    return round(100.0 * covered / total, 1) if total else 0.0


def first_line(text, limit: int = 200) -> str:
    lines = str(text or "").strip().splitlines()
    return lines[0][:limit] if lines else ""


def copy_dir(src: Path, dst: Path) -> bool:
    if not src.is_dir():
        return False
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    return True


def dir_size(path: Path, exclude: str | None = None) -> int:
    total = 0
    for p in path.rglob("*"):
        if exclude and exclude in p.relative_to(path).parts:
            continue
        if p.is_file():
            total += p.stat().st_size
    return total


# --------------------------------------------------------------------------- 日時
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_iso(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def fmt_jst(value: str | None) -> str:
    dt = parse_iso(value)
    return dt.astimezone(JST).strftime("%Y-%m-%d %H:%M") if dt else "-"


def is_stale(value: str | None, days: int = 7) -> bool:
    dt = parse_iso(value)
    return bool(dt) and datetime.now(timezone.utc) - dt > timedelta(days=days)


# --------------------------------------------------------------------------- 実行環境
def run_context() -> dict:
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    return {
        "server": server,
        "repo": repo,
        "run_id": run_id,
        "run_url": f"{server}/{repo}/actions/runs/{run_id}" if repo and run_id else "",
        # PR では GITHUB_SHA が仮マージコミットになるため、ワークフローから HEAD_SHA を渡す
        "commit": os.environ.get("HEAD_SHA") or os.environ.get("GITHUB_SHA", ""),
        "ref": os.environ.get("GITHUB_HEAD_REF") or os.environ.get("GITHUB_REF_NAME", ""),
        "event": os.environ.get("GITHUB_EVENT_NAME", ""),
    }


# --------------------------------------------------------------------------- HTML
def esc(value) -> str:
    return html.escape(str(value))


def md_cell(value) -> str:
    """Markdown の表のセル用にエスケープする."""
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    return text.replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;")


BASE_CSS = """
:root{--bg:#ffffff;--fg:#1f2328;--muted:#59636e;--border:#d1d9e0;--card:#f6f8fa;--link:#0969da;
--pass:#1a7f37;--warn:#9a6700;--fail:#d1242f;--info:#0969da;--stale:#8c959f;color-scheme:light}
@media (prefers-color-scheme: dark){:root{--bg:#0d1117;--fg:#e6edf3;--muted:#9198a1;--border:#3d444d;
--card:#151b23;--link:#4493f8;--pass:#3fb950;--warn:#d29922;--fail:#f85149;--info:#4493f8;--stale:#6e7681;
color-scheme:dark}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.6 system-ui,-apple-system,"Segoe UI","Hiragino Sans","Noto Sans JP",sans-serif}
main{max-width:1200px;margin:0 auto;padding:24px 16px}
a{color:var(--link)}
h1{font-size:22px;margin:4px 0 12px}
h2{font-size:17px;margin:0 0 10px}
code{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px}
table{border-collapse:collapse;width:100%;margin:8px 0;font-size:13px}
th,td{border:1px solid var(--border);padding:6px 8px;text-align:left;vertical-align:top;overflow-wrap:anywhere}
th{background:var(--card);font-weight:600}
.wrap{overflow-x:auto}
.muted{color:var(--muted)}
.s-pass{color:var(--pass)}.s-warn{color:var(--warn)}.s-fail{color:var(--fail)}.s-info{color:var(--info)}
.s-missing{color:var(--warn)}.s-na,.s-omitted{color:var(--muted)}
"""


def table_html(headers, rows) -> str:
    if not rows:
        return '<p class="muted">該当なし</p>'
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in row) + "</tr>" for row in rows)
    return f'<div class="wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def write_page(path: Path, title: str, body: str, css: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '<!doctype html><html lang="ja"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{esc(title)}</title><style>{BASE_CSS}{css}</style></head>"
        f"<body><main>{body}</main></body></html>",
        encoding="utf-8",
    )
