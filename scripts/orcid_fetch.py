"""Harvest each member's public ORCID works into data/orcid/<slug>.json.

usage: python scripts/orcid_fetch.py [--only SLUG ...] [--no-enrich]
"""

import argparse
import datetime
import json
import os
import re
import sys
import unicodedata
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import worklib as w  # noqa: E402

ORCID_API = "https://pub.orcid.org/v3.0"
BULK_SIZE = 100

ORCID_TYPES = {
    "journal-article": "article", "book-chapter": "chapter", "book": "book",
    "edited-book": "edited-book", "book-review": "review", "review": "review",
    "conference-paper": "conference-paper", "conference-abstract": "presentation",
    "conference-presentation": "presentation", "lecture-speech": "presentation",
    "public-speech": "presentation", "conference-poster": "poster", "data-set": "dataset",
    "software": "software", "report": "report", "working-paper": "report",
    "dissertation-thesis": "thesis", "encyclopedia-entry": "chapter",
    "dictionary-entry": "chapter", "preprint": "other", "magazine-article": "other",
    "newspaper-article": "other", "newsletter-article": "other", "blog-post": "other",
    "translation": "other", "journal-issue": "other", "website": "other",
    "online-resource": "other", "conference-proceedings": "other",
}
CROSSREF_TYPES = {
    "journal-article": "article", "book-chapter": "chapter", "book-section": "chapter",
    "book-part": "chapter", "reference-entry": "chapter", "book": "book",
    "monograph": "book", "reference-book": "book", "edited-book": "edited-book",
    "proceedings-article": "conference-paper", "dataset": "dataset", "report": "report",
    "report-component": "report", "dissertation": "thesis", "peer-review": "review",
}
DATACITE_TYPES = {
    "Dataset": "dataset", "Software": "software", "JournalArticle": "article",
    "BookChapter": "chapter", "Book": "book", "Report": "report", "Dissertation": "thesis",
    "ConferencePaper": "conference-paper", "PeerReview": "review",
}
PREPRINT_PREFIXES = ("10.31234/", "10.31219/", "10.31235/", "10.35542/", "10.1101/",
                     "10.21203/", "10.2139/", "10.48550/", "10.20944/", "10.32942/")
REVIEW_TITLE = re.compile(r"^(resena|review of|book review|recension|compte rendu)\b|\breview by\b")
PLACEHOLDER_TITLES = {"", "pendingpublications", "pending publications"}

STOPWORDS = {
    "es": {"el", "los", "las", "del", "y", "en", "una", "para", "con", "por", "sobre", "como",
           "que", "su", "sus", "al", "entre", "desde", "lengua", "estudio", "hacia"},
    "en": {"the", "of", "and", "in", "an", "for", "with", "on", "to", "from", "by", "language",
           "study", "speech", "review", "as", "is", "are", "what", "why", "how"},
    "fr": {"le", "les", "des", "du", "et", "une", "pour", "dans", "sur", "au", "aux", "nom",
           "propre", "est", "ou", "comme"},
    "it": {"il", "lo", "gli", "della", "delle", "degli", "e", "per", "nella", "lingua", "che"},
    "pt": {"o", "os", "da", "do", "das", "dos", "em", "um", "uma", "com", "não", "na"},
}
SIGNALS = {"es": r"[ñ¿¡]|ci[oó]n\b|[áíóú]", "fr": r"[èêëçœâû]|\b[ldjnqs]'", "pt": r"[ãõ]|ção\b"}


def guess_lang(title):
    text = str(title or "").lower()
    words = re.findall(r"[a-zà-ÿ]+", text)
    scores = {lang: sum(word in stops for word in words) for lang, stops in STOPWORDS.items()}
    for lang, pattern in SIGNALS.items():
        scores[lang] += 2 * len(re.findall(pattern, text))
    ranked = sorted(scores.items(), key=lambda item: -item[1])
    if ranked[0][1] < 1 or ranked[0][1] == ranked[1][1]:
        return ""
    return ranked[0][0]


def join_subtitle(title, subtitle):
    if not subtitle or w.norm_title(subtitle) in w.norm_title(title):
        return title
    lang_title, lang_sub = guess_lang(title), guess_lang(subtitle)
    if lang_title and lang_sub and lang_title != lang_sub:
        return title
    return f"{title} {subtitle}" if title.rstrip()[-1:] in "?!.:" else f"{title}: {subtitle}"


def value(node, *path):
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def orcid_get(path, token):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return w.get_json(ORCID_API + path, headers=headers, min_interval=0.25)


ACCENTS = {"'": "\u0301", "`": "\u0300", "^": "\u0302", '"': "\u0308", "~": "\u0303",
           "=": "\u0304", ".": "\u0307", "c": "\u0327", "v": "\u030c", "u": "\u0306"}
GARBLED = re.compile(r"[\u0131\u01d7-\u01dc\u0300-\u036f]")


def delatex(text):
    text = re.sub(r"\\([&%_$#])", r"\1", text)
    text = re.sub(r"\\([ijlo])\b\s*", lambda m: {"i": "ı", "j": "ȷ", "l": "ł", "o": "ø"}[m.group(1)], text)

    def accent(match):
        base = match.group(2).replace("ı", "i").replace("ȷ", "j")
        return unicodedata.normalize("NFC", base + ACCENTS[match.group(1)])

    text = re.sub(r"\\([\'`^\"~=.]|[cvu](?=[\s{]))\s*\{?\s*([A-Za-zıȷ])\s*\}?", accent, text)
    text = text.replace("{", "").replace("}", "").replace("``", "“").replace("''", "”")
    return " ".join(text.split())


def bibtex_fields(citation):
    fields, text = {}, citation or ""
    if not text.lstrip().startswith("@"):
        return fields
    pos = text.find(",") + 1
    pattern = re.compile(r"\s*,?\s*([A-Za-z][\w-]*)\s*=\s*")
    while pos and pos < len(text):
        match = pattern.match(text, pos)
        if not match:
            break
        key, pos = match.group(1).lower(), match.end()
        if pos >= len(text):
            break
        if text[pos] in "{\"":
            close = "}" if text[pos] == "{" else "\""
            depth, end = 0, pos
            while end < len(text):
                char = text[end]
                if char == "{":
                    depth += 1
                elif char == "}" and close == "}":
                    depth -= 1
                    if depth == 0:
                        break
                elif char == "\"" and close == "\"" and end > pos and depth == 0:
                    break
                end += 1
            raw, pos = text[pos + 1:end], end + 1
        else:
            end = re.search(r"[,}\n]|$", text[pos:]).start() + pos
            raw, pos = text[pos:end], end
        fields[key] = delatex(raw)
    return fields


def bib_people(text, members):
    people = []
    for name in re.split(r"\s+and\s+", text or ""):
        name = " ".join(name.split())
        if not name or name.lower() == "others":
            continue
        if "," in name:
            family, given = (part.strip() for part in name.split(",", 1))
            folded = w.fold(f"{given} {family}").replace("-", " ")
            member = next((m for m in members if folded in m["name_forms"]), None)
            person = ({"family": member["family"], "given": member["given"]} if member else
                      {"family": w.smart_case(family), "given": w.smart_case(given)})
        else:
            person = w.split_name(name, members)
        people.append(person)
    return people


def crossref_people(people):
    out = []
    for person in people or []:
        family = person.get("family") or person.get("name") or ""
        out.append({"family": w.smart_case(family.strip()),
                    "given": w.smart_case((person.get("given") or "").strip())})
    return [p for p in out if p["family"]]


def lookup_doi(doi):
    """Registrar metadata for a DOI (Crossref, then DataCite); None if not found."""
    quoted = urllib.parse.quote(doi, safe="/:;()")
    try:
        message = w.get_json(f"https://api.crossref.org/works/{quoted}", min_interval=0.35)["message"]
    except w.HttpError as error:
        if error.status != 404:
            raise
        message = None
    if message:
        relation = message.get("relation") or {}
        issued = value(message, "issued", "date-parts") or [[None]]
        title = join_subtitle(" ".join((message.get("title") or [""])[:1]),
                              " ".join((message.get("subtitle") or [""])[:1]))
        return {
            "source": "crossref",
            "type": CROSSREF_TYPES.get(message.get("type"), ""),
            "is_preprint": message.get("type") == "posted-content" or message.get("subtype") == "preprint",
            "authors": crossref_people(message.get("author")),
            "editors": crossref_people(message.get("editor")),
            "title": w.strip_tags(title),
            "container": w.strip_tags((message.get("container-title") or [""])[0]),
            "volume": str(message.get("volume") or ""),
            "issue": str(message.get("issue") or ""),
            "pages": str(message.get("page") or "").replace("--", "-"),
            "publisher": message.get("publisher") or "",
            "year": issued[0][0] if issued and issued[0] else None,
            "lang": (message.get("language") or "").split("-")[0].lower(),
            "preprint_of": {w.norm_doi(r.get("id")) for r in relation.get("is-preprint-of", [])},
            "has_preprint": {w.norm_doi(r.get("id")) for r in relation.get("has-preprint", [])},
            "orcids": {re.sub(r".*/", "", a.get("ORCID") or "") for a in message.get("author") or []},
        }
    try:
        attrs = w.get_json(f"https://api.datacite.org/dois/{quoted}", min_interval=0.35)["data"]["attributes"]
    except w.HttpError as error:
        if error.status != 404:
            raise
        return lookup_csl(doi, quoted)
    people = []
    for creator in attrs.get("creators") or []:
        if creator.get("familyName"):
            people.append({"family": creator["familyName"].strip(), "given": (creator.get("givenName") or "").strip()})
        elif creator.get("name"):
            people.append(w.split_name(creator["name"]))
    related = attrs.get("relatedIdentifiers") or []
    general = value(attrs, "types", "resourceTypeGeneral") or ""
    publisher = attrs.get("publisher") or ""
    if isinstance(publisher, dict):
        publisher = publisher.get("name") or ""
    return {
        "source": "datacite",
        "type": DATACITE_TYPES.get(general, ""),
        "is_preprint": general == "Preprint",
        "authors": people,
        "editors": [],
        "title": w.strip_tags(((attrs.get("titles") or [{}])[0]).get("title")),
        "container": "",
        "volume": "", "issue": "", "pages": "",
        "publisher": publisher,
        "year": int(attrs["publicationYear"]) if str(attrs.get("publicationYear") or "").isdigit() else None,
        "lang": (attrs.get("language") or "").split("-")[0].lower(),
        "preprint_of": {w.norm_doi(r.get("relatedIdentifier")) for r in related
                        if r.get("relationType") == "IsPreprintOf"},
        "has_preprint": {w.norm_doi(r.get("relatedIdentifier")) for r in related
                         if r.get("relationType") == "HasPreprint"},
        "orcids": {re.sub(r".*/", "", n.get("nameIdentifier") or "") for c in attrs.get("creators") or []
                   for n in c.get("nameIdentifiers") or []},
    }


CSL_TYPES = {"article-journal": "article", "chapter": "chapter", "book": "book",
             "paper-conference": "conference-paper", "dataset": "dataset", "report": "report",
             "thesis": "thesis", "review": "review", "review-book": "review", "software": "software"}


def lookup_csl(doi, quoted):
    """Any other registration agency (mEDRA, JaLC, ...) through doi.org content negotiation."""
    try:
        csl = w.get_json(f"https://doi.org/{quoted}", headers={"Accept": "application/vnd.citationstyles.csl+json"},
                         min_interval=0.35)
    except w.HttpError as error:
        if error.status == 404:
            return None
        raise
    issued = value(csl, "issued", "date-parts") or [[None]]
    container = csl.get("container-title") or ""
    return {
        "source": "doi.org",
        "type": CSL_TYPES.get(csl.get("type"), ""),
        "is_preprint": csl.get("type") in ("posted-content", "post") or csl.get("subtype") == "preprint",
        "authors": crossref_people(csl.get("author")),
        "editors": crossref_people(csl.get("editor")),
        "title": w.strip_tags(csl.get("title") if isinstance(csl.get("title"), str) else " ".join(csl.get("title") or [])),
        "container": w.strip_tags(container if isinstance(container, str) else " ".join(container[:1])),
        "volume": str(csl.get("volume") or ""),
        "issue": str(csl.get("issue") or ""),
        "pages": str(csl.get("page") or "").replace("\u2013", "-").replace("--", "-"),
        "publisher": csl.get("publisher") or "",
        "year": issued[0][0] if issued and issued[0] else None,
        "lang": str(csl.get("language") or "").split("-")[0].lower(),
        "preprint_of": set(), "has_preprint": set(), "orcids": set(),
    }


def orcid_people(contributors, members):
    authors, editors = [], []
    for contributor in contributors or []:
        name = value(contributor, "credit-name", "value")
        if not name:
            continue
        role = (value(contributor, "contributor-attributes", "contributor-role") or "author").lower()
        if role in ("chair-or-translator", "assignee"):
            continue
        person = w.split_name(name, members)
        (editors if role == "editor" else authors).append(person)
    return authors, editors


def first(records, *path):
    for record in records:
        found = value(record, *path)
        if found not in (None, "", [], {}):
            return found
    return None


def group_doi(group):
    for ext in value(group, "external-ids", "external-id") or []:
        if ext.get("external-id-type") == "doi" and ext.get("external-id-relationship") == "self":
            doi = w.norm_doi(ext.get("external-id-value"))
            if doi:
                return doi
    return ""


def build_work(group, records, members, previous, enrich):
    preferred = records[0]
    title = unicodedata.normalize("NFC", w.strip_tags(first(records, "title", "title", "value")))
    title = join_subtitle(title, w.strip_tags(first(records, "title", "subtitle", "value")))
    orcid_type = (preferred.get("type") or "").lower()
    year = first(records, "publication-date", "year", "value")
    doi = group_doi(group)
    contributors = first(records, "contributors", "contributor")
    authors, editors = orcid_people(contributors, members)
    citation = next((value(r, "citation", "citation-value") for r in records
                     if str(value(r, "citation", "citation-value") or "").lstrip().startswith("@")), "")
    bib = bibtex_fields(citation)
    if not authors and not editors:
        authors = bib_people(bib.get("author"), members)
        editors = bib_people(bib.get("editor"), members)
    if bib.get("title") and (not title or GARBLED.search(title)):
        title = bib["title"]
    container = unicodedata.normalize("NFC", w.strip_tags(first(records, "journal-title", "value")))
    bib_container = bib.get("journal") or bib.get("booktitle") or ""
    if bib_container and (not container or GARBLED.search(container)):
        container = bib_container
    url = first(records, "url", "value") or ""
    if re.match(r"https?://(dx\.)?doi\.org/", url, re.I):
        url = ""
    work = {
        "id": f"doi:{doi}" if doi else f"orcid:{preferred.get('put-code')}",
        "type": ORCID_TYPES.get(orcid_type, ""),
        "year": int(year) if str(year or "").isdigit() else None,
        "status": "published",
        "authors": authors,
        "editors": editors,
        "title": title,
        "container": container,
        "volume": bib.get("volume", ""),
        "issue": bib.get("number", ""),
        "pages": bib.get("pages", "").replace("--", "-"),
        "publisher": bib.get("publisher", ""),
        "doi": doi,
        "url": url,
        "lang": (first(records, "language-code") or "").split("_")[0].lower(),
    }
    meta = None
    if doi and enrich:
        try:
            meta = lookup_doi(doi)
        except w.HttpError as error:
            if work["id"] in previous:
                w.warn(f"DOI lookup failed for {doi} ({error}); previous record reused")
                return dict(previous[work["id"]]), {"reused": True}
            w.warn(f"DOI lookup failed for {doi} ({error}); ORCID metadata only")
    info = {"preprint": orcid_type == "preprint" or doi.startswith(PREPRINT_PREFIXES),
            "preprint_of": set(), "has_preprint": set(), "orcids": set()}
    if meta:
        info["preprint"] = info["preprint"] or meta["is_preprint"]
        for key in ("preprint_of", "has_preprint", "orcids"):
            info[key] = {x for x in meta[key] if x}
        if meta["authors"]:
            work["authors"] = [w.canonical(p, members) for p in meta["authors"]]
        if meta["editors"]:
            work["editors"] = [w.canonical(p, members) for p in meta["editors"]]
        for field in ("title", "container", "year", "lang"):
            if not work[field] and meta[field]:
                work[field] = meta[field]
        for field in ("volume", "issue", "pages"):
            if meta[field]:
                work[field] = meta[field]
        if not work["type"]:
            work["type"] = meta["type"]
        if meta["publisher"]:
            work["publisher"] = meta["publisher"]
    if not work["type"]:
        work["type"] = "other"
    if work["type"] in ("article", "other") and REVIEW_TITLE.search(w.norm_title(work["title"])):
        work["type"] = "review"
    if work["type"] in ("article", "review"):
        work["publisher"] = ""
    work["lang"] = w.norm_lang(work["lang"]) or guess_lang(work["title"])
    this_year = datetime.date.today().year
    if work["year"] and work["year"] > this_year:
        work["status"] = "forthcoming"
    return work, info


def completeness(work, info, orcid):
    filled = sum(bool(work.get(f)) for f in ("container", "volume", "issue", "pages", "doi"))
    return (orcid in info.get("orcids", set()), bool(work.get("doi")), filled, str(work["id"]))


def merge_versions(entries, orcid):
    """Drop preprints that have a published version, then duplicates by DOI or title and year."""
    published = [e for e in entries if not e[1].get("preprint")]
    by_doi = {e[0]["doi"]: e for e in published if e[0]["doi"]}
    by_title = {}
    for e in published:
        by_title.setdefault(w.norm_title(e[0]["title"]), []).append(e)
    kept, merged = [], 0
    for work, info in entries:
        if info.get("preprint"):
            target = next((by_doi[d] for d in info.get("preprint_of", ()) if d in by_doi), None)
            if not target:
                target = next((p for p in published if work["doi"] and work["doi"] in p[1].get("has_preprint", ())), None)
            if not target:
                target = next((p for p in by_title.get(w.norm_title(work["title"]), [])
                               if work["year"] and p[0]["year"] and 0 <= p[0]["year"] - work["year"] <= 1), None)
            if target:
                merged += 1
                continue
        kept.append((work, info))
    best, entries_out, duplicates = {}, [], 0
    for work, info in kept:
        keys = w.work_keys(work)
        holder = next((best[k] for k in sorted(keys) if k in best), None)
        if holder is None:
            holder = [work, info]
            entries_out.append(holder)
        else:
            duplicates += 1
            if completeness(work, info, orcid) > completeness(holder[0], holder[1], orcid):
                holder[0], holder[1] = work, info
        for key in keys | w.work_keys(holder[0]):
            best[key] = holder
    return [e[0] for e in entries_out], merged, duplicates


def harvest(member, token, previous, enrich):
    orcid = member["orcid"]
    summary = orcid_get(f"/{orcid}/works", token)
    groups = summary.get("group") or []
    put_codes = [s["put-code"] for g in groups for s in g.get("work-summary") or []]
    details = {}
    for start in range(0, len(put_codes), BULK_SIZE):
        chunk = put_codes[start:start + BULK_SIZE]
        bulk = orcid_get(f"/{orcid}/works/{','.join(str(p) for p in chunk)}", token)
        for item in bulk.get("bulk") or []:
            if "work" in item:
                details[item["work"]["put-code"]] = item["work"]
    stats = {"groups": len(groups), "put_codes": len(put_codes), "dropped": [], "merged": 0, "duplicates": 0}
    entries = []
    for group in groups:
        summaries = group.get("work-summary") or []
        if not summaries:
            continue
        records = [details.get(s["put-code"], s) for s in summaries]
        work, info = build_work(group, records, [member] + MEMBERS, previous, enrich)
        if w.norm_title(work["title"]) in PLACEHOLDER_TITLES or not (work["authors"] or work["editors"]):
            stats["dropped"].append(f"{work['id']} {work['title'][:60]!r}")
            continue
        entries.append((work, info))
    works, stats["merged"], stats["duplicates"] = merge_versions(entries, orcid)
    return sorted((w.ordered(x) for x in works), key=w.sort_key), stats


def write_if_changed(path, orcid, works, previous_doc):
    if previous_doc and previous_doc.get("orcid") == orcid and previous_doc.get("works") == works:
        return False
    stamp = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    doc = {"orcid": orcid, "fetched": stamp, "works": works}
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


MEMBERS = []


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="*", default=[], help="member slugs to fetch")
    parser.add_argument("--no-enrich", action="store_true", help="skip Crossref and DataCite")
    args = parser.parse_args()

    token = os.environ.get("ORCID_TOKEN", "").strip()
    MEMBERS.extend(w.load_members())
    w.ORCID_DIR.mkdir(parents=True, exist_ok=True)
    print(f"ORCID access: {'registered client token' if token else 'anonymous'}")
    failures = 0
    for member in MEMBERS:
        slug, orcid = member["slug"], member["orcid"]
        if args.only and slug not in args.only:
            continue
        if not re.fullmatch(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]", orcid):
            print(f"{slug}: no ORCID iD, skipped")
            continue
        path = w.ORCID_DIR / f"{slug}.json"
        previous_doc = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        previous = {x["id"]: x for x in (previous_doc or {}).get("works", [])}
        try:
            works, stats = harvest(member, token, previous, not args.no_enrich)
        except w.HttpError as error:
            failures += 1
            w.warn(f"{slug}: ORCID fetch failed ({error}); previous file kept")
            continue
        if not works and previous:
            failures += 1
            w.warn(f"{slug}: ORCID returned no works but {len(previous)} were stored; previous file kept")
            continue
        changed = write_if_changed(path, orcid, works, previous_doc)
        print(f"{slug}: {stats['groups']} groups, {stats['put_codes']} put-codes, {len(works)} works "
              f"({stats['merged']} preprints merged, {stats['duplicates']} duplicates merged, "
              f"{len(stats['dropped'])} placeholders dropped){' written' if changed else ' unchanged'}")
        for dropped in stats["dropped"]:
            print(f"    dropped: {dropped}")
    if failures:
        w.warn(f"{failures} member(s) not updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
