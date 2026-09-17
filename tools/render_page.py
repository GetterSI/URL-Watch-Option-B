#!/usr/bin/env python3
"""Render urlwatch's state into index.html — the hosted page.

Charles owns this repo and this page. urlwatch is the engine underneath,
installed as a pinned dependency rather than forked, so its maintainers' fixes
arrive without us maintaining anything.

Read-only by design: it never fetches and never writes to the cache, so it
cannot affect detection. If it breaks, the monitoring carries on.

Reads the same two things as the dashboard: urls.yaml for the job list, and
urlwatch's minidb cache (table CacheEntry, columns guid/timestamp/tries/data)
joined by sha1(location) — the guid urlwatch derives in jobs.py get_guid().
"""
import datetime
import hashlib
import html
import os
import sqlite3
import sys

import yaml

CACHE = os.environ.get("URLWATCH_CACHE", "cache.db")
URLS = os.environ.get("URLWATCH_URLS", "urls.yaml")
OUT = os.environ.get("PAGE_PATH", "index.html")
REPORT = os.environ.get("REPORT_PATH", "last-report.txt")
REPO = os.environ.get("GITHUB_REPOSITORY", "GetterSI/regulatory-watch")

# Under this many characters a "successful" fetch is almost certainly a shell,
# a consent wall or a block page rather than the page itself. Shown as
# low-confidence rather than counted as covered: a row that looks monitored
# while holding nothing is worse than a visible failure.
THIN_CHARS = 400


def load_jobs(path):
    with open(path, "r", encoding="utf-8") as f:
        docs = [d for d in yaml.safe_load_all(f) if d]
    jobs = []
    for d in docs:
        loc = d.get("url") or d.get("navigate") or d.get("command") or ""
        row = None
        for tag in (d.get("tags") or []):
            if isinstance(tag, str) and tag.startswith("vp-"):
                try:
                    row = int(tag[3:])
                except ValueError:
                    pass
        jobs.append({
            "name": d.get("name") or loc,
            "loc": loc,
            "kind": "browser" if d.get("navigate") else "url",
            "row": row,
            "guid": hashlib.sha1(loc.encode("utf-8")).hexdigest(),
        })
    return jobs


def load_cache(path):
    if not os.path.exists(path):
        return {}
    con = sqlite3.connect(path)
    try:
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
        table = next((t for t in tables if t.lower() == "cacheentry"), None)
        if table is None:
            return {}
        rows = con.execute(
            "SELECT guid, timestamp, tries, LENGTH(data) "
            "FROM %s ORDER BY guid, timestamp DESC" % table).fetchall()
    except sqlite3.Error as exc:
        print("cache unreadable (%r) — page will show no state" % (exc,))
        return {}
    finally:
        con.close()
    latest = {}
    for guid, ts, tries, n in rows:
        if guid not in latest:
            latest[guid] = {"ts": ts, "tries": tries or 0, "chars": n or 0}
    return latest


def uk(ts):
    if not ts:
        return "—"
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.fromtimestamp(
            float(ts), ZoneInfo("Europe/London")).strftime("%d %b %Y, %H:%M %Z")
    except Exception:  # noqa: BLE001
        return datetime.datetime.utcfromtimestamp(
            float(ts)).strftime("%d %b %Y, %H:%M UTC")


def e(s):
    return html.escape(str(s), quote=True)


CSS = """
:root{--bg:#fbfbfa;--card:#fff;--ink:#1a1a18;--muted:#6b6b66;--line:#e5e4e0;
--ok:#2f6f43;--warn:#8a5a00;--bad:#9b2c2c;--accent:#2b5c8a;color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){
--bg:#16161a;--card:#1e1e24;--ink:#ecebe8;--muted:#9a998f;--line:#2f2f37;
--ok:#7fc39a;--warn:#e0b060;--bad:#e08585;--accent:#8fb8de}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
padding-block:32px;padding-left:20px;padding-right:20px}
.wrap{max-width:1040px;margin:0 auto}
h1{font-size:1.55rem;margin:0 0 4px;letter-spacing:-.01em}
.sub{color:var(--muted);margin:0 0 26px;font-size:.9rem}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:28px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.stat .n{font-size:1.7rem;font-weight:650;letter-spacing:-.02em}
.stat .l{color:var(--muted);font-size:.78rem;text-transform:uppercase;letter-spacing:.05em;margin-top:2px}
.stat.ok .n{color:var(--ok)}.stat.warn .n{color:var(--warn)}.stat.bad .n{color:var(--bad)}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:18px 20px;margin-bottom:20px}
h2{font-size:1.02rem;margin:0 0 4px}
.note{color:var(--muted);font-size:.86rem;margin:0 0 14px}
table{width:100%;border-collapse:collapse;font-size:.88rem}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:.74rem;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);font-weight:600}
tbody tr:last-child td{border-bottom:none}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
a{color:var(--accent)}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
pre{background:var(--bg);border:1px solid var(--line);border-radius:8px;
padding:12px;overflow-x:auto;font-size:.82rem;line-height:1.45;margin:0}
details summary{cursor:pointer;color:var(--accent);font-size:.9rem}
.pill{display:inline-block;font-size:.72rem;padding:1px 7px;border-radius:999px;
border:1px solid var(--line);color:var(--muted)}
footer{color:var(--muted);font-size:.82rem;margin-top:26px;line-height:1.7}
@media(max-width:560px){.stat .n{font-size:1.4rem}h1{font-size:1.3rem}}
"""


def main():
    jobs = load_jobs(URLS)
    cache = load_cache(CACHE)

    seen, never, thin, failing = [], [], [], []
    for j in jobs:
        c = cache.get(j["guid"])
        if c is None:
            never.append(j)
            continue
        j.update(c)
        seen.append(j)
        if c["tries"]:
            failing.append(j)
        elif c["chars"] < THIN_CHARS:
            thin.append(j)

    report = ""
    if os.path.exists(REPORT):
        with open(REPORT, "r", encoding="utf-8") as f:
            report = f.read().strip()

    o = []
    o.append("<!doctype html><html lang=en><head><meta charset=utf-8>")
    o.append('<meta name=viewport content="width=device-width,initial-scale=1">')
    o.append("<title>Regulatory URL Watch</title>")
    o.append("<style>%s</style></head><body><div class=wrap>" % CSS)

    o.append("<h1>Regulatory URL Watch</h1>")
    o.append('<p class=sub>Source Intelligence — Regulatory Team. '
             'Last run %s. Checked automatically every day; '
             'this page is rebuilt by the run itself.</p>' % e(uk(
                 max((j.get("ts") or 0) for j in seen) if seen else None)))

    def stat(n, label, cls=""):
        o.append('<div class="stat %s"><div class=n>%s</div>'
                 '<div class=l>%s</div></div>' % (cls, n, label))

    o.append("<div class=grid>")
    stat(len(jobs), "sources watched")
    stat(len(seen), "with a snapshot", "ok" if len(seen) == len(jobs) else "warn")
    stat(len(never), "never fetched", "bad" if never else "ok")
    stat(len(failing), "failing now", "warn" if failing else "ok")
    stat(len(thin), "low confidence", "warn" if thin else "ok")
    o.append("</div>")

    o.append("<section><h2>Latest report</h2>")
    if report:
        o.append('<p class=note>What urlwatch reported on the most recent run. '
                 'An empty report means nothing changed.</p>')
        o.append("<pre>%s</pre>" % e(report[:20000]))
    else:
        o.append('<p class=note>No changes reported on the most recent run.</p>')
    o.append("</section>")

    if failing:
        o.append("<section><h2>Failing now <span class=pill>%d</span></h2>" % len(failing))
        o.append('<p class=note>Consecutive failures. urlwatch only reports an '
                 'error once a job passes <code>max_tries</code>, so a job at 1 '
                 'has not raised an alert yet.</p><div class=scroll><table>'
                 '<thead><tr><th>Visualping ID</th><th>Page</th>'
                 '<th class=num>Failures</th><th>Last attempt</th></tr></thead><tbody>')
        for j in sorted(failing, key=lambda x: -x["tries"]):
            o.append("<tr><td class=num>%s</td><td>%s</td>"
                     "<td class=num>%d</td><td>%s</td></tr>"
                     % (j["row"] or "—", e(j["name"]), j["tries"], e(uk(j["ts"]))))
        o.append("</tbody></table></div></section>")

    if never:
        o.append("<section><h2>Never fetched <span class=pill>%d</span></h2>" % len(never))
        o.append('<p class=note>No snapshot has ever been stored, so a change '
                 'could not be detected. Each needs its own fix: a browser job, '
                 'a new URL, or retirement.</p><div class=scroll><table>'
                 '<thead><tr><th>Visualping ID</th><th>Page</th><th>URL</th></tr></thead><tbody>')
        for j in sorted(never, key=lambda x: (x["row"] or 0)):
            o.append('<tr><td class=num>%s</td><td>%s</td>'
                     '<td><a href="%s">%s</a></td></tr>'
                     % (j["row"] or "—", e(j["name"]), e(j["loc"]), e(j["loc"][:70])))
        o.append("</tbody></table></div></section>")

    if thin:
        o.append("<section><h2>Low confidence <span class=pill>%d</span></h2>" % len(thin))
        o.append('<p class=note>These fetched without error, but so little text '
                 'came back that a real change would probably go undetected — '
                 'usually a block page or a consent wall stored as content. '
                 'Shown here rather than counted as covered.</p>'
                 '<div class=scroll><table><thead><tr><th>Visualping ID</th><th>Page</th>'
                 '<th class=num>Characters</th></tr></thead><tbody>')
        for j in sorted(thin, key=lambda x: x["chars"]):
            o.append("<tr><td class=num>%s</td><td>%s</td>"
                     "<td class=num>%d</td></tr>"
                     % (j["row"] or "—", e(j["name"]), j["chars"]))
        o.append("</tbody></table></div></section>")

    o.append("<section><h2>All pages watched</h2>")
    o.append('<p class=note>Every source from the Visualping export, keyed by '
             'its Visualping ID so any alert traces straight back to the '
             'export.</p>')
    o.append("<details><summary>Show all %d</summary><div class=scroll>"
             "<table><thead><tr><th>Visualping ID</th><th>Page</th><th>Type</th>"
             "<th class=num>Characters</th><th>Last checked</th></tr></thead>"
             "<tbody>" % len(jobs))
    for j in sorted(jobs, key=lambda x: (x["row"] or 0)):
        o.append('<tr><td class=num>%s</td><td><a href="%s">%s</a></td>'
                 "<td>%s</td><td class=num>%s</td><td>%s</td></tr>"
                 % (j["row"] or "—", e(j["loc"]), e(j["name"]), j["kind"],
                    j.get("chars", "—"), e(uk(j.get("ts")))))
    o.append("</tbody></table></div></details></section>")

    o.append("<footer>Built on <a href='https://github.com/thp/urlwatch'>urlwatch</a> "
             "(BSD-3), installed as a dependency and pinned — so upstream fixes "
             "arrive without us maintaining a fork. This repo holds only the job "
             "list, the configuration, the daily workflow and this page.<br>"
             "Source and run history: <a href='https://github.com/%s'>%s</a>."
             "</footer>" % (e(REPO), e(REPO)))
    o.append("</div></body></html>")

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(o))

    print("Wrote %s: %d pages, %d with snapshots, %d never fetched, "
          "%d failing, %d low-confidence."
          % (OUT, len(jobs), len(seen), len(never), len(failing), len(thin)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
