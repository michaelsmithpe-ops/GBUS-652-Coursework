"""Search an organization's HR documents (adapted from week-03/ask.py).

Usage (run from the top of the repository):
    .venv\\Scripts\\python.exe week-04\\hr_search.py --rebuild          # (re)build the database
    .venv\\Scripts\\python.exe week-04\\hr_search.py "jury duty pay"    # try a search
    .venv\\Scripts\\python.exe week-04\\hr_search.py --org ridgeline-hotels --rebuild "borrow PTO"

--org names the organization folder (default week-04/hartwell-hr); see hr_org.py.

How it works (same approach as week 3):
  1. Each HTML file in <org>/hr-docs is split into one chunk per <h2>
     section. Every chunk starts with the document title, section heading and
     source file, so it makes sense on its own.
  2. The chunks are embedded with Chroma's built-in embedding model and stored
     in the organization's own database (git-ignored): week-04/chroma_db for
     hartwell-hr, week-04/chroma_db-<org> for any other. A database is only
     built or rebuilt when you run --rebuild.
  3. A search returns the 4 most similar chunks.

There is no Claude call here: whoever calls the search (Claude Code, or an
agent) writes the answer. No API key is needed.

Messages go to stderr, never stdout, because an MCP server uses stdout to talk
to its client.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import sys
from pathlib import Path

import hr_org

HERE = Path(__file__).resolve().parent             # .../GBUS-652-Coursework/week-04

# Set by use_org(); hartwell-hr until then.
ORG_DIR = hr_org.DEFAULT_ORG.resolve()
DOCS_DIR = ORG_DIR / "hr-docs"
DB_DIR = HERE / "chroma_db"
MANIFEST = DB_DIR / "index_manifest.json"          # which files the index was built from
COLLECTION = "hr_documents"
TOP_K = 4
MAX_CHUNK_CHARS = 1800                             # longer sections are split at paragraph breaks


class SearchUnavailable(Exception):
    """The database is missing, so no search is possible."""


def use_org(org: Path) -> None:
    """Point searches and --rebuild at this organization's documents and database."""
    global ORG_DIR, DOCS_DIR, DB_DIR, MANIFEST, _collection
    ORG_DIR = org
    DOCS_DIR = org / "hr-docs"
    DB_DIR = hr_org.db_dir(org)
    MANIFEST = DB_DIR / "index_manifest.json"
    _collection = None


def org_arg() -> str:
    """How to name the current organization on a command line ('' for the default)."""
    return "" if ORG_DIR == hr_org.DEFAULT_ORG.resolve() else f" --org {ORG_DIR.name}"


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("­", "")).strip()


# ---------------------------------------------------------------------------
# Loading and chunking (HTML only; the HR documents are all HTML)
# ---------------------------------------------------------------------------

def load_html(path: Path) -> tuple[str, str, list[tuple[str, list[str]]]]:
    """Return (title, meta line, [(section heading, paragraphs), ...])."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "html.parser")
    page_title = clean(soup.title.get_text()) if soup.title else ""
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript"]):
        tag.decompose()
    root = soup.find("main") or soup.find("article") or soup.body or soup

    h1 = root.find("h1")
    title = clean(h1.get_text()) if h1 else page_title.split(" | ")[0]

    levels = [n for n in range(2, 7) if root.find(f"h{n}")]
    section_tag = f"h{levels[0]}" if levels else None

    blocks = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre", "blockquote", "tr", "dt", "dd"]
    meta_parts: list[str] = []
    sections: list[tuple[str, list[str]]] = []
    for el in root.find_all(blocks):
        if el.find_parent(blocks) is not None:      # e.g. <p> inside <li>
            continue
        name = el.name
        if name == "h1":
            continue
        if name == section_tag:
            sections.append((clean(el.get_text(" ")), []))
            continue
        if name == "tr":
            text = " | ".join(clean(c.get_text(" ")) for c in el.find_all(["th", "td"]))
        else:
            text = clean(el.get_text(" "))
        if not text:
            continue
        if name == "li":
            text = "- " + text
        elif name.startswith("h"):
            text += ":"
        if sections:
            sections[-1][1].append(text)
        else:
            meta_parts.append(text)

    return title, " ".join(meta_parts), [s for s in sections if s[1]]


def make_chunks(file: str, title: str, meta: str,
                sections: list[tuple[str, list[str]]]) -> list[tuple[str, dict]]:
    """One chunk per section; very long sections are split at paragraph breaks."""
    chunks = []
    for heading, paragraphs in sections:
        parts: list[list[str]] = [[]]
        for p in paragraphs:
            if parts[-1] and sum(len(x) for x in parts[-1]) + len(p) > MAX_CHUNK_CHARS:
                parts.append([])
            parts[-1].append(p)
        for i, paras in enumerate(parts):
            h = heading if len(parts) == 1 else f"{heading} (part {i + 1} of {len(parts)})"
            header = f"{title} - {h}\nSource: {file}" + (f" | {meta}" if meta else "")
            chunks.append((header + "\n\n" + "\n".join(paras),
                           {"source_file": file, "document": title, "section": h}))
    return chunks


# ---------------------------------------------------------------------------
# Chroma database
# ---------------------------------------------------------------------------

def docs_fingerprint() -> dict:
    return {p.relative_to(DOCS_DIR).as_posix(): [p.stat().st_size, int(p.stat().st_mtime)]
            for p in sorted(DOCS_DIR.rglob("*")) if p.is_file()}


def chroma_client():
    import chromadb
    from chromadb.config import Settings

    return chromadb.PersistentClient(path=str(DB_DIR), settings=Settings(anonymized_telemetry=False))


def build_index() -> None:
    log(f"Building the database from {DOCS_DIR} ...")
    if DB_DIR.exists():
        # OneDrive can mark files read-only, which blocks deletion on Windows.
        def force_remove(func, path, _exc):
            os.chmod(path, stat.S_IWRITE)
            func(path)
        shutil.rmtree(DB_DIR, onexc=force_remove)

    ids, texts, metas = [], [], []
    for path in sorted(DOCS_DIR.glob("*.htm*")):
        title, meta, sections = load_html(path)
        doc_chunks = make_chunks(path.name, title, meta, sections)
        log(f"  {path.name}: {len(doc_chunks)} chunks  ({title})")
        for i, (text, m) in enumerate(doc_chunks):
            ids.append(f"{path.name}::{i:03d}")
            texts.append(text)
            metas.append(m)
    if not ids:
        sys.exit(f"No HTML documents with text found in {DOCS_DIR}.")

    collection = chroma_client().create_collection(
        COLLECTION, configuration={"hnsw": {"space": "cosine"}})
    collection.add(ids=ids, documents=texts, metadatas=metas)
    MANIFEST.write_text(json.dumps(docs_fingerprint(), indent=2), encoding="utf-8")
    log(f"Indexed {len(ids)} chunks into {DB_DIR}")


_collection = None


def search(query: str, top_k: int = TOP_K) -> dict:
    """Return the top_k closest chunks, plus a warning if the documents changed."""
    global _collection
    if not MANIFEST.exists():
        raise SearchUnavailable(
            "The HR policy database has not been built yet. Run: "
            f".venv\\Scripts\\python.exe week-04\\hr_search.py{org_arg()} --rebuild")
    if _collection is None:
        _collection = chroma_client().get_collection(COLLECTION)
    res = _collection.query(query_texts=[query], n_results=top_k,
                            include=["documents", "metadatas", "distances"])
    results = [{"source_file": m["source_file"], "document": m["document"],
                "section": m["section"], "similarity": round(1 - d, 3), "text": t}
               for t, m, d in zip(res["documents"][0], res["metadatas"][0], res["distances"][0])]
    out: dict = {"results": results}
    if json.loads(MANIFEST.read_text(encoding="utf-8")) != docs_fingerprint():
        out["warning"] = ("The HR documents changed after the database was built, so these "
                          "results may be out of date. Ask the user to rebuild it.")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Build or search an organization's HR document database.")
    ap.add_argument("query", nargs="?", help="text to search for")
    ap.add_argument("--rebuild", action="store_true", help="(re)build the database")
    ap.add_argument("--org", metavar="FOLDER",
                    help="organization folder (default: week-04/hartwell-hr); "
                         "a bare name means a folder inside week-04")
    args = ap.parse_args()
    if not args.rebuild and not args.query:
        ap.error("give a search query, --rebuild, or both")
    use_org(hr_org.fail_on_org_error(lambda: hr_org.resolve(args.org)))
    log(f"Organization: {ORG_DIR.name}  (database: {DB_DIR.name})")
    if args.rebuild:
        build_index()
    if args.query:
        try:
            out = search(args.query)
        except SearchUnavailable as exc:
            sys.exit(str(exc))
        if "warning" in out:
            print(f"Warning: {out['warning']}\n")
        for i, r in enumerate(out["results"], 1):
            print(f"[{i}] {r['source_file']} - {r['section']}  (similarity {r['similarity']:.3f})")
            print("    " + r["text"].split("\n\n", 1)[-1][:200] + "\n")


if __name__ == "__main__":
    main()
