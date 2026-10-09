#!/usr/bin/env python3
"""CI の各ツールの出力を集計し、レポートの画面・Pages の枠・ジョブサマリ・注釈・PR コメントを作る.

Usage:
  ci_report.py fe   --package <pkg> --reports <fe/reports> --out <out> [--baseline <dir>]
  ci_report.py be   --target <be/target> --out <out> [--baseline <dir>]
  ci_report.py docs --outcome <success|failure> --build <docs/build> --out <out>
  ci_report.py report-html --summaries <dir> --out <ci-report.html> [--artifacts <artifacts.json>]
  ci_report.py comment --summaries <dir> --out <comment.md> [--artifacts <artifacts.json>] [--report-url <url>]
                       [--pages-url <url>]
  ci_report.py gate <out>/summary/<job>.json

出力 (<out> 配下):
  report/<画面>.html            チェックごとの画面 (1 ファイル完結の HTML)。圧縮せずに Artifact に上げると
                                (upload-artifact の archive: false) リンクからブラウザでそのまま開ける
  pages/<枠>/                   Pages の枠 (index.html を含む)。Artifact pages-<枠> (zip) として上げる
  pages/<枠>/_pages/summary.json   Pages の索引用の要約。Pages の組み立て時に取り除く
  summary/<job>.md / .json      ジョブの要約 (ジョブサマリ・PR コメント・品質ゲート用)
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
MAX_TRACE = 4000
REPO_ROOT = Path.cwd().resolve()
ANSI = re.compile(r"\x1b\[[0-9;]*m")


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


def read_lines(path: Path) -> list[str] | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None


def status_cell(status: str) -> str:
    icon, label = STATUS[status]
    return f'<span class="s-{status}">{icon} {esc(label)}</span>'


# --------------------------------------------------------------------------- 画面の部品
VIEW_CSS = """
header.view{border-bottom:1px solid var(--border);padding-bottom:10px;margin-bottom:16px}
header.view h1{margin:0 0 6px}
.meta{display:flex;flex-wrap:wrap;gap:2px 16px;font-size:13px;color:var(--muted)}
.lead{font-size:15px;font-weight:600;margin:8px 0 16px}
h2{margin-top:24px}
details{margin:8px 0;border:1px solid var(--border);border-radius:8px;padding:6px 12px}
details>summary{cursor:pointer;font-weight:600}
details[open]>summary{margin-bottom:6px}
pre.trace{white-space:pre-wrap;overflow-wrap:anywhere;font:12px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace;
background:var(--card);border:1px solid var(--border);border-radius:6px;padding:8px;margin:6px 0}
:root{--cov-hit:#dafbe1;--cov-part:#fff8c5;--cov-miss:#ffebe9}
@media (prefers-color-scheme: dark){:root{--cov-hit:#12261e;--cov-part:#2e2a12;--cov-miss:#3a1d1f}}
.src{font:12px/1.55 ui-monospace,SFMono-Regular,Consolas,monospace;border:1px solid var(--border);border-radius:6px;
overflow-x:auto;margin:6px 0}
.src div{white-space:pre;padding-right:12px;min-width:max-content}
.src .ln{display:inline-block;width:4.5em;text-align:right;color:var(--muted);padding-right:12px;user-select:none}
.src .c{background:var(--cov-hit)}.src .p{background:var(--cov-part)}.src .m{background:var(--cov-miss)}
.legend span{display:inline-block;padding:0 8px;margin-right:6px;border-radius:4px;font-size:12px}
.legend .c{background:var(--cov-hit)}.legend .p{background:var(--cov-part)}.legend .m{background:var(--cov-miss)}
.bar{display:inline-block;width:80px;height:8px;border-radius:4px;background:var(--cov-miss);vertical-align:middle;
margin-right:6px;overflow:hidden}
.bar i{display:block;height:100%;background:var(--pass)}
"""

COVERAGE_LEGEND = ('<p class="legend"><span class="c">実行済み</span><span class="p">分岐の一部が未実行</span>'
                   '<span class="m">未実行</span></p>')


def bar(value) -> str:
    v = value if isinstance(value, (int, float)) else 0
    return f'<span class="bar"><i style="width:{max(0, min(100, v)):.0f}%"></i></span>{esc(fmt_pct(value))}'


def source_html(lines: list[str], marks: dict[int, tuple[str, str]]) -> str:
    """ソースを行番号付きで表示し、行ごとの網羅状況で色を付ける. marks: 行番号 → (c|p|m, ツールチップ)."""
    out = []
    for i, text in enumerate(lines, 1):
        cls, tip = marks.get(i, ("", ""))
        attrs = (f' class="{cls}"' if cls else "") + (f' title="{esc(tip)}"' if tip else "")
        out.append(f'<div{attrs}><span class="ln">{i}</span>{esc(text)}</div>')
    return '<div class="src">' + "".join(out) + "</div>"


# --------------------------------------------------------------------------- 集計の器
class JobReport:
    def __init__(self, job: str, title: str, out: str):
        self.job = job
        self.title = title
        self.out = Path(out)
        self.ctx = run_context()
        self.rows: list[dict] = []
        self.details: list[tuple[str, list, list]] = []
        self.gate_failures: list[str] = []
        self.annotations: dict[str, list[str]] = {"error": [], "warning": []}

    # ---- 枠 (Pages)
    def slot_dir(self, slot: str) -> Path:
        d = self.out / "pages" / slot
        d.mkdir(parents=True, exist_ok=True)
        return d

    def finish_slot(self, slot: str, status: str, headline: str, metrics: dict | None = None,
                    links: list[dict] | None = None, views: list[tuple[str, str]] | None = None,
                    zip_label: str | None = None) -> None:
        """枠の結果を確定する.

        views      PR コメントからリンクする画面 [(表示名, report/ 配下のファイル名)]
        zip_label  画面にできない (複数ファイルの) レポートを zip でリンクするときの表示名
        """
        title = catalog_by_id().get(slot, {}).get("title", slot)
        self.rows.append({"name": title, "status": status, "result": headline, "slot": slot,
                          "views": [{"label": label, "file": file} for label, file in (views or [])
                                    if (self.out / "report" / file).exists()],
                          "zip": {"label": zip_label, "artifact": f"pages-{slot}"} if zip_label else None})
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

    # ---- 画面 (PR からリンクする 1 ファイル完結の HTML)
    def view(self, file: str, title: str, lead: str, body: str, slot_page: str | None = None) -> str:
        """report/<file> に画面を書く. slot_page を指定すると同じ内容を Pages の枠の index.html にも書く."""
        ctx = self.ctx
        meta = [f"<span>{esc(self.title)}</span>"]
        if ctx["ref"]:
            meta.append(f"<span>ブランチ {esc(ctx['ref'])}</span>")
        if ctx["commit"]:
            meta.append(f'<span>コミット <a href="{esc(ctx["server"])}/{esc(ctx["repo"])}/commit/{esc(ctx["commit"])}">'
                        f"<code>{esc(ctx['commit'][:7])}</code></a></span>")
        if ctx["run_url"]:
            meta.append(f'<span><a href="{esc(ctx["run_url"])}">CI 実行</a></span>')
        meta.append(f"<span>生成 {esc(fmt_jst(now_iso()))} JST</span>")
        content = (f'<header class="view"><h1>{esc(title)}</h1><div class="meta">{"".join(meta)}</div></header>'
                   f'<p class="lead">{esc(lead)}</p>{body}')
        write_page(self.out / "report" / file, title, content, VIEW_CSS)
        if slot_page:
            write_page(self.slot_dir(slot_page) / "index.html", title, content, VIEW_CSS)
        return file

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
        for row in self.rows:
            lines.append(f"| {md_cell(row['name'])} | {STATUS[row['status']][0]} | {md_cell(row['result'])} |")
        if self.gate_failures:
            lines += ["", "**品質ゲート不合格:** " + " / ".join(md_cell(g) for g in self.gate_failures)]
        for summary, headers, rows in self.details:
            lines += ["", "<details>", f"<summary>{esc(summary)}</summary>", ""]
            lines.append("| " + " | ".join(md_cell(h) for h in headers) + " |")
            lines.append("|" + "---|" * len(headers))
            lines += ["| " + " | ".join(md_cell(c) for c in row) + " |" for row in rows[:MAX_ROWS]]
            if len(rows) > MAX_ROWS:
                lines += ["", f"…他 {len(rows) - MAX_ROWS} 件 (PR コメントの各画面を参照)"]
            lines += ["", "</details>"]
        lines.append("")
        text = "\n".join(lines)

        summary_dir = self.out / "summary"
        summary_dir.mkdir(parents=True, exist_ok=True)
        (summary_dir / f"{self.job}.md").write_text(text, encoding="utf-8")
        write_json(summary_dir / f"{self.job}.json", {
            "job": self.job, "title": self.title, "gate_failures": self.gate_failures,
            "rows": self.rows,
            # 全体の 1 ファイル HTML (ci-report.html) に全件を載せるため、指摘の一覧も省略せずに残す
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
def fe_tests_body(res: dict) -> str:
    files, failed_html = [], []
    for tr in res.get("testResults", []):
        file = rel(tr.get("name", ""))
        asserts = tr.get("assertionResults", [])
        n_fail = sum(1 for a in asserts if a.get("status") == "failed")
        n_skip = sum(1 for a in asserts if a.get("status") in ("pending", "skipped", "todo"))
        dur = to_float(tr.get("endTime")) - to_float(tr.get("startTime"))
        st = "fail" if n_fail or tr.get("status") == "failed" else "pass"
        items = "".join(
            f'<tr><td>{status_cell("fail" if a.get("status") == "failed" else ("skip" if a.get("status") in ("pending", "skipped", "todo") else "pass"))}</td>'
            f'<td>{esc(a.get("fullName", ""))}</td><td>{to_float(a.get("duration")):.0f} ms</td></tr>' for a in asserts)
        files.append(f'<details{" open" if st == "fail" else ""}><summary>{STATUS[st][0]} {esc(file)} '
                     f'<span class="muted">({len(asserts)} 件 / 失敗 {n_fail} / 省略 {n_skip} / {dur:.0f} ms)</span></summary>'
                     f'<div class="wrap"><table><thead><tr><th>状態</th><th>テスト</th><th>時間</th></tr></thead>'
                     f'<tbody>{items}</tbody></table></div></details>')
        for a in asserts:
            if a.get("status") == "failed":
                msg = ANSI.sub("", "\n\n".join(a.get("failureMessages") or []))[:MAX_TRACE]
                loc = (a.get("location") or {}).get("line")
                failed_html.append(f'<h3>{esc(a.get("fullName", ""))}</h3><p class="muted">{esc(file)}'
                                   f'{":" + str(loc) if loc else ""}</p><pre class="trace">{esc(msg)}</pre>')
        if tr.get("status") == "failed" and not asserts:
            failed_html.append(f'<h3>{esc(file)} (読み込み失敗)</h3>'
                               f'<pre class="trace">{esc(ANSI.sub("", tr.get("message") or "")[:MAX_TRACE])}</pre>')
    body = ""
    if failed_html:
        body += "<h2>失敗したテスト</h2>" + "".join(failed_html)
    body += "<h2>テストファイル別</h2>" + "".join(files)
    return body


def fe_coverage_body(summary: dict, final: dict | None) -> str:
    t = summary.get("total", {})
    total_rows = "".join(f'<tr><td>{label}</td><td>{bar(t.get(k, {}).get("pct"))}</td>'
                         f'<td>{t.get(k, {}).get("covered", 0)} / {t.get(k, {}).get("total", 0)}</td></tr>'
                         for label, k in (("Lines", "lines"), ("Statements", "statements"),
                                          ("Functions", "functions"), ("Branches", "branches")))
    body = ('<h2>全体</h2><div class="wrap"><table><thead><tr><th>指標</th><th>率</th><th>網羅 / 全体</th></tr></thead>'
            f"<tbody>{total_rows}</tbody></table></div>")
    files = sorted(((rel(k), v) for k, v in summary.items() if k != "total"),
                   key=lambda kv: to_float(kv[1]["lines"]["pct"], 0))
    body += ('<h2>ファイル別 (低い順)</h2><div class="wrap"><table><thead><tr><th>ファイル</th><th>Lines</th>'
             "<th>Branches</th><th>Functions</th></tr></thead><tbody>"
             + "".join(f'<tr><td><a href="#src-{i}">{esc(f)}</a></td><td>{bar(v["lines"]["pct"])}</td>'
                       f'<td>{bar(v["branches"]["pct"])}</td><td>{bar(v["functions"]["pct"])}</td></tr>'
                       for i, (f, v) in enumerate(files))
             + "</tbody></table></div>")
    if final:
        body += "<h2>ソース</h2>" + COVERAGE_LEGEND
        for i, (f, v) in enumerate(files):
            fc = next((c for k, c in final.items() if rel(k) == f), None)
            lines = read_lines(REPO_ROOT / f)
            if fc is None or lines is None:
                continue
            hits: dict[int, list[int]] = {}
            for sid, loc in fc.get("statementMap", {}).items():
                hits.setdefault(loc["start"]["line"], []).append(fc.get("s", {}).get(sid, 0))
            partial: dict[int, str] = {}
            for bid, br in fc.get("branchMap", {}).items():
                counts = fc.get("b", {}).get(bid, [])
                line_no = (br.get("loc") or {}).get("start", {}).get("line") or br.get("line")
                if counts and any(c == 0 for c in counts) and any(c > 0 for c in counts) and line_no:
                    partial[line_no] = f"分岐 {sum(1 for c in counts if c > 0)}/{len(counts)}"
            marks = {}
            for ln, hs in hits.items():
                if all(h == 0 for h in hs):
                    marks[ln] = ("m", "未実行")
                elif ln in partial or any(h == 0 for h in hs):
                    marks[ln] = ("p", partial.get(ln, "一部未実行"))
                else:
                    marks[ln] = ("c", f"{max(hs)} 回実行")
            pct_v = v["lines"]["pct"]
            body += (f'<details id="src-{i}"{" open" if to_float(pct_v, 100) < 100 else ""}><summary>{esc(f)} '
                     f'<span class="muted">Lines {esc(fmt_pct(pct_v))}</span></summary>'
                     + source_html(lines, marks) + "</details>")
    return body


def cmd_fe(args) -> int:
    pkg = args.package
    src = Path(args.reports)
    r = JobReport(f"fe-{pkg}", f"🖥️ Frontend ({pkg})", args.out)

    # ---- Vitest + カバレッジ → fe-<pkg>-vitest (画面はテスト結果とカバレッジの 2 つ)
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
                    msg = ANSI.sub("", first_line((a.get("failureMessages") or [""])[0]))
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
        r.view(f"fe-{pkg}-tests.html", f"テスト結果 (Vitest) — {pkg}", headline, fe_tests_body(res))
    if cov:
        t = cov.get("total", {})
        metrics["coverage"] = {k: t.get(k, {}).get("pct") for k in ("lines", "statements", "functions", "branches")}
        lines_pct = metrics["coverage"]["lines"]
        base = baseline_metric(args.baseline, slot, "coverage", "lines")
        cov_head = f"Lines {fmt_pct(lines_pct)}{fmt_diff(lines_pct, base)}"
        headline += f" / {cov_head}"
        cov_rows = sorted(([rel(k), fmt_pct(v["lines"]["pct"]), fmt_pct(v["branches"]["pct"]),
                            fmt_pct(v["functions"]["pct"])] for k, v in cov.items() if k != "total"),
                          key=lambda row: to_float(row[1].rstrip("%"), 0))
        r.detail(f"ファイル別カバレッジ (低い順, {len(cov_rows)} ファイル)", ["ファイル", "Lines", "Branches", "Functions"],
                 cov_rows)
        r.view(f"fe-{pkg}-coverage.html", f"カバレッジ (Vitest) — {pkg}", cov_head,
               fe_coverage_body(cov, load_json(src / "coverage" / "coverage-final.json")))
    if not has_html:
        write_page(d / "index.html", f"Vitest ({pkg})",
                   f"<h1>Vitest ({esc(pkg)})</h1><p>{esc(headline)}</p>"
                   + ('<p><a href="coverage/">カバレッジ</a></p>' if has_cov else ""))
    r.finish_slot(slot, status, headline, metrics,
                  [{"label": "カバレッジ", "href": "coverage/"}] if has_cov else [],
                  views=[("テスト結果", f"fe-{pkg}-tests.html"), ("カバレッジ", f"fe-{pkg}-coverage.html")])

    # ---- Storybook → fe-<pkg>-storybook (複数ファイルのため zip)
    slot = f"fe-{pkg}-storybook"
    idx = load_json(src / "storybook" / "index.json")
    if idx is None:
        r.fail_gate("Storybook ビルド失敗")
        write_page(r.slot_dir(slot) / "index.html", "Storybook", "<h1>Storybook</h1><p>ビルドに失敗しました</p>")
        r.finish_slot(slot, "fail", "ビルドに失敗しました")
    else:
        copy_dir(src / "storybook", r.slot_dir(slot))
        stories = [e for e in idx.get("entries", {}).values() if e.get("type") == "story"]
        comps = {e.get("title") for e in stories}
        r.finish_slot(slot, "pass", f"ビルド成功: {len(comps)} コンポーネント / {len(stories)} ストーリー",
                      {"stories": len(stories), "components": len(comps)}, zip_label="Storybook (zip)")

    # ---- ESLint → fe-<pkg>-eslint
    slot = f"fe-{pkg}-eslint"
    data = load_json(src / "eslint.json")
    headers = ["ファイル", "行", "重大度", "ルール", "メッセージ"]
    rows, errors, warnings = [], 0, 0
    if data is None:
        r.fail_gate("ESLint レポートなし")
        status, headline, metrics = "fail", "レポートが生成されませんでした", {}
    else:
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
        status = "fail" if errors else ("warn" if warnings else "pass")
        headline = f"エラー {errors} / 警告 {warnings} (対象 {len(data)} ファイル)"
        metrics = {"issues": {"errors": errors, "warnings": warnings}}
    r.view(f"fe-{pkg}-eslint.html", f"ESLint — {pkg}", headline, table_html(headers, rows), slot_page=slot)
    r.finish_slot(slot, status, headline, metrics, views=[("指摘一覧", f"fe-{pkg}-eslint.html")])

    # ---- npm audit → fe-<pkg>-audit
    slot = f"fe-{pkg}-audit"
    audit = load_json(src / "npm-audit.json")
    order = ["critical", "high", "moderate", "low", "info"]
    headers = ["重大度", "パッケージ", "影響範囲", "内容", "修正"]
    rows, counts = [], {}
    if not audit or "metadata" not in audit:
        status, headline, metrics = "warn", "監査結果を取得できませんでした", {}
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
        status = "warn" if total else "pass"
        headline = f"合計 {total} 件 (" + " / ".join(f"{k} {counts.get(k, 0)}" for k in order[:4]) + ")"
        metrics = {"vulnerabilities": {k: counts.get(k, 0) for k in order}}
    r.view(f"fe-{pkg}-audit.html", f"npm audit — {pkg}", headline, table_html(headers, rows), slot_page=slot)
    r.finish_slot(slot, status, headline, metrics, views=[("警告一覧", f"fe-{pkg}-audit.html")])

    # ---- SLOCCount (cloc) → fe-<pkg>-sloc
    slot = f"fe-{pkg}-sloc"
    cloc = load_json(src / "cloc.json")
    if cloc is None:
        status, headline, metrics, body = "warn", "集計できませんでした", {}, ""
    else:
        langs = sorted(((k, v) for k, v in cloc.items() if k not in ("header", "SUM")),
                       key=lambda kv: -kv[1].get("code", 0))
        s = cloc.get("SUM", {})
        status = "info"
        headline = (f"{s.get('code', 0)} 行 / {s.get('nFiles', 0)} ファイル ("
                    + ", ".join(f"{k} {v.get('code', 0)}" for k, v in langs) + ")")
        metrics = {"sloc": {"code": s.get("code", 0), "files": s.get("nFiles", 0)}}
        by_file = load_json(src / "cloc-by-file.json") or {}
        file_rows = sorted(([k, v.get("language", ""), v.get("blank", 0), v.get("comment", 0), v.get("code", 0)]
                            for k, v in by_file.items() if k not in ("header", "SUM")), key=lambda row: -row[4])
        body = ('<p class="muted">cloc で集計</p><h2>言語別</h2>'
                + table_html(["言語", "ファイル", "空行", "コメント", "コード"],
                             [[k, v.get("nFiles", 0), v.get("blank", 0), v.get("comment", 0), v.get("code", 0)]
                              for k, v in langs])
                + "<h2>ファイル別</h2>" + table_html(["ファイル", "言語", "空行", "コメント", "コード"], file_rows))
    r.view(f"fe-{pkg}-sloc.html", f"SLOCCount — {pkg}", headline, body, slot_page=slot)
    r.finish_slot(slot, status, headline, metrics, views=[("集計", f"fe-{pkg}-sloc.html")])

    r.write()
    return 0


# --------------------------------------------------------------------------- BE
def jacoco_counter(node, kind: str):
    for c in node.findall("counter"):
        if c.get("type") == kind:
            missed, covered = to_int(c.get("missed")), to_int(c.get("covered"))
            return pct(covered, missed + covered), covered, missed + covered
    return None, 0, 0


def jacoco_body(root, module: Path) -> str:
    total_rows = "".join(
        f"<tr><td>{label}</td><td>{bar(jacoco_counter(root, k)[0])}</td>"
        f"<td>{jacoco_counter(root, k)[1]} / {jacoco_counter(root, k)[2]}</td></tr>"
        for label, k in (("Line", "LINE"), ("Branch", "BRANCH"), ("Method", "METHOD"),
                         ("Instruction", "INSTRUCTION"), ("Class", "CLASS")))
    body = ('<h2>全体</h2><div class="wrap"><table><thead><tr><th>指標</th><th>率</th><th>網羅 / 全体</th></tr></thead>'
            f"<tbody>{total_rows}</tbody></table></div>")

    files = []
    for pkg in root.findall("package"):
        for sf in pkg.findall("sourcefile"):
            files.append((pkg.get("name", ""), sf))
    files.sort(key=lambda x: jacoco_counter(x[1], "LINE")[0] if jacoco_counter(x[1], "LINE")[0] is not None else 100)

    classes = []
    for pkg in root.findall("package"):
        for c in pkg.findall("class"):
            missed_lines = jacoco_counter(c, "LINE")[2] - jacoco_counter(c, "LINE")[1]
            classes.append((c.get("name", "").replace("/", "."), jacoco_counter(c, "LINE")[0],
                            jacoco_counter(c, "BRANCH")[0], jacoco_counter(c, "METHOD")[0], missed_lines,
                            c.get("sourcefilename", ""), pkg.get("name", "")))
    classes.sort(key=lambda x: x[1] if x[1] is not None else 100)
    anchors = {(p, sf.get("name")): i for i, (p, sf) in enumerate(files)}
    body += ('<h2>クラス別 (低い順)</h2><div class="wrap"><table><thead><tr><th>クラス</th><th>Line</th><th>Branch</th>'
             "<th>Method</th><th>未実行の行</th></tr></thead><tbody>"
             + "".join(f'<tr><td><a href="#src-{anchors.get((p, sfn), 0)}">{esc(name)}</a></td><td>{bar(line)}</td>'
                       f"<td>{bar(branch) if branch is not None else '-'}</td><td>{bar(method)}</td><td>{missed}</td></tr>"
                       for name, line, branch, method, missed, sfn, p in classes)
             + "</tbody></table></div>")

    body += "<h2>ソース</h2>" + COVERAGE_LEGEND
    for i, (pkg_name, sf) in enumerate(files):
        path = module / "src" / "main" / "java" / pkg_name / sf.get("name", "")
        lines = read_lines(path)
        if lines is None:
            continue
        marks = {}
        for ln in sf.findall("line"):
            nr, mi, ci = to_int(ln.get("nr")), to_int(ln.get("mi")), to_int(ln.get("ci"))
            mb, cb = to_int(ln.get("mb")), to_int(ln.get("cb"))
            branch_tip = f"分岐 {cb}/{mb + cb}" if mb + cb else ""
            if ci == 0:
                marks[nr] = ("m", "未実行" + (f" ({branch_tip})" if branch_tip else ""))
            elif mi or mb:
                marks[nr] = ("p", branch_tip or "一部未実行")
            else:
                marks[nr] = ("c", branch_tip or "実行済み")
        line_pct = jacoco_counter(sf, "LINE")[0]
        body += (f'<details id="src-{i}"{" open" if (line_pct or 0) < 100 else ""}><summary>'
                 f'{esc(pkg_name.replace("/", "."))}.{esc(sf.get("name", ""))} '
                 f'<span class="muted">Line {esc(fmt_pct(line_pct))}</span></summary>'
                 + source_html(lines, marks) + "</details>")
    return body


def cmd_be(args) -> int:
    t = Path(args.target)
    module = t.parent  # be/
    r = JobReport("be", "⚙️ Backend (be)", args.out)

    # ---- JUnit → be-tests
    slot = "be-tests"
    files = sorted((t / "surefire-reports").glob("TEST-*.xml"))
    suites, rows, suite_html, failure_html = [], [], [], []
    total = failures = skipped = 0
    for f in files:
        s = parse_xml(f)
        if s is None:
            continue
        tests, fl, er, sk = (to_int(s.get(k)) for k in ("tests", "failures", "errors", "skipped"))
        total, failures, skipped = total + tests, failures + fl + er, skipped + sk
        st = "fail" if fl + er else "pass"
        suites.append([STATUS[st][0], s.get("name", f.stem), tests, fl + er, sk, f"{to_float(s.get('time')):.2f}s"])
        cases = []
        for tc in s.iter("testcase"):
            cls = tc.get("classname", "")
            case_st = "skip" if tc.find("skipped") is not None else "pass"
            for kind in ("failure", "error"):
                el = tc.find(kind)
                if el is None:
                    continue
                case_st = "fail"
                msg = first_line(el.get("message") or el.text)
                file = (module / "src" / "test" / "java" / (cls.replace(".", "/") + ".java")).as_posix()
                m = re.search(rf"\({re.escape(cls.split('.')[-1])}\.java:(\d+)\)", el.text or "")
                line = m.group(1) if m else None
                rows.append([cls, tc.get("name", ""), kind, msg])
                r.annotate("error", msg, file, line, f"テスト失敗: {cls.split('.')[-1]}.{tc.get('name', '')}")
                failure_html.append(f'<h3>{esc(cls.split(".")[-1])}.{esc(tc.get("name", ""))}</h3>'
                                    f'<p class="muted">{esc(kind)}: {esc(el.get("type", ""))} ・ {esc(file)}'
                                    f'{":" + line if line else ""}</p>'
                                    f'<pre class="trace">{esc((el.text or el.get("message") or "")[:MAX_TRACE])}</pre>')
            cases.append(f'<tr><td>{status_cell(case_st)}</td><td>{esc(tc.get("name", ""))}</td>'
                         f'<td>{to_float(tc.get("time")):.3f}s</td></tr>')
        suite_html.append(f'<details{" open" if st == "fail" else ""}><summary>{STATUS[st][0]} {esc(s.get("name", f.stem))} '
                          f'<span class="muted">({tests} 件 / 失敗 {fl + er} / 省略 {sk} / '
                          f'{to_float(s.get("time")):.2f}s)</span></summary><div class="wrap"><table><thead><tr>'
                          f'<th>状態</th><th>テスト</th><th>時間</th></tr></thead><tbody>{"".join(cases)}</tbody>'
                          "</table></div></details>")
    if not files:
        status, headline = "fail", "テスト結果が生成されませんでした"
        r.fail_gate("JUnit 結果なし")
    else:
        status = "fail" if failures else "pass"
        headline = f"{total - failures - skipped}/{total} 成功 (失敗 {failures} / 省略 {skipped})"
        if failures:
            r.fail_gate(f"JUnit 失敗 {failures} 件")
    r.detail(f"失敗したテスト ({len(rows)} 件)", ["クラス", "テスト", "種別", "メッセージ"], rows)
    body = (("<h2>失敗したテスト</h2>" + "".join(failure_html) if failure_html else "")
            + "<h2>テストクラス別</h2>" + "".join(suite_html))
    r.view("be-tests.html", "テスト結果 (JUnit)", headline, body, slot_page=slot)
    r.finish_slot(slot, status, headline,
                  {"tests": {"total": total, "passed": total - failures - skipped, "failed": failures,
                             "skipped": skipped}} if files else {},
                  views=[("テスト結果", "be-tests.html")])

    # ---- JaCoCo → be-jacoco (Pages は JaCoCo 本来の HTML、PR はソース付きの 1 ファイル画面)
    slot = "be-jacoco"
    root = parse_xml(t / "site" / "jacoco" / "jacoco.xml")
    if root is None:
        write_page(r.slot_dir(slot) / "index.html", "JaCoCo", "<h1>JaCoCo</h1><p>生成されませんでした</p>")
        r.finish_slot(slot, "warn", "カバレッジが生成されませんでした")
    else:
        copy_dir(t / "site" / "jacoco", r.slot_dir(slot))
        cov = {k.lower(): jacoco_counter(root, k)[0] for k in ("LINE", "BRANCH", "METHOD", "INSTRUCTION")}
        base = baseline_metric(args.baseline, slot, "coverage", "line")
        line = cov["line"] or 0.0
        headline = (f"Line {fmt_pct(cov['line'])}{fmt_diff(cov['line'], base)} / Branch {fmt_pct(cov['branch'])}"
                    f" / Method {fmt_pct(cov['method'])}")
        cls_rows = [[c.get("name", "").replace("/", "."), fmt_pct(jacoco_counter(c, "LINE")[0]),
                     fmt_pct(jacoco_counter(c, "BRANCH")[0])]
                    for p in root.findall("package") for c in p.findall("class")]
        cls_rows.sort(key=lambda row: to_float(row[1].rstrip("%"), 0))
        r.detail(f"クラス別カバレッジ (低い順, {len(cls_rows)} クラス)", ["クラス", "Line", "Branch"], cls_rows)
        r.view("be-jacoco.html", "カバレッジ (JaCoCo)", headline, jacoco_body(root, module))
        r.finish_slot(slot, "pass" if line >= 80 else "warn", headline, {"coverage": cov},
                      views=[("カバレッジ", "be-jacoco.html")])

    # ---- Javadoc → be-javadoc (画面は警告一覧、API ドキュメント本体は zip)
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
    headers = ["ファイル", "行", "種別", "メッセージ"]
    r.detail(f"Javadoc の警告 ({len(jd_rows)} 件)", headers, jd_rows)
    if apidocs is None:
        r.fail_gate("Javadoc 生成失敗")
        headline = f"生成に失敗しました (エラー {jd_err})"
        write_page(r.slot_dir(slot) / "index.html", "Javadoc", "<h1>Javadoc</h1><p>生成に失敗しました</p>")
        r.view("be-javadoc.html", "Javadoc の警告", headline, table_html(headers, jd_rows))
        r.finish_slot(slot, "fail", headline, views=[("警告一覧", "be-javadoc.html")])
    else:
        copy_dir(apidocs.parent, r.slot_dir(slot))
        headline = f"生成成功 / 警告 {jd_warn} / エラー {jd_err}"
        r.view("be-javadoc.html", "Javadoc の警告", headline,
               '<p class="muted">API ドキュメント本体は複数ファイルのため、PR コメントの「API ドキュメント (zip)」から'
               "ダウンロードしてください。</p>" + table_html(headers, jd_rows))
        r.finish_slot(slot, "warn" if found else "pass", headline,
                      {"issues": {"errors": jd_err, "warnings": jd_warn}},
                      views=[("警告一覧", "be-javadoc.html")], zip_label="API ドキュメント (zip)")

    # ---- Checkstyle → be-checkstyle
    slot = "be-checkstyle"
    root = parse_xml(t / "checkstyle-result.xml")
    headers = ["ファイル", "行", "重大度", "ルール", "メッセージ"]
    rows = []
    if root is None:
        status, headline, metrics = "warn", "レポートが生成されませんでした", {}
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
        status = "fail" if errs else ("warn" if rows else "pass")
        headline = f"エラー {errs} / 警告 {len(rows) - errs} (対象 {len(root.findall('file'))} ファイル)"
        metrics = {"issues": {"errors": errs, "warnings": len(rows) - errs}}
    r.view("be-checkstyle.html", "Checkstyle", headline, table_html(headers, rows), slot_page=slot)
    r.finish_slot(slot, status, headline, metrics, views=[("指摘一覧", "be-checkstyle.html")])

    # ---- SpotBugs → be-spotbugs
    slot = "be-spotbugs"
    root = parse_xml(t / "spotbugsXml.xml")
    headers = ["優先度", "カテゴリ", "種別", "クラス", "行", "内容"]
    rows = []
    counts = {"High": 0, "Medium": 0, "Low": 0}
    if root is None:
        status, headline, metrics = "warn", "レポートが生成されませんでした", {}
    else:
        prio = {"1": "High", "2": "Medium", "3": "Low"}
        for bug in root.findall("BugInstance"):
            cls = bug.find("Class")
            src_line = bug.find("SourceLine")
            rows.append([prio.get(bug.get("priority", ""), bug.get("priority", "")), bug.get("category", ""),
                         bug.get("type", ""), cls.get("classname", "") if cls is not None else "",
                         src_line.get("start", "-") if src_line is not None else "-",
                         bug.findtext("LongMessage") or bug.findtext("ShortMessage") or ""])
        rank = {"High": 0, "Medium": 1, "Low": 2}
        rows.sort(key=lambda row: rank.get(row[0], 9))
        counts = {p: sum(1 for row in rows if row[0] == p) for p in counts}
        if counts["High"]:
            r.fail_gate(f"SpotBugs High {counts['High']} 件")
        r.detail(f"SpotBugs の指摘 ({len(rows)} 件)", headers, rows)
        status = "fail" if counts["High"] else ("warn" if rows else "pass")
        headline = f"合計 {len(rows)} 件 (High {counts['High']} / Medium {counts['Medium']} / Low {counts['Low']})"
        metrics = {"issues": {"errors": counts["High"], "warnings": counts["Medium"] + counts["Low"]}}
    r.view("be-spotbugs.html", "SpotBugs", headline, table_html(headers, rows), slot_page=slot)
    r.finish_slot(slot, status, headline, metrics, views=[("指摘一覧", "be-spotbugs.html")])

    r.write()
    return 0


# --------------------------------------------------------------------------- Docs
def cmd_docs(args) -> int:
    build = Path(args.build)
    r = JobReport("docs", "📚 Docs (Docusaurus)", args.out)
    if args.outcome == "success" and (build / "index.html").exists():
        copy_dir(build, r.slot_dir("docs"))
        pages = sum(1 for p in build.rglob("index.html") if "assets" not in p.parts)
        r.finish_slot("docs", "pass", f"ビルド成功 ({pages} ページ)", {"pages": pages}, zip_label="サイト (zip)")
    else:
        r.fail_gate("Docusaurus ビルド失敗")
        write_page(r.slot_dir("docs") / "index.html", "Docs", "<h1>Docs</h1><p>ビルドに失敗しました</p>")
        r.finish_slot("docs", "fail", "ビルドに失敗しました (リンク切れ等)")
    r.write()
    return 0


# --------------------------------------------------------------------------- PR: 全体の HTML と PR コメント
def load_jobs(summaries: str) -> tuple[list[dict], list[str]]:
    jobs, failures = [], []
    for p in sorted(Path(summaries).rglob("*.json")):
        data = load_json(p) or {}
        if "rows" not in data:
            continue
        jobs.append(data)
        failures += [f"{data.get('job', p.stem)}: {g}" for g in data.get("gate_failures", [])]
    return jobs, failures


def artifact_urls(path: str) -> dict[str, dict]:
    """artifacts.json ([{name, url, size}]) を名前で引けるようにする."""
    data = load_json(Path(path)) if path else None
    return {a["name"]: a for a in (data or []) if isinstance(a, dict) and "name" in a}


def row_links(row: dict, arts: dict[str, dict]) -> list[tuple[str, str]]:
    """行からリンクする画面 [(表示名, URL)]. 画面は report/<file> を archive: false で上げた Artifact (名前 = ファイル名)."""
    links = [(v["label"], arts[v["file"]]["url"]) for v in row.get("views", []) if v["file"] in arts]
    z = row.get("zip")
    if z and z.get("artifact") in arts:
        links.append((z["label"], arts[z["artifact"]]["url"]))
    return links


def links_html(links: list[tuple[str, str]]) -> str:
    return " ".join(f'<a href="{esc(url)}">{esc(label)}</a>' for label, url in links) or "-"


def cmd_report_html(args) -> int:
    """全ジョブの結果を 1 ファイルの HTML にまとめる (外部ファイル・相対リンクを使わない自己完結の HTML)."""
    ctx = run_context()
    jobs, failures = load_jobs(args.summaries)
    arts = artifact_urls(args.artifacts)
    pr = os.environ.get("PR_NUMBER", "")
    pr_title = os.environ.get("PR_TITLE", "")
    pr_url = f"{ctx['server']}/{ctx['repo']}/pull/{pr}" if pr else ""

    gate_cls = "s-fail" if failures else "s-pass"
    gate = (f'<div class="banner {gate_cls}">'
            + (f'❌ 品質ゲート: 不合格 — {esc(" / ".join(failures))}' if failures else "✅ 品質ゲート: 合格")
            + "</div>")
    toc = '<nav class="toc">' + "".join(
        f'<a href="#job-{esc(j["job"])}">{esc(j.get("title", j["job"]))}</a>' for j in jobs) + "</nav>"

    sections = []
    for j in jobs:
        rows = "".join(
            f'<tr><td>{esc(r["name"])}</td><td class="st">{status_cell(r["status"])}</td><td>{esc(r["result"])}</td>'
            f"<td>{links_html(row_links(r, arts))}</td></tr>"
            for r in j["rows"])
        body = ('<div class="wrap"><table><thead><tr><th>チェック</th><th>状態</th><th>結果</th><th>画面</th></tr></thead>'
                f"<tbody>{rows}</tbody></table></div>")
        if j.get("gate_failures"):
            body += f'<p class="s-fail">品質ゲート不合格: {esc(" / ".join(j["gate_failures"]))}</p>'
        for d in j.get("details", []):
            is_open = " open" if "失敗" in d["summary"] else ""
            body += (f"<details{is_open}><summary>{esc(d['summary'])}</summary>"
                     + table_html(d["headers"], d["rows"]) + "</details>")
        sections.append(f'<section class="job" id="job-{esc(j["job"])}"><h2>{esc(j.get("title", j["job"]))}</h2>'
                        f"{body}</section>")
    if not sections:
        sections.append('<p class="muted">実行されたジョブがありません (変更のなかったプロジェクトは実行されません)。</p>')

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

    css = VIEW_CSS + """
.banner{padding:10px 14px;border-radius:8px;border:1px solid var(--border);background:var(--card);margin:12px 0;font-weight:600}
nav.toc{display:flex;flex-wrap:wrap;gap:6px;margin:12px 0}
nav.toc a{border:1px solid var(--border);border-radius:6px;padding:2px 10px;text-decoration:none;font-size:13px}
section.job{margin:28px 0}
section.job h2{font-size:18px;border-left:4px solid var(--link);padding-left:8px}
td.st{white-space:nowrap}
footer{margin-top:32px;font-size:12px;color:var(--muted)}
"""
    content = (f'<header class="view"><h1>{esc(title)}</h1><div class="meta">{"".join(meta)}</div></header>'
               + gate + toc + "".join(sections)
               + "<footer>このファイルは CI が自動生成した 1 ファイル完結の HTML です。「画面」列のリンクから各レポートを開けます。"
                 "変更のなかったプロジェクトのジョブは実行されないため、ここには載りません。</footer>")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text('<!doctype html><html lang="ja"><head><meta charset="utf-8">'
                   '<meta name="viewport" content="width=device-width, initial-scale=1">'
                   f"<title>{esc(title)}</title><style>{BASE_CSS}{css}</style></head><body><main>"
                   + content + "</main></body></html>", encoding="utf-8")
    return 0


def cmd_comment(args) -> int:
    """PR コメント: 1 チェック 1 行の要約表に、それぞれの画面へのリンクを付ける."""
    ctx = run_context()
    jobs, failures = load_jobs(args.summaries)
    arts = artifact_urls(args.artifacts)
    gate = ("✅ **品質ゲート: 合格**" if not failures
            else "❌ **品質ゲート: 不合格** — " + " / ".join(md_cell(f) for f in failures))
    lines = ["<!-- ci-report -->", "## 📊 CI レポート", "", gate, "",
             "| 対象 | チェック | 状態 | 結果 | 画面 |", "|---|---|:---:|---|---|"]
    for job in jobs:
        for row in job["rows"]:
            links = " ・ ".join(f"[{md_cell(label)}]({url})" for label, url in row_links(row, arts)) or "-"
            lines.append(f"| {md_cell(job.get('job', ''))} | {md_cell(row['name'])} | {STATUS[row['status']][0]} "
                         f"| {md_cell(row['result'])} | {links} |")
    if not jobs:
        lines.append("| - | 実行されたジョブがありません | - | - | - |")
    lines += ["", "「画面」のリンクはブラウザでそのまま開けます (この CI 実行の Artifact。GitHub にログインした状態で開いてください。"
                  "保持 14 日)。zip は展開して開いてください。"]
    footer = []
    if args.report_url:
        footer.append(f"[📄 全体のレポート]({args.report_url})")
    footer.append(f"コミット `{ctx['commit'][:7]}`")
    footer.append(f"[CI 実行 (ジョブサマリ・Artifacts)]({ctx['run_url']})")
    if args.pages_url:
        footer.append(f"[develop の品質レポート (Pages)]({args.pages_url})")
    lines += ["", " ・ ".join(footer), "",
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
    p.add_argument("--artifacts", default="")
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
