#!/usr/bin/env python3
"""CI の各ツールの出力を集計し、Pages の枠 (pages-<枠>) とジョブサマリ・注釈・PR コメントを作る.

Usage:
  ci_report.py fe   --package <pkg> --reports <fe/reports> --out <out> [--baseline <dir>]
  ci_report.py be   --target <be/target> --out <out> [--baseline <dir>]
  ci_report.py docs --outcome <success|failure> --build <docs/build> --out <out>
  ci_report.py report-html --summaries <dir> --out <ci-report.html> [--artifacts <artifacts.json>]
  ci_report.py comment --summaries <dir> --out <comment.md> [--report-url <url>] [--pages-url <url>]
  ci_report.py gate <out>/summary/<job>.json

PR では、全ジョブの結果を 1 ファイルの HTML (ci-report.html) にまとめ、圧縮せずに Artifact として上げる
(upload-artifact の archive: false)。PR コメントからそのリンクを開くとブラウザでそのまま表示される。

出力 (<out> 配下):
  pages/<枠>/                  その枠のサイト (index.html を含む)。Artifact pages-<枠> としてそのまま上げる
  pages/<枠>/_pages/summary.json   索引用の要約 (状態・件数・率・元コミット)。Pages の組み立て時に取り除く
  summary/<job>.md / .json     ジョブの要約 (ジョブサマリ・PR コメント・品質ゲート用)
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from report_common import (BASE_CSS, STATUS, catalog_by_id, copy_dir, esc, first_line, fmt_jst, load_json, md_cell,
                           now_iso, parse_xml, pct, run_context, table_html, to_float, to_int, write_json,
                           write_page)

MAX_ROWS = 30
MAX_ANNOTATIONS = 10  # GitHub は 1 ステップあたり error / warning 各 10 件まで表示する
REPO_ROOT = Path.cwd().resolve()


def rel(path: str) -> str:
    """リポジトリ直下からの相対パス (注釈の file= に使う)."""
    try:
        return Path(os.path.relpath(Path(path).resolve(), REPO_ROOT)).as_posix()
    except ValueError:
        return path


def fmt_pct(value) -> str:
    return f"{value:.1f}%" if isinstance(value, (int, float)) else "-"


def fmt_diff(value, base) -> str:
    if not isinstance(value, (int, float)) or not isinstance(base, (int, float)):
        return ""
    diff = value - base
    sign = "+" if diff > 0 else ("±" if diff == 0 else "")
    return f" (develop 比 {sign}{diff:.1f}pt)"


def baseline_metric(baseline: str | None, slot: str, *keys):
    if not baseline:
        return None
    data = load_json(Path(baseline) / slot / "_pages" / "summary.json") or {}
    node = data.get("metrics", {})
    for k in keys:
        if not isinstance(node, dict):
            return None
        node = node.get(k)
    return node


# --------------------------------------------------------------------------- 集計の器
class JobReport:
    def __init__(self, job: str, title: str, out: str):
        self.job = job
        self.title = title
        self.out = Path(out)
        self.ctx = run_context()
        self.rows: list[tuple[str, str, str]] = []  # (チェック, 状態, 結果)
        self.details: list[tuple[str, list, list]] = []
        self.gate_failures: list[str] = []
        self.annotations: dict[str, list[str]] = {"error": [], "warning": []}

    # ---- 枠
    def slot_dir(self, slot: str) -> Path:
        d = self.out / "pages" / slot
        d.mkdir(parents=True, exist_ok=True)
        return d

    def finish_slot(self, slot: str, status: str, headline: str, metrics: dict | None = None,
                    links: list[dict] | None = None) -> None:
        title = catalog_by_id().get(slot, {}).get("title", slot)
        self.rows.append((title, status, headline))
        write_json(self.slot_dir(slot) / "_pages" / "summary.json", {
            "slot": slot,
            "status": status,
            "headline": headline,
            "metrics": metrics or {},
            "links": links or [],
            "commit": self.ctx["commit"],
            "ref": self.ctx["ref"],
            "event": self.ctx["event"],
            "run_id": self.ctx["run_id"],
            "run_url": self.ctx["run_url"],
            "generated_at": now_iso(),
        })

    # ---- 指摘
    def detail(self, summary: str, headers: list, rows: list) -> None:
        if rows:
            self.details.append((summary, headers, rows))

    def annotate(self, level: str, message: str, file: str | None = None, line=None, title: str | None = None):
        def prop(v) -> str:
            return str(v).replace("%", "%25").replace("\r", "").replace("\n", "%0A").replace(":", "%3A").replace(",", "%2C")

        props = []
        if file:
            props.append(f"file={prop(file)}")
        if line:
            props.append(f"line={prop(line)}")
        if title:
            props.append(f"title={prop(title)}")
        msg = str(message).replace("%", "%25").replace("\r", "").replace("\n", "%0A")
        self.annotations[level].append(f"::{level} {','.join(props)}::{msg}")

    def fail_gate(self, reason: str) -> None:
        self.gate_failures.append(reason)

    # ---- 出力
    def write(self) -> None:
        lines = [f"### {self.title}", "", "| チェック | 状態 | 結果 |", "|---|:---:|---|"]
        for name, status, result in self.rows:
            lines.append(f"| {md_cell(name)} | {STATUS[status][0]} | {md_cell(result)} |")
        if self.gate_failures:
            lines += ["", "**品質ゲート不合格:** " + " / ".join(md_cell(g) for g in self.gate_failures)]
        for summary, headers, rows in self.details:
            lines += ["", "<details>", f"<summary>{esc(summary)}</summary>", ""]
            lines.append("| " + " | ".join(md_cell(h) for h in headers) + " |")
            lines.append("|" + "---|" * len(headers))
            lines += ["| " + " | ".join(md_cell(c) for c in row) + " |" for row in rows[:MAX_ROWS]]
            if len(rows) > MAX_ROWS:
                lines += ["", f"…他 {len(rows) - MAX_ROWS} 件 (Artifact のレポートを参照)"]
            lines += ["", "</details>"]
        lines.append("")
        text = "\n".join(lines)

        summary_dir = self.out / "summary"
        summary_dir.mkdir(parents=True, exist_ok=True)
        (summary_dir / f"{self.job}.md").write_text(text, encoding="utf-8")
        write_json(summary_dir / f"{self.job}.json", {
            "job": self.job, "title": self.title, "gate_failures": self.gate_failures,
            "rows": [{"name": n, "status": s, "result": r} for n, s, r in self.rows],
            # PR 用の 1 ファイル HTML レポートに全件を載せるため、指摘の一覧も省略せずに残す
            "details": [{"summary": s, "headers": h, "rows": [[str(c) for c in row] for row in rows]}
                        for s, h, rows in self.details],
            "commit": self.ctx["commit"], "run_url": self.ctx["run_url"], "generated_at": now_iso(),
        })

        step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if step_summary:
            with open(step_summary, "a", encoding="utf-8") as f:
                f.write(text + "\n")

        for level, items in self.annotations.items():
            for a in items[:MAX_ANNOTATIONS]:
                print(a)
            if len(items) > MAX_ANNOTATIONS:
                print(f"::{level}::他 {len(items) - MAX_ANNOTATIONS} 件はジョブサマリを参照してください")


# --------------------------------------------------------------------------- FE
def cmd_fe(args) -> int:
    pkg = args.package
    src = Path(args.reports)
    r = JobReport(f"fe-{pkg}", f"🖥️ Frontend ({pkg})", args.out)

    # ---- Vitest + カバレッジ → fe-<pkg>-vitest
    slot = f"fe-{pkg}-vitest"
    d = r.slot_dir(slot)
    res = load_json(src / "vitest" / "results.json")
    cov = load_json(src / "coverage" / "coverage-summary.json")
    has_html = copy_dir(src / "vitest" / "html", d)
    has_cov = copy_dir(src / "coverage", d / "coverage")
    metrics: dict = {}
    if res is None:
        status, headline = "fail", "テスト結果が生成されませんでした"
        r.fail_gate("Vitest 結果なし")
    else:
        total = res.get("numTotalTests", 0)
        failed = res.get("numFailedTests", 0)
        skipped = res.get("numPendingTests", 0) + res.get("numTodoTests", 0)
        broken_files = res.get("numFailedTestSuites", 0)
        metrics["tests"] = {"total": total, "passed": res.get("numPassedTests", 0), "failed": failed,
                            "skipped": skipped}
        rows = []
        for tr in res.get("testResults", []):
            file = rel(tr.get("name", ""))
            for a in tr.get("assertionResults", []):
                if a.get("status") == "failed":
                    msg = first_line((a.get("failureMessages") or [""])[0])
                    line = (a.get("location") or {}).get("line")
                    rows.append([file, line or "-", a.get("fullName", ""), msg])
                    r.annotate("error", msg, file, line, f"テスト失敗: {a.get('fullName', '')}")
            if tr.get("status") == "failed" and not tr.get("assertionResults"):
                rows.append([file, "-", "(ファイルの読み込みに失敗)", first_line(tr.get("message"))])
                r.annotate("error", first_line(tr.get("message")), file, None, "テストファイルの読み込み失敗")
        status = "fail" if failed or broken_files else "pass"
        headline = f"{total - failed - skipped}/{total} 成功 (失敗 {failed} / 省略 {skipped})"
        if status == "fail":
            r.fail_gate(f"Vitest 失敗 {failed} 件")
        r.detail(f"失敗したテスト ({len(rows)} 件)", ["ファイル", "行", "テスト", "メッセージ"], rows)
    if cov:
        t = cov.get("total", {})
        metrics["coverage"] = {k: t.get(k, {}).get("pct") for k in ("lines", "statements", "functions", "branches")}
        lines_pct = metrics["coverage"]["lines"]
        base = baseline_metric(args.baseline, slot, "coverage", "lines")
        headline += f" / Lines {fmt_pct(lines_pct)}{fmt_diff(lines_pct, base)}"
        cov_rows = sorted(([rel(k), fmt_pct(v["lines"]["pct"]), fmt_pct(v["branches"]["pct"]),
                            fmt_pct(v["functions"]["pct"])] for k, v in cov.items() if k != "total"),
                          key=lambda row: to_float(row[1].rstrip("%"), 0))
        r.detail(f"ファイル別カバレッジ (低い順, {len(cov_rows)} ファイル)", ["ファイル", "Lines", "Branches", "Functions"],
                 cov_rows)
    if not has_html:
        write_page(d / "index.html", f"Vitest ({pkg})",
                   f"<h1>Vitest ({esc(pkg)})</h1><p>{esc(headline)}</p>"
                   + ('<p><a href="coverage/">カバレッジ</a></p>' if has_cov else ""))
    r.finish_slot(slot, status, headline, metrics,
                  [{"label": "カバレッジ", "href": "coverage/"}] if has_cov else [])

    # ---- Storybook → fe-<pkg>-storybook
    slot = f"fe-{pkg}-storybook"
    idx = load_json(src / "storybook" / "index.json")
    if idx is None:
        r.finish_slot(slot, "fail", "ビルドに失敗しました")
        r.fail_gate("Storybook ビルド失敗")
        write_page(r.slot_dir(slot) / "index.html", "Storybook", "<h1>Storybook</h1><p>ビルドに失敗しました</p>")
    else:
        copy_dir(src / "storybook", r.slot_dir(slot))
        stories = [e for e in idx.get("entries", {}).values() if e.get("type") == "story"]
        comps = {e.get("title") for e in stories}
        r.finish_slot(slot, "pass", f"ビルド成功: {len(comps)} コンポーネント / {len(stories)} ストーリー",
                      {"stories": len(stories), "components": len(comps)})

    # ---- ESLint → fe-<pkg>-eslint
    slot = f"fe-{pkg}-eslint"
    data = load_json(src / "eslint.json")
    headers = ["ファイル", "行", "重大度", "ルール", "メッセージ"]
    if data is None:
        r.finish_slot(slot, "fail", "レポートが生成されませんでした")
        r.fail_gate("ESLint レポートなし")
        rows, errors, warnings = [], 0, 0
    else:
        rows = []
        for f in data:
            file = rel(f["filePath"])
            for m in f.get("messages", []):
                level = "error" if m.get("severity") == 2 else "warning"
                rows.append([file, m.get("line", "-"), level, m.get("ruleId") or "-", m.get("message", "")])
                if level == "error":
                    r.annotate("error", m.get("message", ""), file, m.get("line"), f"ESLint {m.get('ruleId') or ''}")
        errors = sum(f.get("errorCount", 0) for f in data)
        warnings = sum(f.get("warningCount", 0) for f in data)
        if errors:
            r.fail_gate(f"ESLint エラー {errors} 件")
        r.detail(f"ESLint の指摘 ({len(rows)} 件)", headers, rows)
        r.finish_slot(slot, "fail" if errors else ("warn" if warnings else "pass"),
                      f"エラー {errors} / 警告 {warnings} (対象 {len(data)} ファイル)",
                      {"issues": {"errors": errors, "warnings": warnings}})
    write_page(r.slot_dir(slot) / "index.html", f"ESLint ({pkg})",
               f"<h1>ESLint ({esc(pkg)})</h1><p>エラー {errors} / 警告 {warnings}</p>" + table_html(headers, rows))

    # ---- npm audit → fe-<pkg>-audit
    slot = f"fe-{pkg}-audit"
    audit = load_json(src / "npm-audit.json")
    order = ["critical", "high", "moderate", "low", "info"]
    headers = ["重大度", "パッケージ", "影響範囲", "内容", "修正"]
    rows, counts = [], {}
    if not audit or "metadata" not in audit:
        r.finish_slot(slot, "warn", "監査結果を取得できませんでした")
    else:
        counts = audit["metadata"].get("vulnerabilities", {})
        total = counts.get("total", sum(counts.get(k, 0) for k in order))
        for name, vul in audit.get("vulnerabilities", {}).items():
            titles = [x.get("title", "") for x in vul.get("via", []) if isinstance(x, dict)]
            via = "; ".join(titles) or "依存: " + ", ".join(x for x in vul.get("via", []) if isinstance(x, str))
            fix = vul.get("fixAvailable")
            fix_text = f"{fix.get('name')}@{fix.get('version')}" if isinstance(fix, dict) else ("あり" if fix else "なし")
            rows.append([vul.get("severity", ""), name, vul.get("range", ""), via, fix_text])
        rank = {k: i for i, k in enumerate(order)}
        rows.sort(key=lambda row: rank.get(row[0], 99))
        r.detail(f"npm audit の警告 ({len(rows)} パッケージ)", headers, rows)
        r.finish_slot(slot, "warn" if total else "pass",
                      f"合計 {total} 件 (" + " / ".join(f"{k} {counts.get(k, 0)}" for k in order[:4]) + ")",
                      {"vulnerabilities": {k: counts.get(k, 0) for k in order}})
    write_page(r.slot_dir(slot) / "index.html", f"npm audit ({pkg})",
               f"<h1>npm audit ({esc(pkg)})</h1><p>" + esc(" / ".join(f"{k}: {counts.get(k, 0)}" for k in order))
               + "</p>" + table_html(headers, rows))

    # ---- SLOCCount (cloc) → fe-<pkg>-sloc
    slot = f"fe-{pkg}-sloc"
    cloc = load_json(src / "cloc.json")
    if cloc is None:
        r.finish_slot(slot, "warn", "集計できませんでした")
        write_page(r.slot_dir(slot) / "index.html", "SLOCCount", "<h1>SLOCCount</h1><p>集計できませんでした</p>")
    else:
        langs = sorted(((k, v) for k, v in cloc.items() if k not in ("header", "SUM")),
                       key=lambda kv: -kv[1].get("code", 0))
        s = cloc.get("SUM", {})
        r.finish_slot(slot, "info",
                      f"{s.get('code', 0)} 行 / {s.get('nFiles', 0)} ファイル ("
                      + ", ".join(f"{k} {v.get('code', 0)}" for k, v in langs) + ")",
                      {"sloc": {"code": s.get("code", 0), "files": s.get("nFiles", 0)}})
        by_file = load_json(src / "cloc-by-file.json") or {}
        file_rows = sorted(([k, v.get("language", ""), v.get("blank", 0), v.get("comment", 0), v.get("code", 0)]
                            for k, v in by_file.items() if k not in ("header", "SUM")), key=lambda row: -row[4])
        write_page(r.slot_dir(slot) / "index.html", f"SLOCCount ({pkg})",
                   f"<h1>SLOCCount ({esc(pkg)})</h1><p class=\"muted\">cloc で集計</p><h2>言語別</h2>"
                   + table_html(["言語", "ファイル", "空行", "コメント", "コード"],
                                [[k, v.get("nFiles", 0), v.get("blank", 0), v.get("comment", 0), v.get("code", 0)]
                                 for k, v in langs])
                   + "<h2>ファイル別</h2>" + table_html(["ファイル", "言語", "空行", "コメント", "コード"], file_rows))

    r.write()
    return 0


# --------------------------------------------------------------------------- BE
def cmd_be(args) -> int:
    t = Path(args.target)
    module = t.parent  # be/
    r = JobReport("be", "⚙️ Backend (be)", args.out)

    # ---- JUnit → be-tests
    slot = "be-tests"
    files = sorted((t / "surefire-reports").glob("TEST-*.xml"))
    suites, rows = [], []
    total = failures = skipped = 0
    for f in files:
        s = parse_xml(f)
        if s is None:
            continue
        tests, fl, er, sk = (to_int(s.get(k)) for k in ("tests", "failures", "errors", "skipped"))
        total, failures, skipped = total + tests, failures + fl + er, skipped + sk
        suites.append([STATUS["fail" if fl + er else "pass"][0], s.get("name", f.stem), tests, fl + er, sk,
                       f"{to_float(s.get('time')):.2f}s"])
        for tc in s.iter("testcase"):
            for kind in ("failure", "error"):
                el = tc.find(kind)
                if el is None:
                    continue
                cls = tc.get("classname", "")
                msg = first_line(el.get("message") or el.text)
                file = (module / "src" / "test" / "java" / (cls.replace(".", "/") + ".java")).as_posix()
                m = re.search(rf"\({re.escape(cls.split('.')[-1])}\.java:(\d+)\)", el.text or "")
                line = m.group(1) if m else None
                rows.append([cls, tc.get("name", ""), kind, msg])
                r.annotate("error", msg, file, line, f"テスト失敗: {cls.split('.')[-1]}.{tc.get('name', '')}")
    if not files:
        status, headline = "fail", "テスト結果が生成されませんでした"
        r.fail_gate("JUnit 結果なし")
    else:
        status = "fail" if failures else "pass"
        headline = f"{total - failures - skipped}/{total} 成功 (失敗 {failures} / 省略 {skipped})"
        if failures:
            r.fail_gate(f"JUnit 失敗 {failures} 件")
    r.detail(f"失敗したテスト ({len(rows)} 件)", ["クラス", "テスト", "種別", "メッセージ"], rows)
    write_page(r.slot_dir(slot) / "index.html", "JUnit テスト結果",
               f"<h1>JUnit テスト結果</h1><p>{esc(headline)}</p>"
               + table_html(["", "クラス", "テスト数", "失敗", "省略", "時間"], suites)
               + "<h2>失敗したテスト</h2>" + table_html(["クラス", "テスト", "種別", "メッセージ"], rows))
    r.finish_slot(slot, status, headline,
                  {"tests": {"total": total, "passed": total - failures - skipped, "failed": failures,
                             "skipped": skipped}} if files else {})

    # ---- JaCoCo → be-jacoco
    slot = "be-jacoco"
    root = parse_xml(t / "site" / "jacoco" / "jacoco.xml")
    if root is None:
        r.finish_slot(slot, "warn", "カバレッジが生成されませんでした")
        write_page(r.slot_dir(slot) / "index.html", "JaCoCo", "<h1>JaCoCo</h1><p>生成されませんでした</p>")
    else:
        def counter(node, kind: str):
            for c in node.findall("counter"):
                if c.get("type") == kind:
                    missed, covered = to_int(c.get("missed")), to_int(c.get("covered"))
                    return pct(covered, missed + covered)
            return None

        copy_dir(t / "site" / "jacoco", r.slot_dir(slot))
        cov = {k.lower(): counter(root, k) for k in ("LINE", "BRANCH", "METHOD", "INSTRUCTION")}
        base = baseline_metric(args.baseline, slot, "coverage", "line")
        line = cov["line"] or 0.0
        r.finish_slot(slot, "pass" if line >= 80 else "warn",
                      f"Line {fmt_pct(cov['line'])}{fmt_diff(cov['line'], base)} / Branch {fmt_pct(cov['branch'])}"
                      f" / Method {fmt_pct(cov['method'])}",
                      {"coverage": cov})
        cls_rows = [[c.get("name", "").replace("/", "."), fmt_pct(counter(c, "LINE")), fmt_pct(counter(c, "BRANCH"))]
                    for p in root.findall("package") for c in p.findall("class")]
        cls_rows.sort(key=lambda row: to_float(row[1].rstrip("%"), 0))
        r.detail(f"クラス別カバレッジ (低い順, {len(cls_rows)} クラス)", ["クラス", "Line", "Branch"], cls_rows)

    # ---- Javadoc → be-javadoc
    slot = "be-javadoc"
    log_path = t / "javadoc.log"
    log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    pattern = re.compile(r"([^\s\[\]]+\.java):(\d+): (warning|error):?\s*(.*)")
    found = {}
    for raw in log.splitlines():
        m = pattern.search(raw)
        if m:
            found[(rel(m.group(1)), m.group(2), m.group(3), m.group(4))] = None
    jd_rows = [list(k) for k in found]
    jd_warn = sum(1 for k in found if k[2] == "warning")
    jd_err = len(found) - jd_warn
    apidocs = next(iter(sorted(t.glob("**/apidocs/index.html"))), None)
    if apidocs is None:
        r.finish_slot(slot, "fail", f"生成に失敗しました (エラー {jd_err})")
        r.fail_gate("Javadoc 生成失敗")
        write_page(r.slot_dir(slot) / "index.html", "Javadoc", "<h1>Javadoc</h1><p>生成に失敗しました</p>")
    else:
        copy_dir(apidocs.parent, r.slot_dir(slot))
        r.finish_slot(slot, "warn" if found else "pass", f"生成成功 / 警告 {jd_warn} / エラー {jd_err}",
                      {"issues": {"errors": jd_err, "warnings": jd_warn}})
    r.detail(f"Javadoc の警告 ({len(jd_rows)} 件)", ["ファイル", "行", "種別", "メッセージ"], jd_rows)

    # ---- Checkstyle → be-checkstyle
    slot = "be-checkstyle"
    root = parse_xml(t / "checkstyle-result.xml")
    headers = ["ファイル", "行", "重大度", "ルール", "メッセージ"]
    rows = []
    if root is None:
        r.finish_slot(slot, "warn", "レポートが生成されませんでした")
    else:
        for f in root.findall("file"):
            name = rel(f.get("name", ""))
            for e in f.findall("error"):
                rule = (e.get("source") or "").split(".")[-1].removesuffix("Check")
                rows.append([name, e.get("line", "-"), e.get("severity", ""), rule, e.get("message", "")])
                if e.get("severity") == "error":
                    r.annotate("error", e.get("message", ""), name, e.get("line"), f"Checkstyle {rule}")
        errs = sum(1 for row in rows if row[2] == "error")
        if errs:
            r.fail_gate(f"Checkstyle エラー {errs} 件")
        r.detail(f"Checkstyle の指摘 ({len(rows)} 件)", headers, rows)
        r.finish_slot(slot, "fail" if errs else ("warn" if rows else "pass"),
                      f"エラー {errs} / 警告 {len(rows) - errs} (対象 {len(root.findall('file'))} ファイル)",
                      {"issues": {"errors": errs, "warnings": len(rows) - errs}})
    write_page(r.slot_dir(slot) / "index.html", "Checkstyle",
               f"<h1>Checkstyle</h1><p>指摘 {len(rows)} 件</p>" + table_html(headers, rows))

    # ---- SpotBugs → be-spotbugs
    slot = "be-spotbugs"
    root = parse_xml(t / "spotbugsXml.xml")
    headers = ["優先度", "カテゴリ", "種別", "クラス", "行", "内容"]
    rows = []
    counts = {"High": 0, "Medium": 0, "Low": 0}
    if root is None:
        r.finish_slot(slot, "warn", "レポートが生成されませんでした")
    else:
        prio = {"1": "High", "2": "Medium", "3": "Low"}
        for bug in root.findall("BugInstance"):
            cls = bug.find("Class")
            src_line = bug.find("SourceLine")
            rows.append([prio.get(bug.get("priority", ""), bug.get("priority", "")), bug.get("category", ""),
                         bug.get("type", ""), cls.get("classname", "") if cls is not None else "",
                         src_line.get("start", "-") if src_line is not None else "-",
                         bug.findtext("ShortMessage") or bug.findtext("LongMessage") or ""])
        rank = {"High": 0, "Medium": 1, "Low": 2}
        rows.sort(key=lambda row: rank.get(row[0], 9))
        counts = {p: sum(1 for row in rows if row[0] == p) for p in counts}
        if counts["High"]:
            r.fail_gate(f"SpotBugs High {counts['High']} 件")
        r.detail(f"SpotBugs の指摘 ({len(rows)} 件)", headers, rows)
        r.finish_slot(slot, "fail" if counts["High"] else ("warn" if rows else "pass"),
                      f"合計 {len(rows)} 件 (High {counts['High']} / Medium {counts['Medium']} / Low {counts['Low']})",
                      {"issues": {"errors": counts["High"], "warnings": counts["Medium"] + counts["Low"]}})
    write_page(r.slot_dir(slot) / "index.html", "SpotBugs",
               "<h1>SpotBugs</h1><p>" + esc(" / ".join(f"{k}: {v}" for k, v in counts.items())) + "</p>"
               + table_html(headers, rows))

    r.write()
    return 0


# --------------------------------------------------------------------------- Docs
def cmd_docs(args) -> int:
    build = Path(args.build)
    r = JobReport("docs", "📚 Docs (Docusaurus)", args.out)
    if args.outcome == "success" and (build / "index.html").exists():
        copy_dir(build, r.slot_dir("docs"))
        pages = sum(1 for p in build.rglob("index.html") if "assets" not in p.parts)
        r.finish_slot("docs", "pass", f"ビルド成功 ({pages} ページ)", {"pages": pages})
    else:
        r.finish_slot("docs", "fail", "ビルドに失敗しました (リンク切れ等)")
        r.fail_gate("Docusaurus ビルド失敗")
        write_page(r.slot_dir("docs") / "index.html", "Docs", "<h1>Docs</h1><p>ビルドに失敗しました</p>")
    r.write()
    return 0


# --------------------------------------------------------------------------- PR コメント
def load_jobs(summaries: str) -> tuple[list[dict], list[str]]:
    jobs, failures = [], []
    for p in sorted(Path(summaries).rglob("*.json")):
        data = load_json(p) or {}
        if "rows" not in data:
            continue
        jobs.append(data)
        failures += [f"{data.get('job', p.stem)}: {g}" for g in data.get("gate_failures", [])]
    return jobs, failures


REPORT_CSS = """
header{border-bottom:1px solid var(--border);padding-bottom:10px;margin-bottom:16px}
header h1{margin:0 0 6px}
.meta{display:flex;flex-wrap:wrap;gap:2px 16px;font-size:13px;color:var(--muted)}
.banner{padding:10px 14px;border-radius:8px;border:1px solid var(--border);background:var(--card);margin:12px 0;font-weight:600}
nav.toc{display:flex;flex-wrap:wrap;gap:6px;margin:12px 0}
nav.toc a{border:1px solid var(--border);border-radius:6px;padding:2px 10px;text-decoration:none;font-size:13px}
section.job{margin:28px 0}
section.job h2{font-size:18px;border-left:4px solid var(--link);padding-left:8px}
details{margin:10px 0;border:1px solid var(--border);border-radius:8px;padding:6px 12px}
details>summary{cursor:pointer;font-weight:600}
details[open]>summary{margin-bottom:6px}
td.st{white-space:nowrap;text-align:center}
ul.arts{padding-left:20px}
footer{margin-top:32px;font-size:12px;color:var(--muted)}
"""


def cmd_report_html(args) -> int:
    """全ジョブの結果を 1 ファイルの HTML にまとめる (外部ファイル・相対リンクを使わない自己完結の HTML)."""
    ctx = run_context()
    jobs, failures = load_jobs(args.summaries)
    pr = os.environ.get("PR_NUMBER", "")
    pr_title = os.environ.get("PR_TITLE", "")
    pr_url = f"{ctx['server']}/{ctx['repo']}/pull/{pr}" if pr else ""
    artifacts = load_json(Path(args.artifacts)) if args.artifacts else []

    gate_cls = "s-fail" if failures else "s-pass"
    gate = (f'<div class="banner {gate_cls}">'
            + (f'❌ 品質ゲート: 不合格 — {esc(" / ".join(failures))}' if failures else "✅ 品質ゲート: 合格")
            + "</div>")
    toc = '<nav class="toc">' + "".join(
        f'<a href="#job-{esc(j["job"])}">{esc(j.get("title", j["job"]))}</a>' for j in jobs) + "</nav>"

    sections = []
    for j in jobs:
        rows = "".join(f'<tr><td>{esc(r["name"])}</td><td class="st">{STATUS[r["status"]][0]} {esc(STATUS[r["status"]][1])}'
                       f'</td><td>{esc(r["result"])}</td></tr>' for r in j["rows"])
        body = ('<div class="wrap"><table><thead><tr><th>チェック</th><th>状態</th><th>結果</th></tr></thead>'
                f"<tbody>{rows}</tbody></table></div>")
        if j.get("gate_failures"):
            body += f'<p class="s-fail">品質ゲート不合格: {esc(" / ".join(j["gate_failures"]))}</p>'
        for d in j.get("details", []):
            # 失敗したテストの一覧は最初から開いておく
            is_open = " open" if "失敗" in d["summary"] else ""
            body += (f"<details{is_open}><summary>{esc(d['summary'])}</summary>"
                     + table_html(d["headers"], d["rows"]) + "</details>")
        sections.append(f'<section class="job" id="job-{esc(j["job"])}"><h2>{esc(j.get("title", j["job"]))}</h2>'
                        f"{body}</section>")
    if not sections:
        sections.append('<p class="muted">実行されたジョブがありません (変更のなかったプロジェクトは実行されません)。</p>')

    art_html = ""
    if artifacts:
        items = "".join(f'<li><a href="{esc(a["url"])}">{esc(a["name"])}</a> <span class="muted">'
                        f'({a.get("size", 0) / 1024:.0f} KB)</span></li>'
                        for a in artifacts if a["name"].startswith("pages-"))
        art_html = ("<section><h2>HTML レポート一式 (zip)</h2><p class=\"muted\">JaCoCo・Javadoc・Vitest・カバレッジ・"
                    "Storybook など複数ファイルのレポートは zip でダウンロードし、展開して開いてください"
                    "(Vitest・Storybook は <code>npx http-server &lt;展開先&gt;</code> などでローカル配信が必要)。</p>"
                    f'<ul class="arts">{items}</ul></section>')

    title = f"CI レポート PR #{pr}" if pr else "CI レポート"
    meta = []
    if pr:
        meta.append(f'<span><a href="{esc(pr_url)}">PR #{esc(pr)}</a> {esc(pr_title)}</span>')
    meta.append(f"<span>ブランチ {esc(ctx['ref'])}</span>")
    if ctx["commit"]:
        meta.append(f'<span>コミット <a href="{esc(ctx["server"])}/{esc(ctx["repo"])}/commit/{esc(ctx["commit"])}">'
                    f"<code>{esc(ctx['commit'][:7])}</code></a></span>")
    if ctx["run_url"]:
        meta.append(f'<span><a href="{esc(ctx["run_url"])}">CI 実行 (ジョブサマリ・Artifacts)</a></span>')
    meta.append(f"<span>生成 {esc(fmt_jst(now_iso()))} JST</span>")

    html_text = ('<!doctype html><html lang="ja"><head><meta charset="utf-8">'
                 '<meta name="viewport" content="width=device-width, initial-scale=1">'
                 f"<title>{esc(title)}</title><style>{BASE_CSS}{REPORT_CSS}</style></head><body><main>"
                 f'<header><h1>{esc(title)}</h1><div class="meta">{"".join(meta)}</div></header>'
                 + gate + toc + "".join(sections) + art_html
                 + "<footer>このファイルは CI が自動生成した 1 ファイル完結の HTML です。"
                   "変更のなかったプロジェクトのジョブは実行されないため、ここには載りません。</footer>"
                 + "</main></body></html>")
    Path(args.out).write_text(html_text, encoding="utf-8")
    return 0


def cmd_comment(args) -> int:
    """PR コメントは要約 (1 チェック 1 行) と、1 ファイル HTML レポートへのリンクだけにする."""
    ctx = run_context()
    jobs, failures = load_jobs(args.summaries)
    gate = ("✅ **品質ゲート: 合格**" if not failures
            else "❌ **品質ゲート: 不合格** — " + " / ".join(md_cell(f) for f in failures))
    lines = ["<!-- ci-report -->", "## 📊 CI レポート", "", gate, ""]
    if args.report_url:
        lines += [f"### 📄 [CI レポートを開く]({args.report_url})", "",
                  "テストの失敗・ファイル別カバレッジ・指摘の一覧など、すべての詳細はこのページで見られます"
                  " (この CI 実行の Artifact `ci-report.html`。GitHub にログインした状態で開いてください。保持 14 日)。", ""]
    lines += ["| 対象 | チェック | 状態 | 結果 |", "|---|---|:---:|---|"]
    for job in jobs:
        for row in job["rows"]:
            lines.append(f"| {md_cell(job.get('job', ''))} | {md_cell(row['name'])} | {STATUS[row['status']][0]} "
                         f"| {md_cell(row['result'])} |")
    if not jobs:
        lines.append("| - | 実行されたジョブがありません | - | - |")
    footer = f"コミット `{ctx['commit'][:7]}` ・ [CI 実行 (ジョブサマリ・Artifacts)]({ctx['run_url']})"
    if args.pages_url:
        footer += f" ・ [develop の品質レポート (Pages)]({args.pages_url})"
    lines += ["", footer, "",
              "<sub>変更のなかったプロジェクトのジョブは実行されません。このコメントは push のたびに上書きされます。</sub>"]
    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


# --------------------------------------------------------------------------- 品質ゲート
def cmd_gate(args) -> int:
    data = load_json(Path(args.summary))
    if data is None:
        print(f"::error::{args.summary} がありません")
        return 1
    for g in data.get("gate_failures", []):
        print(f"::error title=品質ゲート::{data.get('job')}: {g}")
    if data.get("gate_failures"):
        return 1
    print(f"{data.get('job')}: 品質ゲート合格")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("fe")
    p.add_argument("--package", required=True)
    p.add_argument("--reports", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--baseline")
    p.set_defaults(func=cmd_fe)

    p = sub.add_parser("be")
    p.add_argument("--target", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--baseline")
    p.set_defaults(func=cmd_be)

    p = sub.add_parser("docs")
    p.add_argument("--outcome", required=True)
    p.add_argument("--build", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_docs)

    p = sub.add_parser("report-html")
    p.add_argument("--summaries", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--artifacts", default="")
    p.set_defaults(func=cmd_report_html)

    p = sub.add_parser("comment")
    p.add_argument("--summaries", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--report-url", default="")
    p.add_argument("--pages-url", default="")
    p.set_defaults(func=cmd_comment)

    p = sub.add_parser("gate")
    p.add_argument("summary")
    p.set_defaults(func=cmd_gate)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
