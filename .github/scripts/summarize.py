#!/usr/bin/env python3
"""CI の各種レポートを集計し、PR コメント用 Markdown と Pages 用 HTML を生成する.

標準ライブラリのみで動作する。

Usage:
  summarize.py fe <fe/reports> <out_dir>          FE レポート集計
  summarize.py be <be/target> <out_dir>           BE レポート集計
  summarize.py docs <outcome> <docs/site> <out>   Docs ビルド結果
  summarize.py comment <out.md> <summary.md>...   PR コメント本文を生成
  summarize.py portal <site_dir>                  Pages のトップページを生成
  summarize.py gate <summary.json>                品質ゲート判定 (不合格なら exit 1)
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

ICON = {"pass": "✅", "warn": "⚠️", "fail": "❌", "info": "ℹ️"}
MAX_ROWS = 30
JST = timezone(timedelta(hours=9))

CSS = """
:root{--bg:#fff;--fg:#1f2328;--muted:#59636e;--border:#d1d9e0;--card:#f6f8fa;--link:#0969da;
--pass:#1a7f37;--warn:#9a6700;--fail:#d1242f;--info:#0969da}
@media (prefers-color-scheme: dark){:root{--bg:#0d1117;--fg:#e6edf3;--muted:#9198a1;--border:#3d444d;
--card:#151b23;--link:#4493f8;--pass:#3fb950;--warn:#d29922;--fail:#f85149;--info:#4493f8}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.6 system-ui,-apple-system,"Segoe UI","Hiragino Sans","Noto Sans JP",sans-serif}
main{max-width:1200px;margin:0 auto;padding:24px 16px}
a{color:var(--link)}
h1{font-size:24px;margin:8px 0 16px}
table{border-collapse:collapse;width:100%;margin:12px 0;font-size:13px}
th,td{border:1px solid var(--border);padding:6px 8px;text-align:left;vertical-align:top;word-break:break-word}
th{background:var(--card)}
.wrap{overflow-x:auto}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,340px),1fr));gap:16px}
.card{border:1px solid var(--border);border-radius:8px;padding:16px;background:var(--card)}
.card h2{margin:0 0 8px;font-size:18px}
.s-pass{color:var(--pass)}.s-warn{color:var(--warn)}.s-fail{color:var(--fail)}.s-info{color:var(--info)}
.muted{color:var(--muted)}
ul.items{list-style:none;padding:0;margin:0}
ul.items li{padding:8px 0;border-top:1px solid var(--border)}
ul.items .name{font-weight:600}
.banner{padding:12px 16px;border-radius:8px;border:1px solid var(--border);margin-bottom:16px}
"""


# --------------------------------------------------------------------------- helpers
def load_json(path: Path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def parse_xml(path: Path):
    try:
        return ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return None


def esc(value) -> str:
    return html.escape(str(value))


def md(value) -> str:
    """Markdown テーブルセル用にエスケープする."""
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    return text.replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;")


def pct(covered: float, total: float) -> float:
    return 100.0 * covered / total if total else 0.0


def fpct(value) -> str:
    return f"{value:.1f}%" if isinstance(value, (int, float)) else str(value)


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


def table_html(headers, rows) -> str:
    if not rows:
        return '<p class="muted">該当なし</p>'
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in row) + "</tr>" for row in rows)
    return f'<div class="wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def status_html(status: str) -> str:
    return f'<span class="s-{status}">{ICON[status]}</span>'


def write_page(path: Path, title: str, body: str, back: tuple[str, str] | None = ("index.html", "← 一覧へ")) -> None:
    nav = f'<p><a href="{back[0]}">{esc(back[1])}</a></p>' if back else ""
    path.write_text(
        "<!doctype html><html lang=\"ja\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{esc(title)}</title><style>{CSS}</style></head>"
        f"<body><main>{nav}<h1>{esc(title)}</h1>{body}</main></body></html>",
        encoding="utf-8",
    )


def now_jst() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")


# --------------------------------------------------------------------------- report model
class Report:
    def __init__(self, project: str, title: str, out_dir: str):
        self.project = project
        self.title = title
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        self.items: list[dict] = []
        self.details: list[tuple[str, list, list]] = []
        self.gate_failures: list[str] = []

    def add(self, name: str, status: str, result: str, link: str | None = None) -> None:
        self.items.append({"name": name, "status": status, "result": result, "link": link})

    def fail_gate(self, reason: str) -> None:
        self.gate_failures.append(reason)

    def detail(self, summary: str, headers: list, rows: list) -> None:
        if rows:
            self.details.append((summary, headers, rows))

    def write(self) -> None:
        lines = [f"### {self.title}", "", "| チェック | 状態 | 結果 |", "|---|:---:|---|"]
        for it in self.items:
            lines.append(f"| {md(it['name'])} | {ICON[it['status']]} | {md(it['result'])} |")
        if self.gate_failures:
            lines += ["", "**品質ゲート不合格:** " + " / ".join(md(g) for g in self.gate_failures)]
        for summary, headers, rows in self.details:
            lines += ["", "<details>", f"<summary>{esc(summary)}</summary>", ""]
            lines.append("| " + " | ".join(md(h) for h in headers) + " |")
            lines.append("|" + "---|" * len(headers))
            for row in rows[:MAX_ROWS]:
                lines.append("| " + " | ".join(md(c) for c in row) + " |")
            if len(rows) > MAX_ROWS:
                lines += ["", f"…他 {len(rows) - MAX_ROWS} 件 (詳細は Artifacts / Pages のレポートを参照)"]
            lines += ["", "</details>"]
        lines.append("")
        (self.out / "summary.md").write_text("\n".join(lines), encoding="utf-8")

        (self.out / "summary.json").write_text(
            json.dumps(
                {
                    "project": self.project,
                    "title": self.title,
                    "items": self.items,
                    "gate_failures": self.gate_failures,
                    "generated_at": now_jst(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        lis = []
        for it in self.items:
            name = esc(it["name"])
            if it["link"]:
                name = f'<a href="{esc(it["link"])}">{name}</a>'
            lis.append(f'<li>{status_html(it["status"])} <span class="name">{name}</span>'
                       f'<br><span class="muted">{esc(it["result"])}</span></li>')
        gate = ""
        if self.gate_failures:
            gate = '<div class="banner s-fail">品質ゲート不合格: ' + esc(" / ".join(self.gate_failures)) + "</div>"
        write_page(self.out / "index.html", self.title, gate + '<ul class="items">' + "".join(lis) + "</ul>"
                   + f'<p class="muted">生成: {now_jst()}</p>', back=("../index.html", "← ポータルへ"))


# --------------------------------------------------------------------------- FE
def cmd_fe(reports_dir: str, out_dir: str) -> int:
    src = Path(reports_dir)
    root = src.parent.resolve()
    r = Report("fe", "🖥️ Frontend (fe)", out_dir)

    def rel(p: str) -> str:
        try:
            return os.path.relpath(p, root)
        except ValueError:
            return p

    # ---- ESLint
    data = load_json(src / "eslint.json")
    if data is None:
        r.add("ESLint", "fail", "レポートが生成されませんでした")
        r.fail_gate("ESLint レポートなし")
    else:
        rows = []
        for f in data:
            for m in f.get("messages", []):
                rows.append([rel(f["filePath"]), m.get("line", "-"),
                             "error" if m.get("severity") == 2 else "warning",
                             m.get("ruleId") or "-", m.get("message", "")])
        errors = sum(f.get("errorCount", 0) for f in data)
        warnings = sum(f.get("warningCount", 0) for f in data)
        status = "fail" if errors else ("warn" if warnings else "pass")
        r.add("ESLint", status, f"エラー {errors} / 警告 {warnings} (対象 {len(data)} ファイル)", "eslint.html")
        if errors:
            r.fail_gate(f"ESLint エラー {errors} 件")
        headers = ["ファイル", "行", "重大度", "ルール", "メッセージ"]
        r.detail(f"ESLint 指摘 ({len(rows)} 件)", headers, rows)
        write_page(r.out / "eslint.html", "ESLint",
                   f"<p>エラー {errors} / 警告 {warnings} / 対象 {len(data)} ファイル</p>" + table_html(headers, rows))

    # ---- Vitest
    res = load_json(src / "vitest" / "results.json")
    if res is None:
        r.add("Vitest", "fail", "テスト結果が生成されませんでした")
        r.fail_gate("Vitest 結果なし")
    else:
        total = res.get("numTotalTests", 0)
        passed = res.get("numPassedTests", 0)
        failed = res.get("numFailedTests", 0)
        skipped = res.get("numPendingTests", 0) + res.get("numTodoTests", 0)
        failed_suites = res.get("numFailedTestSuites", 0)
        rows = []
        for tr in res.get("testResults", []):
            for a in tr.get("assertionResults", []):
                if a.get("status") == "failed":
                    rows.append([rel(tr.get("name", "")), a.get("fullName", ""),
                                 first_line((a.get("failureMessages") or [""])[0])])
            if tr.get("status") == "failed" and not tr.get("assertionResults"):
                rows.append([rel(tr.get("name", "")), "(ファイル読込失敗)", first_line(tr.get("message"))])
        status = "fail" if failed or failed_suites else "pass"
        link = "vitest/index.html" if copy_dir(src / "vitest" / "html", r.out / "vitest") else None
        r.add("Vitest", status,
              f"{passed}/{total} 成功 (失敗 {failed} / スキップ {skipped} / {len(res.get('testResults', []))} ファイル)",
              link)
        if status == "fail":
            r.fail_gate(f"Vitest 失敗 {failed} 件")
        r.detail(f"失敗したテスト ({len(rows)} 件)", ["ファイル", "テスト", "メッセージ"], rows)

    # ---- Coverage
    cov = load_json(src / "coverage" / "coverage-summary.json")
    if cov is None:
        r.add("Coverage (v8)", "warn", "カバレッジが生成されませんでした")
    else:
        t = cov.get("total", {})
        lines_pct = t.get("lines", {}).get("pct", 0)
        status = "pass" if isinstance(lines_pct, (int, float)) and lines_pct >= 80 else "warn"
        link = "coverage/index.html" if copy_dir(src / "coverage", r.out / "coverage") else None
        r.add("Coverage (v8)", status,
              " / ".join(f"{k.capitalize()} {fpct(t.get(k, {}).get('pct', 0))}"
                         for k in ("lines", "statements", "functions", "branches")),
              link)
        rows = sorted(
            ([rel(k), fpct(v["lines"]["pct"]), fpct(v["branches"]["pct"]), fpct(v["functions"]["pct"])]
             for k, v in cov.items() if k != "total"),
            key=lambda row: to_float(str(row[1]).rstrip("%"), 0),
        )
        r.detail(f"ファイル別カバレッジ ({len(rows)} ファイル, 低い順)", ["ファイル", "Lines", "Branches", "Functions"], rows)

    # ---- Storybook
    idx = load_json(src / "storybook" / "index.json")
    if idx is None:
        r.add("Storybook", "fail", "ビルドに失敗しました")
        r.fail_gate("Storybook ビルド失敗")
    else:
        entries = list(idx.get("entries", {}).values())
        stories = [e for e in entries if e.get("type") == "story"]
        components = sorted({e.get("title", "") for e in stories})
        copy_dir(src / "storybook", r.out / "storybook")
        r.add("Storybook", "pass", f"ビルド成功: {len(components)} コンポーネント / {len(stories)} ストーリー",
              "storybook/index.html")

    # ---- npm audit
    audit = load_json(src / "npm-audit.json")
    if not audit or "metadata" not in audit:
        r.add("npm audit", "warn", "監査結果を取得できませんでした")
    else:
        v = audit["metadata"].get("vulnerabilities", {})
        order = ["critical", "high", "moderate", "low", "info"]
        total = v.get("total", sum(v.get(k, 0) for k in order))
        r.add("npm audit", "warn" if total else "pass",
              f"合計 {total} 件 (" + " / ".join(f"{k} {v.get(k, 0)}" for k in order[:4]) + ")", "audit.html")
        rows = []
        for name, vul in audit.get("vulnerabilities", {}).items():
            titles = [x.get("title", "") for x in vul.get("via", []) if isinstance(x, dict)]
            via = "; ".join(titles) or "依存: " + ", ".join(x for x in vul.get("via", []) if isinstance(x, str))
            fix = vul.get("fixAvailable")
            fix_text = f"{fix.get('name')}@{fix.get('version')}" if isinstance(fix, dict) else ("あり" if fix else "なし")
            rows.append([vul.get("severity", ""), name, vul.get("range", ""), via, fix_text])
        rank = {k: i for i, k in enumerate(order)}
        rows.sort(key=lambda row: rank.get(row[0], 99))
        headers = ["重大度", "パッケージ", "影響範囲", "内容", "修正"]
        r.detail(f"npm audit 警告 ({len(rows)} パッケージ)", headers, rows)
        write_page(r.out / "audit.html", "npm audit",
                   "<p>" + esc(" / ".join(f"{k}: {v.get(k, 0)}" for k in order)) + "</p>" + table_html(headers, rows))

    # ---- SLOCCount (cloc)
    cloc = load_json(src / "cloc.json")
    if cloc is None:
        r.add("SLOCCount", "warn", "集計できませんでした")
    else:
        langs = sorted(((k, v) for k, v in cloc.items() if k not in ("header", "SUM")),
                       key=lambda kv: -kv[1].get("code", 0))
        s = cloc.get("SUM", {})
        r.add("SLOCCount", "info",
              f"{s.get('code', 0)} 行 / {s.get('nFiles', 0)} ファイル (" +
              ", ".join(f"{k} {v.get('code', 0)}" for k, v in langs) + ")", "sloc.html")
        lang_rows = [[k, v.get("nFiles", 0), v.get("blank", 0), v.get("comment", 0), v.get("code", 0)] for k, v in langs]
        by_file = load_json(src / "cloc-by-file.json") or {}
        file_rows = sorted(([k, v.get("language", ""), v.get("blank", 0), v.get("comment", 0), v.get("code", 0)]
                            for k, v in by_file.items() if k not in ("header", "SUM")), key=lambda row: -row[4])
        write_page(r.out / "sloc.html", "SLOCCount (cloc)",
                   "<h2>言語別</h2>" + table_html(["言語", "ファイル", "空行", "コメント", "コード"], lang_rows)
                   + "<h2>ファイル別</h2>" + table_html(["ファイル", "言語", "空行", "コメント", "コード"], file_rows))

    r.write()
    return 0


# --------------------------------------------------------------------------- BE
def cmd_be(target_dir: str, out_dir: str) -> int:
    t = Path(target_dir)
    project_root = t.parent.resolve()
    r = Report("be", "⚙️ Backend (be)", out_dir)

    # ---- JUnit (Surefire)
    files = sorted((t / "surefire-reports").glob("TEST-*.xml"))
    if not files:
        r.add("JUnit", "fail", "テスト結果が生成されませんでした")
        r.fail_gate("JUnit 結果なし")
    else:
        total = failures = errors = skipped = 0
        suites, rows = [], []
        for f in files:
            s = parse_xml(f)
            if s is None:
                continue
            tests, fl, er, sk = (to_int(s.get(k)) for k in ("tests", "failures", "errors", "skipped"))
            total, failures, errors, skipped = total + tests, failures + fl, errors + er, skipped + sk
            ok = ICON["fail"] if fl + er else ICON["pass"]
            suites.append([ok, s.get("name", f.stem), tests, fl, er, sk, f"{to_float(s.get('time')):.2f}s"])
            for tc in s.iter("testcase"):
                for kind in ("failure", "error"):
                    el = tc.find(kind)
                    if el is not None:
                        rows.append([tc.get("classname", ""), tc.get("name", ""), kind,
                                     first_line(el.get("message") or el.text)])
        broken = failures + errors
        passed = total - broken - skipped
        r.add("JUnit", "fail" if broken else "pass",
              f"{passed}/{total} 成功 (失敗 {broken} / スキップ {skipped} / {len(suites)} クラス)", "tests.html")
        if broken:
            r.fail_gate(f"JUnit 失敗 {broken} 件")
        r.detail(f"失敗したテスト ({len(rows)} 件)", ["クラス", "テスト", "種別", "メッセージ"], rows)
        write_page(r.out / "tests.html", "JUnit テスト結果",
                   f"<p>{passed}/{total} 成功 / 失敗 {broken} / スキップ {skipped}</p>"
                   + table_html(["", "クラス", "テスト数", "失敗", "エラー", "スキップ", "時間"], suites)
                   + "<h2>失敗したテスト</h2>" + table_html(["クラス", "テスト", "種別", "メッセージ"], rows))

    # ---- JaCoCo
    root = parse_xml(t / "site" / "jacoco" / "jacoco.xml")
    if root is None:
        r.add("JaCoCo", "warn", "カバレッジが生成されませんでした")
    else:
        def counter_pct(node, kind: str) -> float:
            for c in node.findall("counter"):
                if c.get("type") == kind:
                    missed, covered = to_int(c.get("missed")), to_int(c.get("covered"))
                    return pct(covered, missed + covered)
            return 0.0

        line = counter_pct(root, "LINE")
        copy_dir(t / "site" / "jacoco", r.out / "jacoco")
        r.add("JaCoCo", "pass" if line >= 80 else "warn",
              " / ".join(f"{label} {counter_pct(root, kind):.1f}%" for label, kind in
                         (("Line", "LINE"), ("Branch", "BRANCH"), ("Method", "METHOD"), ("Instruction", "INSTRUCTION"))),
              "jacoco/index.html")
        rows = []
        for pkg in root.findall("package"):
            for cls in pkg.findall("class"):
                rows.append([cls.get("name", "").replace("/", "."),
                             f"{counter_pct(cls, 'LINE'):.1f}%", f"{counter_pct(cls, 'BRANCH'):.1f}%"])
        rows.sort(key=lambda row: to_float(row[1].rstrip("%")))
        r.detail(f"クラス別カバレッジ ({len(rows)} クラス, 低い順)", ["クラス", "Line", "Branch"], rows)

    # ---- Javadoc
    log_path = t / "javadoc.log"
    log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    pattern = re.compile(r"([^\s\[\]]+\.java):(\d+): (warning|error):?\s*(.*)")
    found = {}
    for raw in log.splitlines():
        m = pattern.search(raw)
        if m:
            path, line_no, level, msg = m.groups()
            try:
                path = os.path.relpath(path, project_root)
            except ValueError:
                pass
            found[(path, line_no, level, msg)] = None
    jd_rows = [list(k) for k in found]
    jd_warn = sum(1 for k in found if k[2] == "warning")
    jd_err = sum(1 for k in found if k[2] == "error")
    apidocs = next(iter(sorted(t.glob("**/apidocs/index.html"))), None)
    if apidocs is None:
        r.add("Javadoc", "fail", f"生成に失敗しました (エラー {jd_err})")
        r.fail_gate("Javadoc 生成失敗")
    else:
        copy_dir(apidocs.parent, r.out / "javadoc")
        r.add("Javadoc", "warn" if jd_warn or jd_err else "pass",
              f"生成成功 / 警告 {jd_warn} / エラー {jd_err}", "javadoc/index.html")
    r.detail(f"Javadoc 警告 ({len(jd_rows)} 件)", ["ファイル", "行", "種別", "メッセージ"], jd_rows)

    # ---- Checkstyle
    root = parse_xml(t / "checkstyle-result.xml")
    if root is None:
        r.add("Checkstyle", "warn", "レポートが生成されませんでした")
    else:
        rows = []
        for f in root.findall("file"):
            try:
                name = os.path.relpath(f.get("name", ""), project_root)
            except ValueError:
                name = f.get("name", "")
            for e in f.findall("error"):
                rule = (e.get("source") or "").split(".")[-1].removesuffix("Check")
                rows.append([name, e.get("line", "-"), e.get("severity", ""), rule, e.get("message", "")])
        errs = sum(1 for row in rows if row[2] == "error")
        others = len(rows) - errs
        r.add("Checkstyle", "fail" if errs else ("warn" if others else "pass"),
              f"エラー {errs} / 警告 {others} (対象 {len(root.findall('file'))} ファイル)", "checkstyle.html")
        if errs:
            r.fail_gate(f"Checkstyle エラー {errs} 件")
        headers = ["ファイル", "行", "重大度", "ルール", "メッセージ"]
        r.detail(f"Checkstyle 指摘 ({len(rows)} 件)", headers, rows)
        write_page(r.out / "checkstyle.html", "Checkstyle",
                   f"<p>エラー {errs} / 警告 {others}</p>" + table_html(headers, rows))

    # ---- SpotBugs
    root = parse_xml(t / "spotbugsXml.xml")
    if root is None:
        r.add("SpotBugs", "warn", "レポートが生成されませんでした")
    else:
        prio = {"1": "High", "2": "Medium", "3": "Low"}
        rows = []
        for bug in root.findall("BugInstance"):
            cls = bug.find("Class")
            src_line = bug.find("SourceLine")
            msg = bug.findtext("ShortMessage") or bug.findtext("LongMessage") or ""
            rows.append([prio.get(bug.get("priority", ""), bug.get("priority", "")), bug.get("category", ""),
                         bug.get("type", ""), cls.get("classname", "") if cls is not None else "",
                         src_line.get("start", "-") if src_line is not None else "-", msg])
        rows.sort(key=lambda row: ["High", "Medium", "Low"].index(row[0]) if row[0] in prio.values() else 9)
        counts = {p: sum(1 for row in rows if row[0] == p) for p in ("High", "Medium", "Low")}
        status = "fail" if counts["High"] else ("warn" if rows else "pass")
        r.add("SpotBugs", status,
              f"合計 {len(rows)} 件 (High {counts['High']} / Medium {counts['Medium']} / Low {counts['Low']})",
              "spotbugs.html")
        if counts["High"]:
            r.fail_gate(f"SpotBugs High {counts['High']} 件")
        headers = ["優先度", "カテゴリ", "種別", "クラス", "行", "内容"]
        r.detail(f"SpotBugs 指摘 ({len(rows)} 件)", headers, rows)
        write_page(r.out / "spotbugs.html", "SpotBugs",
                   "<p>" + esc(" / ".join(f"{k}: {v}" for k, v in counts.items())) + "</p>" + table_html(headers, rows))

    r.write()
    return 0


# --------------------------------------------------------------------------- Docs
def cmd_docs(outcome: str, site_dir: str, out_dir: str) -> int:
    site = Path(site_dir)
    r = Report("docs", "📚 Docs", out_dir)
    if outcome == "success" and (site / "index.html").exists():
        pages = [p for p in site.rglob("index.html") if "assets" not in p.parts]
        copy_dir(site, r.out / "site")
        r.add("MkDocs build", "pass", f"ビルド成功 ({len(pages)} ページ)", "site/index.html")
    else:
        r.add("MkDocs build", "fail", "ビルドに失敗しました (--strict)")
        r.fail_gate("MkDocs ビルド失敗")
    r.write()
    return 0


# --------------------------------------------------------------------------- PR comment
def pages_url() -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" not in repo:
        return ""
    owner, name = repo.split("/", 1)
    return f"https://{owner.lower()}.github.io/{name}/"


def cmd_comment(out_path: str, *summaries: str) -> int:
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    sha = os.environ.get("HEAD_SHA") or os.environ.get("GITHUB_SHA", "")
    run_url = f"{server}/{repo}/actions/runs/{run_id}"

    bodies, failures = [], []
    for path in summaries:
        p = Path(path)
        if p.exists():
            bodies.append(p.read_text(encoding="utf-8"))
            data = load_json(p.with_name("summary.json")) or {}
            failures += [f"{data.get('project', '?')}: {g}" for g in data.get("gate_failures", [])]
        else:
            name = p.parent.name.removesuffix("-report") or path
            bodies.append(f"### {name}\n\n❌ サマリーが生成されませんでした (ジョブが途中で失敗した可能性があります)\n")
            failures.append(f"{name}: サマリーなし")

    gate = ("✅ **品質ゲート: 合格**" if not failures
            else "❌ **品質ゲート: 不合格** — " + " / ".join(md(f) for f in failures))
    head = [
        "## 📊 品質レポート",
        "",
        gate,
        "",
        f"コミット `{sha[:7]}` ・ 更新 {now_jst()} ・ [ワークフロー実行]({run_url})",
        "",
        "> 詳細レポート (HTML) は実行ページの **Artifacts** (`fe-report` / `be-report` / `docs-report`) からダウンロードできます。",
    ]
    url = pages_url()
    if url:
        head.append(f"> develop ブランチの最新レポート: {url}")
    text = "\n".join(head) + "\n\n" + "\n---\n\n".join(bodies)
    if len(text) > 60000:  # GitHub コメントの上限 (65536 文字) 対策
        text = text[:60000] + "\n\n…(長すぎるため省略しました)"
    Path(out_path).write_text(text, encoding="utf-8")
    return 0


# --------------------------------------------------------------------------- Pages portal
def cmd_portal(site_dir: str) -> int:
    site = Path(site_dir)
    sources = [("fe", site / "fe" / "summary.json", "fe/"),
               ("be", site / "be" / "summary.json", "be/"),
               ("docs", site / "docs-summary.json", "")]
    cards, failures = [], []
    for project, summary_path, prefix in sources:
        data = load_json(summary_path)
        if data is None:
            cards.append(f'<section class="card"><h2>{esc(project)}</h2>'
                         f'<p class="s-fail">{ICON["fail"]} レポートがありません (ジョブ失敗)</p></section>')
            failures.append(f"{project}: レポートなし")
            continue
        failures += [f"{project}: {g}" for g in data.get("gate_failures", [])]
        lis = []
        for it in data.get("items", []):
            link = it.get("link")
            if project == "docs":
                link = "docs/" if site.joinpath("docs", "index.html").exists() else None
            name = esc(it["name"])
            if link:
                name = f'<a href="{esc(prefix + link)}">{name}</a>'
            lis.append(f'<li>{status_html(it["status"])} <span class="name">{name}</span>'
                       f'<br><span class="muted">{esc(it["result"])}</span></li>')
        title = esc(data.get("title", project))
        if project != "docs":
            title = f'<a href="{prefix}index.html">{title}</a>'
        cards.append(f'<section class="card"><h2>{title}</h2><ul class="items">{"".join(lis)}</ul></section>')

    sha = os.environ.get("GITHUB_SHA", "")
    ref = os.environ.get("GITHUB_REF_NAME", "")
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    commit = f'<a href="{server}/{repo}/commit/{sha}"><code>{sha[:7]}</code></a>' if sha else "-"
    banner_status = "fail" if failures else "pass"
    banner = (f'<div class="banner s-{banner_status}">{ICON[banner_status]} 品質ゲート: '
              + ("不合格 — " + esc(" / ".join(failures)) if failures else "合格") + "</div>")
    links = '<p><a href="docs/">📚 ドキュメント</a> ・ <a href="fe/storybook/">📖 Storybook</a> ・ ' \
            '<a href="be/javadoc/">☕ Javadoc</a></p>'
    meta = f'<p class="muted">ブランチ {esc(ref or "-")} ・ コミット {commit} ・ 生成 {now_jst()}</p>'
    write_page(site / "index.html", "品質レポート ポータル",
               meta + banner + links + '<div class="grid">' + "".join(cards) + "</div>", back=None)
    return 0


# --------------------------------------------------------------------------- gate
def cmd_gate(summary_path: str) -> int:
    data = load_json(Path(summary_path))
    if data is None:
        print(f"::error::{summary_path} がありません")
        return 1
    if data.get("gate_failures"):
        for g in data["gate_failures"]:
            print(f"::error::{data.get('project')}: {g}")
        return 1
    print(f"{data.get('project')}: 品質ゲート合格")
    return 0


COMMANDS = {"fe": cmd_fe, "be": cmd_be, "docs": cmd_docs, "comment": cmd_comment,
            "portal": cmd_portal, "gate": cmd_gate}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(2)
    sys.exit(COMMANDS[sys.argv[1]](*sys.argv[2:]))
