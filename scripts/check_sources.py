"""Watch the Home Office asylum summary-table listing without adopting it."""
import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WATCH = ROOT / "sources" / "watch.json"
USER_AGENT = "uk-asylum-source-watch/1.0 (+https://github.com/aloysius109/uk-asylum)"
TIMEOUT = 90


def read(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def names(text, pattern):
    files, releases = set(), set()
    for match in re.finditer(pattern, text, flags=re.IGNORECASE):
        files.add(match.group(0))
        if match.groups():
            releases.add(match.group(1).lower())
    return sorted(files), sorted(releases)


def check_links(source, status, body):
    if status != 200:
        return "unreachable", f"HTTP {status} for the Home Office listing page.", {}
    files, releases = names(body.decode("utf-8", "replace"), source["pattern"])
    if not files:
        return "unreachable", "The listing page no longer contains a matching asylum-summary workbook link.", {}
    observed = {"files": files}
    if releases:
        observed["latest_release"] = releases[-1]
    added = [name for name in files if name not in source.get("files", [])]
    removed = [name for name in source.get("files", []) if name not in files]
    latest = observed.get("latest_release")
    notes = []
    if latest and latest != source.get("latest_release"):
        notes.append(f"New release `{latest}` listed; recorded release is `{source.get('latest_release')}`.")
    if added:
        notes.append("New workbook link(s): " + ", ".join(f"`{name}`" for name in added[:8]) + (" …" if len(added) > 8 else "."))
    if removed:
        notes.append("Previously listed workbook link(s) removed: " + ", ".join(f"`{name}`" for name in removed[:8]) + (" …" if len(removed) > 8 else "."))
    if notes:
        return "changed", " ".join(notes), observed
    return "unchanged", f"{len(files)} asylum-summary workbook link(s) listed; latest is `{latest}`.", observed


def fingerprint(drift):
    state = ";".join(sorted(f"{result['id']}:{result['state']}" for result in drift))
    return hashlib.sha256(state.encode("utf-8")).hexdigest()[:12]


def inspect(source):
    result = {"id": source["id"], "label": source["label"], "url": source["url"]}
    try:
        status, body = read(source["url"])
    except Exception as error:  # DNS, TLS, timeout, connection reset
        return {**result, "state": "unreachable", "detail": f"Could not be fetched: {error}", "observed": {}}
    state, detail, observed = check_links(source, status, body)
    return {**result, "state": state, "detail": detail, "observed": observed}


def report_markdown(results):
    stamp = datetime.now(timezone.utc).strftime("%d %B %Y")
    unchanged = [result for result in results if result["state"] == "unchanged"]
    changed = [result for result in results if result["state"] == "changed"]
    unreachable = [result for result in results if result["state"] == "unreachable"]
    lines = [f"## UK asylum source watch — {stamp}", "", f"{len(unchanged)} of {len(results)} watched sources unchanged.", ""]
    for heading, group in (("Changed upstream", changed), ("Could not be checked", unreachable)):
        if group:
            lines.append(f"### {heading}")
            for result in group:
                lines.extend([f"- **{result['label']}** — {result['detail']}", f"  <{result['url']}>"])
            lines.append("")
    if unchanged:
        lines.extend(["### Unchanged", ""])
        lines.extend(f"- {result['label']} — {result['detail']}" for result in unchanged)
        lines.append("")
    if changed or unreachable:
        lines.extend([
            "### What this means", "",
            "The report has not been changed. A new or unavailable source requires review before adoption.",
            "Replace the saved workbook and update `data/raw/source.json` only after deciding to adopt it,",
            "then rerun `python scripts/analyze.py`, revise `index.qmd`, run the checks, render and review,",
            "and re-baseline with `python scripts/check_sources.py --update`. The watcher never downloads",
            "data into the report or publishes a new edition.", "",
        ])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true", help="Re-baseline the listing after deliberately adopting a release")
    parser.add_argument("--strict", action="store_true", help="Exit 1 when the listing differs or cannot be checked")
    parser.add_argument("--report", type=Path, help="Also write the Markdown report to this path")
    args = parser.parse_args()

    watch = json.loads(WATCH.read_text(encoding="utf-8"))
    results = [inspect(source) for source in watch["sources"]]
    drift = [result for result in results if result["state"] != "unchanged"]
    report = report_markdown(results)
    if drift:
        report += f"\n<!-- source-watch:{fingerprint(drift)} -->\n"
    print(report)

    if args.report:
        args.report.write_text(report + "\n", encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(report + "\n")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"drift={'true' if drift else 'false'}\n")

    if args.update:
        observed = {result["id"]: result for result in results}
        for source in watch["sources"]:
            result = observed[source["id"]]
            if result["state"] == "unreachable":
                print(f"Not re-baselining {source['id']}: it could not be checked.", file=sys.stderr)
                continue
            source.update(result["observed"])
        watch["checked_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        WATCH.write_text(json.dumps(watch, indent=2) + "\n", encoding="utf-8")
        print("Re-baselined sources/watch.json.")

    if drift and args.strict:
        sys.exit(1)


if __name__ == "__main__":
    main()