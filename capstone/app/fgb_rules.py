"""search_rules: retrieval (RAG) over inputs/roe-standing.md, one chunk per rule.

Usage:
    .venv\\Scripts\\python.exe capstone\\app\\fgb_rules.py --rebuild           # build the database
    .venv\\Scripts\\python.exe capstone\\app\\fgb_rules.py "laser elevation"    # try a search

How it works (same approach as weeks 3-4):
  1. roe-standing.md is split into one chunk per rule (ROE-x.y). Each chunk starts with its
     section heading, so it makes sense on its own.
  2. Chunks are embedded with Chroma's built-in embedding model and stored in
     app/chroma_rules (git-ignored). The database is built only when you run --rebuild.
  3. A search returns the closest rules. If the query names rule IDs (e.g. "ROE-5.7"),
     those rules are returned first, exactly.

No Claude call and no API key. Messages go to stderr, because an MCP server uses stdout.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RULES_FILE = HERE.parent / "inputs" / "roe-standing.md"
DB_DIR = HERE / "chroma_rules"
MANIFEST = DB_DIR / "index_manifest.json"
COLLECTION = "fort_gbus_rules"
TOP_K = 4

# Matches both "**ROE-5.7 Elevation limit.** text" and untitled "**ROE-5.1** text".
_RULE = re.compile(r"^\*\*(ROE-\d+\.\d+)(?:\s+(.+?))?\*\*\s*(.*)$")


def _title_from(text: str) -> str:
    """For untitled rules: the first few words of the rule, without Markdown."""
    words = re.sub(r"\*\*|`", "", text).split()
    return " ".join(words[:8]).rstrip(".,;:") + ("..." if len(words) > 8 else "")


class SearchUnavailable(Exception):
    """The database is missing, so no search is possible."""


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def load_rules() -> list[dict]:
    """[{rule_id, title, section, text}] in file order."""
    rules, current, section, sub = [], None, "", ""
    for raw in RULES_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if line.startswith("## "):
            section, sub, current = line[3:].strip(), "", None
            continue
        if line.startswith("### "):
            sub, current = line[4:].strip(), None
            continue
        if line.strip() == "---":
            current = None
            continue
        m = _RULE.match(line.strip())
        if m:
            heading = section + (f" / {sub}" if sub else "")
            title = m.group(2).rstrip(".") if m.group(2) else _title_from(m.group(3))
            current = {"rule_id": m.group(1), "title": title,
                       "section": heading, "lines": [m.group(3)] if m.group(3) else []}
            rules.append(current)
            continue
        if current is not None:
            current["lines"].append(line)
    for r in rules:
        r["text"] = "\n".join(r.pop("lines")).strip()
    return rules


def chunk_text(r: dict) -> str:
    return f"{r['rule_id']} {r['title']}\nSection: {r['section']}\n\n{r['text']}"


def fingerprint() -> list:
    st = RULES_FILE.stat()
    return [st.st_size, int(st.st_mtime)]


def chroma_client():
    import chromadb
    from chromadb.config import Settings
    return chromadb.PersistentClient(path=str(DB_DIR), settings=Settings(anonymized_telemetry=False))


def build_index() -> None:
    import shutil
    rules = load_rules()
    if DB_DIR.exists():
        shutil.rmtree(DB_DIR, ignore_errors=True)
    col = chroma_client().create_collection(COLLECTION, configuration={"hnsw": {"space": "cosine"}})
    col.add(ids=[r["rule_id"] for r in rules], documents=[chunk_text(r) for r in rules],
            metadatas=[{"rule_id": r["rule_id"], "title": r["title"], "section": r["section"]}
                       for r in rules])
    MANIFEST.write_text(json.dumps(fingerprint()), encoding="utf-8")
    log(f"Indexed {len(rules)} rules from {RULES_FILE.name} into {DB_DIR.name}")


_collection = None


def search_rules(query: str, top_k: int = TOP_K) -> dict:
    global _collection
    rules = {r["rule_id"]: r for r in load_rules()}
    exact = [rid for rid in re.findall(r"ROE-\d+\.\d+", query.upper()) if rid in rules]
    results = [{"rule_id": rid, "title": rules[rid]["title"], "section": rules[rid]["section"],
                "match": "exact ID", "text": rules[rid]["text"]} for rid in dict.fromkeys(exact)]

    if not MANIFEST.exists():
        if results:
            return {"results": results}
        raise SearchUnavailable(
            "The rules database has not been built yet. Run: .venv\\Scripts\\python.exe "
            "capstone\\app\\fgb_rules.py --rebuild")
    if _collection is None:
        _collection = chroma_client().get_collection(COLLECTION)
    res = _collection.query(query_texts=[query], n_results=top_k + len(results),
                            include=["metadatas", "distances"])
    for m, d in zip(res["metadatas"][0], res["distances"][0]):
        rid = m["rule_id"]
        if rid in rules and rid not in exact and len(results) < top_k + len(exact):
            results.append({"rule_id": rid, "title": rules[rid]["title"],
                            "section": rules[rid]["section"],
                            "similarity": round(1 - d, 3), "text": rules[rid]["text"]})
    out: dict = {"results": results}
    if json.loads(MANIFEST.read_text(encoding="utf-8")) != fingerprint():
        out["warning"] = ("roe-standing.md changed after the rules database was built; rule text "
                          "shown is current, but ranking may be out of date. Ask for a rebuild.")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Build or search the Fort GBUS rules database.")
    ap.add_argument("query", nargs="?")
    ap.add_argument("--rebuild", action="store_true")
    args = ap.parse_args()
    if not args.rebuild and not args.query:
        ap.error("give a search query, --rebuild, or both")
    if args.rebuild:
        build_index()
    if args.query:
        for r in search_rules(args.query)["results"]:
            score = r.get("similarity", r.get("match"))
            print(f"{r['rule_id']} {r['title']}  ({score})")


if __name__ == "__main__":
    main()
