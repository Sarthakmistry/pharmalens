"""
api/agent.py
PharmaLens Q&A agent — Gemini 2.5 Flash + wiki/stock tools.

Runs an agentic tool loop (max MAX_TOOL_CALLS iterations) and yields
server-sent event dicts that the FastAPI route streams to the client:

  {"type": "tool_call",   "name": str, "input": dict}
  {"type": "tool_result", "name": str, "content": str}   # first 300 chars
  {"type": "text",        "content": str}
  {"type": "done",        "full_text": str}
"""

import json
from typing import AsyncGenerator

from dotenv import load_dotenv
from google import genai
from google.genai import types

from .tools import read_wiki_page, list_wiki_pages, get_stock_price

load_dotenv()

client = genai.Client()
FLASH_MODEL = "gemini-2.5-flash"
MAX_TOOL_CALLS = 10

SYSTEM_PROMPT = """You are PharmaLens, a pharmaceutical intelligence assistant backed by a structured wiki.

Wiki layout:
- drugs/<drug>.md               — per-drug pages (mechanism, trials, sentiment)
- companies/<company>.md        — company pipeline, earnings intelligence, recent events
- indications/<slug>/_index.md  — therapeutic area overview (drugs, companies, trials, events)
- trials/<company>.md           — clinical trial roster per company
- events/<slug>.md              — individual corporate events (earnings, approvals, filings)

Instructions:
1. Always look up relevant wiki pages with read_wiki_page or list_wiki_pages before answering.
2. Quote specific numbers, dates, and drug names from the wiki — do not hallucinate.
3. For live stock data, call get_stock_price with the company's ticker (e.g. NVO, LLY).
4. Be concise. One short paragraph per topic; bullet points for lists.
"""

# ── Gemini tool declarations ──────────────────────────────────────────────────

TOOL_DECLARATIONS = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="read_wiki_page",
            description=(
                "Read a single wiki page by its path relative to the wiki directory. "
                "Example paths: 'indications/glp1-obesity/_index.md', "
                "'companies/novo-nordisk.md', 'drugs/semaglutide.md'"
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "page_path": types.Schema(
                        type=types.Type.STRING,
                        description="Path relative to wiki/, e.g. 'drugs/tirzepatide.md'",
                    )
                },
                required=["page_path"],
            ),
        ),
        types.FunctionDeclaration(
            name="list_wiki_pages",
            description=(
                "List all .md pages under a wiki sub-directory. "
                "Useful to discover what pages exist before reading them. "
                "Example prefixes: 'companies', 'drugs', 'indications', 'events', 'trials'"
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "prefix": types.Schema(
                        type=types.Type.STRING,
                        description="Sub-directory prefix, e.g. 'companies'. Leave empty to list all.",
                    )
                },
                required=[],
            ),
        ),
        types.FunctionDeclaration(
            name="get_stock_price",
            description="Get the current stock price, change, and % change for a ticker symbol.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "ticker": types.Schema(
                        type=types.Type.STRING,
                        description="NYSE/NASDAQ ticker, e.g. 'NVO', 'LLY', 'MRK'",
                    )
                },
                required=["ticker"],
            ),
        ),
    ]
)

# ── tool dispatch ─────────────────────────────────────────────────────────────

def _dispatch(name: str, args: dict) -> str:
    if name == "read_wiki_page":
        return read_wiki_page(args.get("page_path", ""))
    if name == "list_wiki_pages":
        result = list_wiki_pages(args.get("prefix", ""))
        return json.dumps(result)
    if name == "get_stock_price":
        result = get_stock_price(args.get("ticker", ""))
        return json.dumps(result)
    return f"Unknown tool: {name}"


# ── agent loop ────────────────────────────────────────────────────────────────

async def run_agent(
    question: str,
    indication: str | None = None,
    company: str | None = None,
) -> AsyncGenerator[dict, None]:
    """Async generator that runs the agentic loop and yields SSE event dicts."""

    # Build user message with optional context hint
    context_lines = []
    if indication:
        context_lines.append(f"User is currently viewing indication: {indication}")
    if company:
        context_lines.append(f"User is currently viewing company: {company}")

    user_text = ("\n".join(context_lines) + "\n\n" if context_lines else "") + question

    contents: list[types.Content] = [
        types.Content(role="user", parts=[types.Part(text=user_text)])
    ]

    full_text_parts: list[str] = []

    for _ in range(MAX_TOOL_CALLS):
        response = await client.aio.models.generate_content(
            model=FLASH_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                tools=[TOOL_DECLARATIONS],
                temperature=0.2,
            ),
        )

        candidate = response.candidates[0]
        function_calls: list = []
        text_parts: list[str] = []

        for part in candidate.content.parts:
            if hasattr(part, "function_call") and part.function_call:
                function_calls.append(part.function_call)
            if hasattr(part, "text") and part.text:
                text_parts.append(part.text)

        if text_parts:
            text = "".join(text_parts)
            full_text_parts.append(text)
            yield {"type": "text", "content": text}

        if not function_calls:
            break

        # Append model turn before executing tools
        contents.append(candidate.content)

        tool_result_parts: list[types.Part] = []
        for fc in function_calls:
            fn_name = fc.name
            fn_args = dict(fc.args) if fc.args else {}

            yield {"type": "tool_call", "name": fn_name, "input": fn_args}

            try:
                raw = _dispatch(fn_name, fn_args)
            except Exception as exc:
                raw = f"Error: {exc}"

            # Truncate very large results (wiki pages can be long)
            if len(raw) > 8000:
                raw = raw[:8000] + "\n...[truncated]"

            yield {"type": "tool_result", "name": fn_name, "content": raw[:300]}

            tool_result_parts.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        name=fn_name,
                        response={"output": raw},
                    )
                )
            )

        contents.append(types.Content(role="user", parts=tool_result_parts))

    yield {"type": "done", "full_text": "".join(full_text_parts)}
