"""Propose members' works for the curated group list.

usage: python scripts/orcid_candidates.py [--since YEAR] [--output FILE] [--body FILE] [--append-to-group]
       python scripts/orcid_candidates.py reject ID --reason TEXT
"""

import argparse
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import worklib as w  # noqa: E402


def entry_keys(entry):
    """DOI or normalised title, the keys the group list and rejected list are matched on."""
    keys = set()
    if isinstance(entry, str):
        entry = {"id": entry}
    if not isinstance(entry, dict):
        return keys
    wid = str(entry.get("id") or "").strip()
    doi = w.norm_doi(entry.get("doi")) or w.norm_doi(wid[4:] if wid.lower().startswith("doi:") else wid)
    if doi:
        keys.add("doi:" + doi)
    if wid and not doi:
        keys.add("id:" + wid.lower())
    title = w.norm_title(entry.get("title"))
    if title:
        keys.add("title:" + title)
    return keys


def candidate_keys(work):
    keys = entry_keys(work)
    keys.add("id:" + str(work.get("id") or "").lower())
    return keys


def load_list(path):
    data = w.load_yaml(path)
    if data is None:
        return []
    if isinstance(data, dict):
        for key in ("works", "publications", "items"):
            if isinstance(data.get(key), list):
                return data[key]
        return []
    return data if isinstance(data, list) else []


def collect(members):
    """All members' works, merged across members by DOI or title and year; extra wins."""
    pool, index = [], {}
    sources = []
    for member in members:
        path = w.ORCID_DIR / f"{member['slug']}.json"
        if path.exists():
            doc = json.loads(path.read_text(encoding="utf-8"))
            sources += [(work, f"orcid:{member['slug']}", 0) for work in doc.get("works", [])]
        extra = w.EXTRA_DIR / f"{member['slug']}.yaml"
        sources += [(work, f"extra:{member['slug']}", 1) for work in load_list(extra) if isinstance(work, dict)]
    for work, origin, rank in sources:
        keys = w.work_keys(work) | ({f"id:{work['id']}"} if work.get("id") else set())
        holder = next((index[k] for k in sorted(keys) if k in index), None)
        if holder is None:
            holder = {"work": work, "rank": rank, "found_in": set()}
            pool.append(holder)
        elif rank > holder["rank"]:
            holder["work"], holder["rank"] = work, rank
        holder["found_in"].add(origin)
        for key in keys | w.work_keys(holder["work"]) | ({f"id:{holder['work']['id']}"} if holder["work"].get("id") else set()):
            index[key] = holder
    return pool


def propose(members, since):
    known = set()
    for entry in load_list(w.GROUP_FILE):
        known |= entry_keys(entry)
    for entry in load_list(w.REJECTED_FILE):
        known |= entry_keys(entry)
    out = []
    for holder in collect(members):
        work = holder["work"]
        if not isinstance(work.get("year"), int) or work["year"] < since:
            continue
        slugs = w.members_in(work, members)
        if not slugs or candidate_keys(work) & known:
            continue
        item = w.ordered(work)
        item["members"] = slugs
        out.append((item, sorted(holder["found_in"])))
    out.sort(key=lambda pair: w.sort_key(pair[0]))
    return out


def body_markdown(candidates, since):
    today = datetime.date.today().isoformat()
    lines = [f"Works from {since} onward with at least one member as author, found in the members' "
             f"ORCID records and extra files on {today}, that are neither in "
             "`data/publications/group.yaml` nor in `data/publications/rejected.yaml`.",
             "",
             "This branch appends them to `group.yaml`. Before merging: delete from `group.yaml` every "
             "entry that should not be on the group list and add it to `rejected.yaml` with a reason, "
             "so it is not proposed again. Merging accepts what remains. The next weekly run rebuilds "
             "this branch unless it carries commits made by a person, in which case it is left alone.",
             ""]
    for number, (work, found_in) in enumerate(candidates, 1):
        lines += [f"{number}. {w.apa_es(work)}",
                  f"   id `{work['id']}`; members: {', '.join(work['members'])}; source: {', '.join(found_in)}",
                  "   ```yaml",
                  f"   - id: {work['id']}",
                  f"     title: {json.dumps(work['title'], ensure_ascii=False)}",
                  "     reason: ",
                  "   ```"]
    return "\n".join(lines) + "\n"


def append_to_group(candidates):
    data = w.load_yaml(w.GROUP_FILE)
    items = [work for work, _ in candidates]
    if data is None or isinstance(data, list):
        text = w.GROUP_FILE.read_text(encoding="utf-8") if w.GROUP_FILE.exists() else ""
        if text.strip() in ("[]", ""):
            text = ""
        elif not text.endswith("\n"):
            text += "\n"
        w.GROUP_FILE.parent.mkdir(parents=True, exist_ok=True)
        w.GROUP_FILE.write_text(text + w.dump_yaml(items), encoding="utf-8")
        return
    key = next(k for k in ("works", "publications", "items") if isinstance(data.get(k), list))
    data[key] += items
    w.GROUP_FILE.write_text(w.dump_yaml(data), encoding="utf-8")


def reject(work_id, reason, title):
    entries = load_list(w.REJECTED_FILE)
    if any(entry_keys(e) & entry_keys({"id": work_id}) for e in entries):
        print(f"{work_id} is already in {w.REJECTED_FILE.name}")
        return 0
    entries.append({"id": work_id, "title": title or "", "reason": reason})
    w.REJECTED_FILE.write_text(w.dump_yaml(entries), encoding="utf-8")
    print(f"{work_id} added to {w.REJECTED_FILE.name}")
    return 0


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "reject":
        parser = argparse.ArgumentParser(prog="orcid_candidates.py reject")
        parser.add_argument("id")
        parser.add_argument("--reason", required=True)
        parser.add_argument("--title", default="")
        args = parser.parse_args(sys.argv[2:])
        return reject(args.id, args.reason.strip(), args.title.strip())

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", type=int, default=2024, help="first year considered (default 2024)")
    parser.add_argument("--output", type=Path, help="write the candidates as YAML here")
    parser.add_argument("--body", type=Path, help="write a Markdown pull-request body here")
    parser.add_argument("--append-to-group", action="store_true", help="append the candidates to group.yaml")
    args = parser.parse_args()

    members = w.load_members()
    candidates = propose(members, args.since)
    print(f"{len(candidates)} candidate(s) from {args.since} onward")
    for work, found_in in candidates:
        print(f"  {work['year']} {work['id']}  [{', '.join(work['members'])}]  {work['title'][:70]}")
    if args.output:
        args.output.write_text(w.dump_yaml([work for work, _ in candidates]), encoding="utf-8")
    if args.body:
        args.body.write_text(body_markdown(candidates, args.since), encoding="utf-8")
    if args.append_to_group and candidates:
        append_to_group(candidates)
    return 0


if __name__ == "__main__":
    sys.exit(main())
