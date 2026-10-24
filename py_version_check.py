"""
py_version_check.py
============================================================================
PURPOSE
Twin of the Apps Script fn_24_67 version check, for the files in the GitHub repository: compares the version written in every listed
Python / workflow file with the version it should have (EXPECTED below) and prints one line per file:
    OK       file vNN (expected vNN)
    OLD      the repository file is older than expected  -> commit the newer file
    NEWER    the repository file is newer than expected  -> EXPECTED here is out of date
    NO TAG   the file has no readable version line
    MISSING  the file is not in the repository
The files are only READ as text (nothing is imported or run), so the check needs no packages and takes about a second.

HOW IT IS USED
  * workflow py_version_check.yml (Actions -> "py_version_check" -> Run workflow): prints the list; the job fails when something is OLD / MISSING / NO TAG.
  * first step of provider_json_scraper.yml (continue-on-error): the list is at the top of every scraper run's log.
  * locally: python py_version_check.py

HOW TO KEEP IT CURRENT
  Every time a listed file gets a new version, the number in EXPECTED changes with it (this file is delivered together with that change).
  Version lines read:  VERSION = "name v66" / SCRIPT_VERSION = "name v66"  |  "VERSION: name v3" in the docstring  |  "# VERSION 13" in a workflow.

VERSION: py_version_check v2 -- (2026-10-23) workflow files are looked up in .github/workflows/ as well (v1 reported provider_json_scraper.yml as MISSING).
  v1 -- new.
============================================================================
"""
import os
import re
import sys

VERSION = "py_version_check v6"

# file -> expected version (a number such as 66 or 1.16)
EXPECTED = {
    "provider_json_scraper.py": "70",
    "insider_score_scraper.py": "15",
    "as_dcf_extractor.py": "7",
    "as_qm_data.py": "1.17",
    "as_quality_metrics.py": "6",
    "as_moat.py": "1.3",
    "as_ttm_metrics.py": "1.7",
    "gh_log_uploader.py": "3",
    "provider_json_scraper.yml": "14",
}


def _num(text):
    return tuple(int(part) for part in re.findall(r"\d+", text or ""))


def read_version(path):
    """Version text found in the file, or None."""
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            source = handle.read()
    except OSError:
        return "MISSING"
    if path.endswith((".yml", ".yaml")):
        found = re.findall(r"^#\s*VERSION\s+(\d+)", source, re.M)
        return str(max(int(n) for n in found)) if found else None
    found = re.search(r'^\s*(?:SCRIPT_)?VERSION\s*=\s*["\'][^"\']*?v?(\d+(?:\.\d+)*)["\']', source, re.M)
    if not found:
        found = re.search(r"^\s*VERSION:\s*\S+\s+v(\d+(?:\.\d+)*)", source, re.M)
    return found.group(1) if found else None


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    print("📦 VERSIONS | " + VERSION)
    bad = 0
    for name, expected in EXPECTED.items():
        path = os.path.join(here, name)
        if not os.path.exists(path):
            path = os.path.join(here, ".github", "workflows", name)   # v2: workflows live here in the repository
        actual = read_version(path)
        if actual == "MISSING":
            status, shown = "MISSING", ""
        elif actual is None:
            status, shown = "NO TAG", ""
        else:
            shown = " v" + actual
            status = "OK" if _num(actual) == _num(expected) else ("OLD" if _num(actual) < _num(expected) else "NEWER")
        if status != "OK":
            bad += 1 if status != "NEWER" else 0
        print("{:<8}  {}{} (expected v{})".format(status, name, shown, expected))
    print("VERSION CHECK - {}".format("all files as expected" if not bad else "{} file(s) to update".format(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
