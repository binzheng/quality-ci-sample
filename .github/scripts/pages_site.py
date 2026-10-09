#!/usr/bin/env python3
"""GitHub Pages のサイトを組み立てる (develop の最新レポート + 索引画面).

Usage:
  pages_site.py fetch --dest <dir> [--slots a,b] [--branch develop]
      枠ごとに「その枠の Artifact (pages-<枠>) を最後に出した <branch> の実行」を探してダウンロードする。
      PR の実行が同じ名前の Artifact を出しても、ブランチで絞るので拾わない。gh CLI (GH_TOKEN) を使う。
  pages_site.py assemble --staging <dir> --site <dir> [--budget-mb 950] [--warn-mb 800]
      取得した枠を Pages 上のパスへ配置し、容量予算を超える分は priority の低い順に省く。
      索引画面 index.html と site.json を出力する。

索引画面は静的 HTML として生成する (画面側で JSON を fetch しない・外部 CDN を使わない)。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from report_common import (FE_PACKAGES, STATUS, BASE_CSS, build_catalog, copy_dir, dir_size, esc, fmt_jst,
                           is_stale, load_json, now_iso, write_json)

PAGES_META = "_pages"


# --------------------------------------------------------------------------- fetch
def gh_json(*args: str):
    out = subprocess.run(["gh", "api", *args], check=True, capture_output=True, text=True).stdout
    return json.loads(out) if out.strip() else None


def cmd_fetch(args) -> int:
    repo = os.environ["GITHUB_REPOSITORY"]
    wanted = set(args.slots.split(",")) if args.slots else None
    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)
    for slot in build_catalog():
        if wanted and slot["id"] not in wanted:
            continue
        name = f"pages-{slot['id']}"
        data = gh_json(f"repos/{repo}/actions/artifacts?name={name}&per_page=100") or {}
        candidates = [a for a in data.get("artifacts", [])
                      if not a.get("expired") and (a.get("workflow_run") or {}).get("head_branch") == args.branch]
        if not candidates:
            print(f"{name}: {args.branch} の成果物なし")
            continue
        art = max(candidates, key=lambda a: a.get("created_at", ""))
        run = art["workflow_run"]
        target = dest / slot["id"]
        if target.exists():
            shutil.rmtree(target)
        result = subprocess.run(["gh", "run", "download", str(run["id"]), "-R", repo, "-n", name, "-D", str(target)],
                                capture_output=True, text=True)
        if result.returncode != 0:
            print(f"::warning::{name} のダウンロードに失敗しました: {result.stderr.strip()}")
            continue
        write_json(target / PAGES_META / "artifact.json", {
            "artifact_id": art.get("id"), "run_id": run.get("id"), "head_sha": run.get("head_sha"),
            "created_at": art.get("created_at"), "size_in_bytes": art.get("size_in_bytes"),
        })
        print(f"{name}: run {run.get('id')} ({str(run.get('head_sha'))[:7]}, {art.get('created_at')})")
    return 0


# --------------------------------------------------------------------------- assemble
def slot_state(slot: dict, staging: Path) -> dict:
    src = staging / slot["id"]
    summary = load_json(src / PAGES_META / "summary.json") or {}
    artifact = load_json(src / PAGES_META / "artifact.json") or {}
    present = src.is_dir() and (src / "index.html").exists()
    return {
        **slot,
        "present": present,
        "status": summary.get("status", "pass") if present else "missing",
        "headline": summary.get("headline", "") if present else "保持期間内の develop の成果物がありません",
        "metrics": summary.get("metrics", {}),
        "links": summary.get("links", []),
        "commit": summary.get("commit") or artifact.get("head_sha") or "",
        "generated_at": summary.get("generated_at") or artifact.get("created_at") or "",
        "run_url": summary.get("run_url", ""),
        "size": dir_size(src, exclude=PAGES_META) if present else 0,
        "omitted": False,
    }


def apply_budget(states: list[dict], budget: int, fixed: int) -> int:
    """容量予算を超える分を priority の低い順に省く. 省いても件数・率は概況に数える."""
    total = fixed + sum(s["size"] for s in states if s["present"])
    for s in sorted((s for s in states if s["present"]), key=lambda s: s["priority"]):
        if total <= budget:
            break
        s["omitted"] = True
        total -= s["size"]
    return total


def mb(size: int) -> str:
    return f"{size / 1024 / 1024:.1f} MB"


def cmd_assemble(args) -> int:
    staging, site = Path(args.staging), Path(args.site)
    site.mkdir(parents=True, exist_ok=True)
    ci_metrics = site / "ci-metrics"
    fixed = dir_size(ci_metrics) if ci_metrics.is_dir() else 0

    states = [slot_state(s, staging) for s in build_catalog()]
    budget = int(args.budget_mb * 1024 * 1024)
    total = apply_budget(states, budget, fixed)

    for s in states:
        if s["present"] and not s["omitted"]:
            dst = site / s["path"]
            copy_dir(staging / s["id"], dst)
            shutil.rmtree(dst / PAGES_META, ignore_errors=True)

    deploy = {
        "deployed_at": now_iso(),
        "source_sha": os.environ.get("SOURCE_SHA", ""),
        "source_run_url": os.environ.get("SOURCE_RUN_URL", ""),
        "source_run_number": os.environ.get("SOURCE_RUN_NUMBER", ""),
        "repo_url": f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{os.environ.get('GITHUB_REPOSITORY', '')}",
        "ci_workflow": os.environ.get("CI_WORKFLOW_FILE", "ci.yml"),
        "site_bytes": total,
        "budget_bytes": budget,
        "has_ci_metrics": ci_metrics.is_dir(),
    }
    overview = build_overview(states)

    write_json(site / "site.json", {
        "deploy": deploy,
        "overview": overview,
        "slots": [{k: s[k] for k in ("id", "group", "package", "title", "path", "priority", "present", "omitted",
                                     "status", "headline", "metrics", "commit", "generated_at", "size")}
                  for s in states],
    })
    (site / "index.html").write_text(render_index_html(states, overview, deploy), encoding="utf-8")
    (site / ".nojekyll").touch()

    # ジョブサマリ: 容量の実測
    lines = ["### Pages サイト", "", f"合計 **{mb(total)}** / 予算 {mb(budget)}", "",
             "| 枠 | 状態 | サイズ | priority |", "|---|:---:|---:|---:|"]
    for s in sorted(states, key=lambda s: -s["size"]):
        state = "omitted" if s["omitted"] else s["status"]
        lines.append(f"| {s['id']} | {STATUS[state][0]} | {mb(s['size'])} | {s['priority']} |")
    if fixed:
        lines.append(f"| ci-metrics | ✅ | {mb(fixed)} | - |")
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    if total > args.warn_mb * 1024 * 1024:
        print(f"::warning::Pages サイトが {mb(total)} です ({args.warn_mb} MB 超)。上限は 1 GB です")
    omitted = [s["id"] for s in states if s["omitted"]]
    if omitted:
        print(f"::warning::容量のため省略した枠: {', '.join(omitted)}")
    return 0


# --------------------------------------------------------------------------- 概況
def build_overview(states: list[dict]) -> dict:
    tests = {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "slots": 0}
    issues = {"errors": 0, "warnings": 0}
    coverage = {"be": None, "fe": {}}
    for s in states:
        if not s["present"]:
            continue
        m = s["metrics"]
        if "tests" in m:
            tests["slots"] += 1
            for k in ("total", "passed", "failed", "skipped"):
                tests[k] += m["tests"].get(k, 0) or 0
        if "issues" in m:
            issues["errors"] += m["issues"].get("errors", 0) or 0
            issues["warnings"] += m["issues"].get("warnings", 0) or 0
        if "coverage" in m:
            if s["group"] == "be":
                coverage["be"] = m["coverage"].get("line")
            elif s["group"] == "fe":
                coverage["fe"][s["package"]] = m["coverage"].get("lines")
    missing = sum(1 for s in states if not s["present"])
    failed = sum(1 for s in states if s["present"] and s["status"] == "fail")
    return {"tests": tests, "issues": issues, "coverage": coverage, "missing_slots": missing, "failed_slots": failed}


# --------------------------------------------------------------------------- 索引画面
INDEX_CSS = """
header.top{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:flex-end;gap:8px 24px;
border-bottom:1px solid var(--border);padding-bottom:12px;margin-bottom:8px}
header.top h1{margin:0}
.meta{display:flex;flex-wrap:wrap;gap:2px 16px;font-size:13px;color:var(--muted)}
.meta b{color:var(--fg);font-weight:600}
section{margin:28px 0}
.num{display:inline-block;min-width:1.6em;height:1.6em;line-height:1.6em;text-align:center;border-radius:50%;
background:var(--fg);color:var(--bg);font-size:12px;margin-right:6px;vertical-align:1px}
.cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
@media (max-width:900px){.cards{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (max-width:480px){.cards{grid-template-columns:minmax(0,1fr)}}
.card{border:1px solid var(--border);border-radius:8px;padding:12px 14px;background:var(--card);min-width:0}
.card .label{font-size:12px;color:var(--muted)}
.card .value{font-size:26px;font-weight:600;line-height:1.3}
.card .sub{font-size:12px;color:var(--muted)}
.btn{display:inline-block;padding:2px 10px;margin:2px 4px 2px 0;border:1px solid var(--border);border-radius:6px;
background:var(--bg);text-decoration:none;font-size:13px;white-space:nowrap}
.btn:hover{border-color:var(--link)}
.state{white-space:nowrap}
.stale,.stale a{color:var(--stale)}
.headline{display:block;font-size:12px;color:var(--muted)}
table.rtable td.c-name{font-weight:600}
@media (max-width:760px){
  table.rtable thead{display:none}
  table.rtable,table.rtable tbody,table.rtable tr,table.rtable td{display:block;width:100%}
  table.rtable tr{border:1px solid var(--border);border-radius:8px;padding:8px 12px;margin:0 0 10px;background:var(--card)}
  table.rtable td{border:none;padding:3px 0}
  table.rtable td[data-label]::before{content:attr(data-label);display:block;font-size:11px;color:var(--muted)}
}
.two{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
@media (max-width:640px){.two{grid-template-columns:minmax(0,1fr)}}
.guide{border-left:4px solid var(--info);background:var(--card);padding:10px 14px;border-radius:0 8px 8px 0}
footer{margin-top:32px;font-size:12px;color:var(--muted)}
"""


def state_html(s: dict) -> str:
    key = "omitted" if s.get("omitted") else s["status"]
    icon, label = STATUS[key]
    return f'<span class="state s-{key}">{icon} {esc(label)}</span>'


def commit_html(sha: str, repo_url: str) -> str:
    if not sha:
        return "-"
    return f'<a href="{esc(repo_url)}/commit/{esc(sha)}"><code>{esc(sha[:7])}</code></a>'


def open_links(s: dict) -> str:
    if not s["present"] or s["omitted"]:
        return '<span class="muted">-</span>'
    out = [f'<a class="btn" href="./{esc(s["path"])}">開く</a>']
    for link in s.get("links", []):
        out.append(f'<a class="btn" href="./{esc(s["path"])}{esc(link["href"])}">{esc(link["label"])}</a>')
    return "".join(out)


def origin_cells(s: dict, repo_url: str) -> str:
    cls = ' class="stale"' if is_stale(s["generated_at"]) else ""
    return (f'<td data-label="元コミット"{cls}>{commit_html(s["commit"], repo_url)}</td>'
            f'<td data-label="生成日時"{cls}>{esc(fmt_jst(s["generated_at"]))}</td>')


def fmt_pct(v) -> str:
    return f"{v:.1f}%" if isinstance(v, (int, float)) else "-"


def render_index_html(states: list[dict], overview: dict, deploy: dict) -> str:
    repo_url = deploy["repo_url"]
    by_id = {s["id"]: s for s in states}

    # ---- ヘッダー
    run_label = f"CI #{deploy['source_run_number']}" if deploy["source_run_number"] else "CI 実行"
    source = commit_html(deploy["source_sha"], repo_url)
    if deploy["source_run_url"]:
        source += f' ・ <a href="{esc(deploy["source_run_url"])}">{esc(run_label)}</a>'
    header = (
        '<header class="top"><h1>品質レポート <span class="muted">(develop)</span></h1>'
        '<div class="meta">'
        f'<span>最終配備 <b>{esc(fmt_jst(deploy["deployed_at"]))} JST</b></span>'
        f'<span>配備元 {source}</span>'
        f'<span>サイズ {esc(mb(deploy["site_bytes"]))}</span>'
        "</div></header>"
    )

    # ---- ① 概況
    t = overview["tests"]
    test_state = "fail" if t["failed"] else ("pass" if t["total"] else "missing")
    fe_cov = overview["coverage"]["fe"]
    if len(fe_cov) <= 1:
        fe_value = fmt_pct(next(iter(fe_cov.values()), None))
        fe_sub = "Lines"
    else:
        fe_value = fmt_pct(min((v for v in fe_cov.values() if isinstance(v, (int, float))), default=None))
        fe_sub = "最小 / " + " ・ ".join(f"{k} {fmt_pct(v)}" for k, v in fe_cov.items())
    iss = overview["issues"]
    cards = [
        ("テスト", f'<span class="s-{test_state}">{t["passed"]}/{t["total"]}</span>',
         f'失敗 {t["failed"]} ・ 省略 {t["skipped"]} ・ {t["slots"]} 枠'),
        ("BE カバレッジ", fmt_pct(overview["coverage"]["be"]), "JaCoCo Line"),
        ("FE カバレッジ", fe_value, f"Vitest {fe_sub}"),
        ("静的解析の指摘", f'<span class="s-{"fail" if iss["errors"] else "pass"}">{iss["errors"]}</span>',
         f'エラー ・ 警告 {iss["warnings"]} (ESLint / Checkstyle / SpotBugs / Javadoc)'),
    ]
    sec1 = ('<section><h2><span class="num">1</span>概況</h2><div class="cards">'
            + "".join(f'<div class="card"><div class="label">{esc(label)}</div><div class="value">{value}</div>'
                      f'<div class="sub">{esc(sub)}</div></div>' for label, value, sub in cards)
            + "</div>"
            + (f'<p class="muted">⚠️ 成果物のない枠が {overview["missing_slots"]} 件あります。</p>'
               if overview["missing_slots"] else "")
            + "</section>")

    # ---- ② バックエンド
    be_rows = []
    for s in (x for x in states if x["group"] == "be"):
        be_rows.append(
            f'<tr><td class="c-name" data-label="レポート">{esc(s["title"])}</td>'
            f'<td data-label="状態">{state_html(s)}</td>'
            f'<td data-label="結果">{esc(s["headline"])}</td>'
            + origin_cells(s, repo_url)
            + f'<td data-label="開く">{open_links(s)}</td></tr>')
    sec2 = ('<section><h2><span class="num">2</span>バックエンド (be)</h2><table class="rtable"><thead><tr>'
            "<th>レポート</th><th>状態</th><th>結果</th><th>元コミット</th><th>生成日時</th><th>開く</th>"
            "</tr></thead><tbody>" + "".join(be_rows) + "</tbody></table></section>")

    # ---- ③ フロントエンド (パッケージごとに 1 行。狭い画面ではカード)
    kinds = ["vitest", "storybook", "eslint", "audit", "sloc"]
    fe_slots = [x for x in states if x["group"] == "fe"]
    titles = {k: next((x.get("short", x["title"]) for x in fe_slots if x["id"].endswith(f"-{k}")), k) for k in kinds}
    fe_rows = []
    for pkg in FE_PACKAGES:
        cells = []
        for k in kinds:
            s = by_id.get(f"fe-{pkg}-{k}")
            if s is None:
                cells.append(f'<td data-label="{esc(titles[k])}">{state_html({"status": "na"})}</td>')
                continue
            cells.append(f'<td data-label="{esc(titles[k])}">{state_html(s)}'
                         f'<span class="headline">{esc(s["headline"])}</span>{open_links(s)}</td>')
        origin = next((by_id[f"fe-{pkg}-{k}"] for k in kinds if by_id.get(f"fe-{pkg}-{k}", {}).get("present")),
                      by_id[f"fe-{pkg}-vitest"])
        fe_rows.append(f'<tr><td class="c-name" data-label="パッケージ">{esc(pkg)}</td>' + "".join(cells)
                       + origin_cells(origin, repo_url) + "</tr>")
    sec3 = ('<section><h2><span class="num">3</span>フロントエンド (fe)</h2><table class="rtable"><thead><tr>'
            "<th>パッケージ</th>" + "".join(f"<th>{esc(titles[k])}</th>" for k in kinds)
            + "<th>元コミット</th><th>生成日時</th></tr></thead><tbody>" + "".join(fe_rows)
            + "</tbody></table></section>")

    # ---- ④ ドキュメント・推移
    docs = by_id["docs"]
    stale = ' class="stale"' if is_stale(docs["generated_at"]) else ""
    docs_card = (f'<div class="card"><div class="label">ドキュメント (Docusaurus)</div>'
                 f'<div>{state_html(docs)} <span class="muted">{esc(docs["headline"])}</span></div>'
                 f'<div class="sub"{stale}>元コミット {commit_html(docs["commit"], repo_url)} ・ '
                 f'{esc(fmt_jst(docs["generated_at"]))}</div><div>{open_links(docs)}</div></div>')
    if deploy["has_ci_metrics"]:
        metrics_card = ('<div class="card"><div class="label">推移 (ci-metrics)</div>'
                        '<div class="sub">ビルド時間・規模などの推移グラフ</div>'
                        '<div><a class="btn" href="./ci-metrics/">開く</a></div></div>')
    else:
        metrics_card = ('<div class="card"><div class="label">推移 (ci-metrics)</div>'
                        f'<div>{state_html({"status": "na"})}</div>'
                        '<div class="sub">未導入 (gh-pages ブランチの ci-metrics/ があれば取り込みます)</div></div>')
    sec4 = ('<section><h2><span class="num">4</span>ドキュメント・推移</h2><div class="two">'
            + docs_card + metrics_card + "</div></section>")

    # ---- ⑤ 案内
    sec5 = ('<section><h2><span class="num">5</span>PR・ブランチの結果</h2><div class="guide">'
            "<p>この画面には <b>develop</b> の最新レポートだけを載せています。PR・ブランチの CI 結果は"
            "<b>PR 画面</b> (チェック一覧の <code>CI status</code>、各ジョブのサマリと注釈、PR コメント) で確認し、"
            "HTML レポートは CI 実行の Artifacts (<code>pages-*</code>) をダウンロードして開いてください。</p>"
            f'<p><a class="btn" href="./docs/ci/pr-guide/">PR での確認手順</a>'
            f'<a class="btn" href="{esc(repo_url)}/actions/workflows/{esc(deploy["ci_workflow"])}">CI の実行一覧</a>'
            f'<a class="btn" href="{esc(repo_url)}/pulls">PR 一覧</a></p></div></section>')

    legend = " ・ ".join(f"{icon} {label}" for icon, label in
                         (STATUS[k] for k in ("pass", "warn", "fail", "missing", "na", "omitted")))
    footer = (f"<footer>状態: {esc(legend)}<br>各枠は、その枠の成果物を最後に出した develop の CI のものです"
              "(配備元と異なる場合があります)。7 日以上前のものは灰色で表示します。"
              ' <a href="./site.json">site.json</a></footer>')

    return ('<!doctype html><html lang="ja"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>品質レポート</title><style>{BASE_CSS}{INDEX_CSS}</style></head><body><main>"
            + header + sec1 + sec2 + sec3 + sec4 + sec5 + footer + "</main></body></html>")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("fetch")
    p.add_argument("--dest", required=True)
    p.add_argument("--slots", default="")
    p.add_argument("--branch", default="develop")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("assemble")
    p.add_argument("--staging", required=True)
    p.add_argument("--site", required=True)
    p.add_argument("--budget-mb", type=int, default=int(os.environ.get("PAGES_BUDGET_MB", "950")))
    p.add_argument("--warn-mb", type=int, default=800)
    p.set_defaults(func=cmd_assemble)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
