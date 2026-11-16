"""Check data/orcid/*.json and the publication YAML files against the WORK schema.

usage: python scripts/validate_publications.py
"""

import datetime
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import worklib as w  # noqa: E402

ID_RE = re.compile(r"^(doi:10\.\S+|orcid:\d+|manual:[a-z0-9][a-z0-9-]*)$")
STRINGS = ("title", "container", "volume", "issue", "pages", "publisher", "doi", "url", "lang")


def check_people(people, label, errors):
    if not isinstance(people, list):
        errors.append(f"{label} is not a list")
        return
    for person in people:
        if not isinstance(person, dict) or set(person) != {"family", "given"}:
            errors.append(f"{label} entry {person!r} is not {{family, given}}")
        elif not isinstance(person["family"], str) or not person["family"].strip():
            errors.append(f"{label} entry with empty family name")
        elif not isinstance(person["given"], str):
            errors.append(f"{label} entry with non-string given name")


def check_work(work, where, extra_keys=()):
    errors = []
    if not isinstance(work, dict):
        return [f"{where}: entry is not a mapping"]
    wid = work.get("id")
    where = f"{where} [{wid}]"
    missing = [f for f in w.FIELDS if f != "editors" and f not in work]
    unknown = [k for k in work if k not in w.FIELDS and k not in extra_keys]
    if missing:
        errors.append(f"missing fields {missing}")
    if unknown:
        errors.append(f"unknown fields {unknown}")
    if not isinstance(wid, str) or not ID_RE.match(wid):
        errors.append(f"bad id {wid!r}")
    if work.get("type") not in w.TYPES:
        errors.append(f"bad type {work.get('type')!r}")
    if work.get("status") not in w.STATUSES:
        errors.append(f"bad status {work.get('status')!r}")
    year = work.get("year")
    if not isinstance(year, int) or isinstance(year, bool) or not 1900 <= year <= datetime.date.today().year + 5:
        errors.append(f"bad year {year!r}")
    check_people(work.get("authors"), "authors", errors)
    if "editors" in work:
        check_people(work.get("editors"), "editors", errors)
    if not (work.get("authors") or work.get("editors")):
        errors.append("no authors and no editors")
    for field in STRINGS:
        if field in work and not isinstance(work[field], str):
            errors.append(f"{field} is not a string")
    if not str(work.get("title") or "").strip():
        errors.append("empty title")
    doi = work.get("doi") or ""
    if doi and (doi != doi.lower() or not doi.startswith("10.")):
        errors.append(f"doi {doi!r} is not a lowercased DOI")
    if isinstance(wid, str) and wid.startswith("doi:") and wid != f"doi:{doi}":
        errors.append("id and doi disagree")
    if work.get("url") and not re.match(r"^https?://", work["url"]):
        errors.append(f"url {work['url']!r} is not http(s)")
    if work.get("lang") and not re.fullmatch(r"[a-z]{2,3}", work["lang"]):
        errors.append(f"lang {work['lang']!r} is not a language code")
    return [f"{where}: {e}" for e in errors]


def check_list(works, where, extra_keys=()):
    errors, seen = [], set()
    for index, work in enumerate(works):
        errors += check_work(work, f"{where} #{index + 1}", extra_keys)
        wid = work.get("id") if isinstance(work, dict) else None
        if wid in seen:
            errors.append(f"{where}: duplicate id {wid}")
        seen.add(wid)
    return errors


def main():
    errors, counts = [], {}
    slugs = {m["slug"] for m in w.load_members()}
    for path in sorted(w.ORCID_DIR.glob("*.json")):
        rel = path.relative_to(w.ROOT)
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            errors.append(f"{rel}: invalid JSON ({error})")
            continue
        if set(doc) != {"orcid", "fetched", "works"}:
            errors.append(f"{rel}: top-level keys {sorted(doc)}")
            continue
        if not re.fullmatch(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]", str(doc["orcid"])):
            errors.append(f"{rel}: bad orcid {doc['orcid']!r}")
        try:
            datetime.datetime.fromisoformat(str(doc["fetched"]).replace("Z", "+00:00"))
        except ValueError:
            errors.append(f"{rel}: fetched is not ISO-8601")
        if path.stem not in slugs:
            errors.append(f"{rel}: no member with slug {path.stem}")
        errors += check_list(doc["works"], str(rel))
        counts[str(rel)] = len(doc["works"])
    targets = sorted(w.EXTRA_DIR.glob("*.yaml")) + [w.GROUP_FILE]
    for path in targets:
        if not path.exists():
            continue
        rel = path.relative_to(w.ROOT)
        data = w.load_yaml(path)
        if data is None:
            data = []
        if not isinstance(data, list):
            errors.append(f"{rel}: top level is not a list")
            continue
        if path == w.GROUP_FILE:
            errors += check_list(data, str(rel), extra_keys=("members",))
            for work in data:
                members = work.get("members") if isinstance(work, dict) else None
                if not isinstance(members, list) or not members or set(members) - slugs:
                    errors.append(f"{rel} [{work.get('id') if isinstance(work, dict) else work}]: bad members {members!r}")
        else:
            if path.stem not in slugs:
                errors.append(f"{rel}: no member with slug {path.stem}")
            errors += check_list(data, str(rel))
        counts[str(rel)] = len(data)
    if w.REJECTED_FILE.exists():
        rel = w.REJECTED_FILE.relative_to(w.ROOT)
        data = w.load_yaml(w.REJECTED_FILE) or []
        if not isinstance(data, list):
            errors.append(f"{rel}: top level is not a list")
            data = []
        for entry in data:
            if not isinstance(entry, dict) or not ID_RE.match(str(entry.get("id") or "")):
                errors.append(f"{rel}: entry {entry!r} needs an id")
            elif not str(entry.get("reason") or "").strip():
                errors.append(f"{rel} [{entry['id']}]: no reason")
            elif set(entry) - {"id", "title", "reason"}:
                errors.append(f"{rel} [{entry['id']}]: unknown fields {sorted(set(entry) - {'id', 'title', 'reason'})}")
        counts[str(rel)] = len(data)
    for name, count in counts.items():
        print(f"{name}: {count} entries")
    for error in errors:
        print(f"ERROR {error}")
    print(f"{len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
