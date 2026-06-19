import json
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from google import genai
from google.genai import types

from agents.logger import get_logger

load_dotenv()  # must be before genai.Client()

logger = get_logger("pharmalens.lint")

client = genai.Client(http_options=types.HttpOptions(timeout=300_000))  # 300s in ms

PRO_MODEL = "gemini-2.5-pro"

try:
    BASE_DIR = Path(__file__).parent.parent
except NameError:
    BASE_DIR = Path.cwd().parent

REFERENCE_DIR = BASE_DIR / "reference"

DRUGS      = json.loads((REFERENCE_DIR / "drugs.json").read_text())
INDICATIONS = json.loads((REFERENCE_DIR / "indications.json").read_text())
COMPANIES  = json.loads((REFERENCE_DIR / "companies.json").read_text())


def collect_wiki_pages() -> dict[str, str]:
    from agents.wiki_gcs import read_wiki, list_wiki
    pages = {}
    for rel in list_wiki():
        if rel in ("log.md", "health-report.md"):
            continue
        pages[rel] = read_wiki(rel)
    return pages


def run_lint():
    from agents.wiki_gcs import read_wiki, write_wiki

    pages = collect_wiki_pages()
    log_content = read_wiki("log.md")

    structural_issues = _structural_checks(pages)
    semantic_issues = _semantic_checks(pages, log_content)

    _write_health_report(structural_issues, semantic_issues, pages)

    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M")
    new_entry = (
        f"\n## [{timestamp}] lint | weekly pass\n"
        f"pages_checked: {len(pages)}\n"
        f"structural_issues: {len(structural_issues)}\n"
        f"semantic_issues: {len(semantic_issues)}\n"
        f"status: success\n"
    )
    write_wiki("log.md", log_content + new_entry)

    logger.info(
        f"LINT | Done. {len(structural_issues)} structural, "
        f"{len(semantic_issues)} semantic issues."
    )


def _structural_checks(pages: dict[str, str]) -> list[dict]:
    issues = []
    all_content = "\n".join(pages.values())

    for page_path in pages:
        page_name = Path(page_path).stem
        if (f"[[{page_name}]]" not in all_content
                and f"[[{page_path}]]" not in all_content
                and page_path != "index.md"):
            issues.append({
                "type": "orphan_page",
                "page": page_path,
                "detail": "No backlinks from any other wiki page"
            })

    for inn in DRUGS:
        if f"drugs/{inn}.md" not in pages:
            issues.append({
                "type": "missing_drug_page",
                "page": f"drugs/{inn}.md",
                "detail": f"{inn} in drugs.json but no wiki page exists yet"
            })

    for slug in COMPANIES:
        if f"companies/{slug}.md" not in pages:
            issues.append({
                "type": "missing_company_page",
                "page": f"companies/{slug}.md",
                "detail": f"{slug} in companies.json but no wiki page exists yet"
            })

    for slug in INDICATIONS:
        hub = f"indications/{slug}/_index.md"
        if hub not in pages:
            issues.append({
                "type": "missing_indication_hub",
                "page": hub,
                "detail": f"No _index.md for indication {slug}"
            })

    required_drug_fields = ["drug:", "company:", "indications:", "status:", "latest_event:"]
    for page_path, content in pages.items():
        if page_path.startswith("drugs/") and page_path.endswith(".md"):
            missing = [f for f in required_drug_fields if f not in content]
            if missing:
                issues.append({
                    "type": "missing_frontmatter",
                    "page": page_path,
                    "detail": f"Missing frontmatter fields: {missing}"
                })

    return issues


def _semantic_checks(pages: dict[str, str], log_content: str) -> list[dict]:
    snapshot_parts = []

    if "index.md" in pages:
        snapshot_parts.append(f"=== index.md ===\n{pages['index.md'][:3000]}")

    for path, content in pages.items():
        if path.startswith("drugs/"):
            snapshot_parts.append(f"=== {path} ===\n{content[:800]}")

    for path, content in pages.items():
        if path.startswith("companies/"):
            snapshot_parts.append(f"=== {path} ===\n{content[:600]}")

    for path, content in pages.items():
        if path.startswith("trials/"):
            snapshot_parts.append(f"=== {path} ===\n{content[:400]}")

    for path, content in pages.items():
        if path.startswith("events/"):
            snapshot_parts.append(f"=== {path} ===\n{content[:400]}")

    snapshot = "\n\n".join(snapshot_parts)
    log_recent = "\n".join(log_content.splitlines()[-60:])

    prompt = f"""
Perform a health check on the PharmaLens wiki.

Wiki snapshot:
---
{snapshot[:20000]}
---

Recent log entries:
---
{log_recent}
---

Check for these issues and return a JSON array:

1. CONTRADICTIONS — any drug page field that conflicts with an event or company page
2. STALE_ENTITY — a drug or company page not updated after a related document was ingested
3. MISSING_BACKLINK — event references a drug/company but no return link exists
4. THIN_INDICATION_HUB — _index.md lists fewer drugs than should belong there
5. SUGGESTED_NEW_PAGE — pattern of events suggests a synthesis page would be valuable

Return JSON array:
[
  {{
    "type": "contradiction | stale_entity | missing_backlink | thin_hub | suggested_new_page",
    "page": "affected page path",
    "detail": "specific description",
    "suggested_action": "what to fix"
  }}
]

Return ONLY valid JSON. Return [] if no issues found.
"""

    response = client.models.generate_content(
        model=PRO_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.1,
            response_mime_type="application/json"
        )
    )

    try:
        return json.loads(response.text)
    except json.JSONDecodeError:
        return [{"type": "lint_error", "page": "N/A",
                 "detail": "LLM returned invalid JSON",
                 "suggested_action": "Re-run lint"}]


def _write_health_report(structural: list[dict], semantic: list[dict],
                         pages: dict[str, str]):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "# Wiki health report",
        f"Generated: {timestamp}  |  Pages checked: {len(pages)}",
        "",
        f"## Structural issues ({len(structural)})",
        "",
    ]
    for issue in structural:
        lines += [f"### {issue['type']}",
                  f"- **Page:** `{issue['page']}`",
                  f"- **Detail:** {issue['detail']}", ""]

    lines += [f"## Semantic issues ({len(semantic)})", ""]
    for issue in semantic:
        lines += [f"### {issue['type']}",
                  f"- **Page:** `{issue.get('page', 'N/A')}`",
                  f"- **Detail:** {issue.get('detail', '')}",
                  f"- **Action:** {issue.get('suggested_action', '')}", ""]

    new_pages = [i for i in semantic if i["type"] == "suggested_new_page"]
    if new_pages:
        lines += ["## Suggested new pages", ""]
        for item in new_pages:
            lines.append(f"- {item['detail']}")

    from agents.wiki_gcs import write_wiki
    write_wiki("health-report.md", "\n".join(lines))
