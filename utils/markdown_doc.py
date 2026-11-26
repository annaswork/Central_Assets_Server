"""Safe stdlib Markdown parser and structured document loader for portal guides."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MarkdownSection:
    """Rendered top-level (H2) documentation section."""

    id: str
    title: str
    html: str
    subsections: list[dict[str, str]]
    search_text: str


def github_slug(heading_text: str) -> str:
    """Compute GitHub-compatible heading anchor IDs for in-page navigation."""
    cleaned = re.sub(r"`([^`]+)`", r"\1", heading_text)
    cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
    cleaned = cleaned.strip().lower()
    # Keep ASCII alphanumeric, spaces, underscores, and hyphens (drop emojis/punctuation like GitHub anchors)
    cleaned = re.sub(r"[^a-z0-9\s_-]", "", cleaned)
    cleaned = cleaned.strip()
    return re.sub(r" ", "-", cleaned) or "section"


def _render_inline(text: str) -> str:
    """Render inline Markdown (code, links, bold, italic) after HTML-escaping text."""
    code_tokens: list[str] = []

    def _stash_code(match: re.Match[str]) -> str:
        idx = len(code_tokens)
        escaped = html.escape(match.group(1), quote=False)
        code_tokens.append(f'<code class="api-inline-code">{escaped}</code>')
        return f"\x00INLINECODE{idx}\x00"

    protected = re.sub(r"`([^`\n]+)`", _stash_code, text)
    escaped_text = html.escape(protected, quote=False)

    # Markdown links: [label](href) — permit only internal anchors or http(s)/relative links
    def _replace_link(match: re.Match[str]) -> str:
        label = match.group(1)
        href = match.group(2).strip()
        if not (href.startswith("#") or href.startswith("/") or href.startswith("https://") or href.startswith("http://")):
            return label
        safe_href = html.escape(href, quote=True)
        extra = ' target="_blank" rel="noopener noreferrer"' if href.startswith(("http://", "https://")) else ""
        return f'<a href="{safe_href}" class="api-doc-link"{extra}>{label}</a>'

    escaped_text = re.sub(
        r"\[([^\]]+)\]\(((?:[^()\s]+|\([^()\s]*\))+)\)",
        _replace_link,
        escaped_text,
    )
    escaped_text = re.sub(r"\*\*([^\n*]+?)\*\*", r"<strong>\1</strong>", escaped_text)
    # Boundary-aware underscore italics so snake_case identifiers stay intact
    escaped_text = re.sub(
        r"(^|(?<=[\s(]))_([^_\n]+?)_(?=$|[\s.,;:!?)])",
        r"\1<em>\2</em>",
        escaped_text,
    )

    for idx, code_html in enumerate(code_tokens):
        escaped_text = escaped_text.replace(f"\x00INLINECODE{idx}\x00", code_html)
    return escaped_text


def _split_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _is_table_separator(line: str) -> bool:
    stripped = line.strip()
    if "|" not in stripped:
        return False
    cells = _split_table_row(stripped)
    return bool(cells) and all(bool(re.fullmatch(r":?-{3,}:?", c)) for c in cells)


def _render_code_block(lang: str, code_lines: list[str]) -> str:
    clean_lang = re.sub(r"[^a-zA-Z0-9_-]", "", (lang or "").strip().lower())
    display_lang = clean_lang.upper() if clean_lang else "TEXT"
    raw_code = "\n".join(code_lines)
    escaped_code = html.escape(raw_code, quote=False)
    method_badge = ""
    if clean_lang == "http":
        first_line = next((ln.strip() for ln in code_lines if ln.strip()), "")
        for verb in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            if first_line.startswith(f"{verb} "):
                cls = "api-method-post" if verb in ("POST", "PUT", "PATCH") else "api-method-get"
                method_badge = f'<span class="api-method-pill {cls}">{verb}</span>'
                break
    return (
        '<div class="api-code-block">'
        '<div class="api-code-header">'
        f'<div class="api-code-meta">{method_badge}<span class="api-code-lang">{html.escape(display_lang)}</span></div>'
        '<button type="button" class="btn btn-outlined btn-xs api-copy-code-btn" onclick="copyApiCodeBlock(this)" title="Copy snippet">'
        '📋 Copy'
        "</button>"
        "</div>"
        f'<pre class="api-code-pre"><code class="language-{clean_lang or "text"}">{escaped_code}</code></pre>'
        "</div>"
    )


def _render_blockquote(quote_lines: list[str]) -> str:
    body_html = "<br>".join(_render_inline(ln.rstrip()) for ln in quote_lines)
    return f'<div class="api-doc-callout">{body_html}</div>'


def _render_list(lines: list[str], start_idx: int) -> tuple[str, int]:
    """Render contiguous bulleted/numbered list lines with single-level nesting."""
    item_re = re.compile(r"^(\s*)([-*]|\d+\.)\s+(.*)$")
    first_m = item_re.match(lines[start_idx])
    assert first_m is not None
    base_indent = len(first_m.group(1))
    is_ordered = first_m.group(2).endswith(".")
    tag = "ol" if is_ordered else "ul"
    parts = [f'<{tag} class="api-doc-list">']
    idx = start_idx

    while idx < len(lines):
        m = item_re.match(lines[idx])
        if not m:
            break
        indent = len(m.group(1))
        marker = m.group(2)
        if indent < base_indent:
            break
        if indent > base_indent:
            nested_html, idx = _render_list(lines, idx)
            if parts and parts[-1].endswith("</li>"):
                parts[-1] = parts[-1][:-5] + nested_html + "</li>"
            else:
                parts.append(f"<li>{nested_html}</li>")
            continue
        cur_ordered = marker.endswith(".")
        if cur_ordered != is_ordered:
            break
        parts.append(f"<li>{_render_inline(m.group(3).strip())}</li>")
        idx += 1

    parts.append(f"</{tag}>")
    return "".join(parts), idx


def render_markdown_blocks(lines: list[str]) -> tuple[str, list[dict[str, str]]]:
    """Convert Markdown lines into HTML blocks and collect H3/H4 subsection anchors."""
    chunks: list[str] = []
    subsections: list[dict[str, str]] = []
    idx = 0
    total = len(lines)
    item_re = re.compile(r"^\s*([-*]|\d+\.)\s+")

    while idx < total:
        line = lines[idx]
        stripped = line.strip()

        if not stripped:
            idx += 1
            continue

        if stripped.startswith("```"):
            lang = stripped[3:].strip()
            idx += 1
            code_lines: list[str] = []
            while idx < total and not lines[idx].strip().startswith("```"):
                code_lines.append(lines[idx])
                idx += 1
            if idx < total:
                idx += 1
            chunks.append(_render_code_block(lang, code_lines))
            continue

        if re.fullmatch(r"-{3,}|\*{3,}", stripped):
            chunks.append('<hr class="api-doc-hr">')
            idx += 1
            continue

        heading_m = re.match(r"^(#{2,4})\s+(.+)$", stripped)
        if heading_m:
            level = len(heading_m.group(1))
            raw_title = heading_m.group(2).strip()
            slug = github_slug(raw_title)
            if level == 3:
                subsections.append({"id": slug, "title": raw_title})
            chunks.append(
                f'<h{level} id="{html.escape(slug, quote=True)}" class="api-doc-h{level}">'
                f"{_render_inline(raw_title)}</h{level}>"
            )
            idx += 1
            continue

        if stripped.startswith(">"):
            q_lines: list[str] = []
            while idx < total and lines[idx].strip().startswith(">"):
                q_lines.append(lines[idx].strip()[1:].lstrip())
                idx += 1
            chunks.append(_render_blockquote(q_lines))
            continue

        if "|" in stripped and idx + 1 < total and _is_table_separator(lines[idx + 1]):
            headers = _split_table_row(lines[idx])
            idx += 2
            rows: list[list[str]] = []
            while idx < total and "|" in lines[idx].strip() and lines[idx].strip():
                rows.append(_split_table_row(lines[idx]))
                idx += 1
            th_html = "".join(f"<th>{_render_inline(col)}</th>" for col in headers)
            tr_html = "".join(
                "<tr>"
                + "".join(
                    f"<td>{_render_inline(row[c] if c < len(row) else '')}</td>"
                    for c in range(len(headers))
                )
                + "</tr>"
                for row in rows
            )
            chunks.append(
                '<div class="table-responsive api-doc-table-wrap">'
                '<table class="data-table api-doc-table">'
                f"<thead><tr>{th_html}</tr></thead>"
                f"<tbody>{tr_html}</tbody>"
                "</table></div>"
            )
            continue

        if item_re.match(line):
            list_html, idx = _render_list(lines, idx)
            chunks.append(list_html)
            continue

        para_lines: list[str] = []
        while idx < total:
            cur = lines[idx]
            cur_s = cur.strip()
            if (
                not cur_s
                or cur_s.startswith(("```", ">"))
                or re.match(r"^#{2,4}\s+", cur_s)
                or re.fullmatch(r"-{3,}|\*{3,}", cur_s)
                or item_re.match(cur)
                or ("|" in cur_s and idx + 1 < total and _is_table_separator(lines[idx + 1]))
            ):
                break
            para_lines.append(cur_s)
            idx += 1
        chunks.append(f'<p class="api-doc-p">{" ".join(_render_inline(p) for p in para_lines)}</p>')

    return "\n".join(chunks), subsections


@lru_cache(maxsize=4)
def _parse_api_usage_cached(path_str: str, mtime_ns: int) -> dict[str, Any]:
    """Parse API_Usage.md into intro banner + structured H2 sections."""
    del mtime_ns  # Cache key invalidation only
    raw_text = Path(path_str).read_text(encoding="utf-8")
    all_lines = raw_text.splitlines()

    doc_title = "Client SDK / API Integration Guide"
    preamble_lines: list[str] = []
    h2_blocks: list[tuple[str, list[str]]] = []
    current_h2: str | None = None
    current_lines: list[str] = []
    in_fence = False

    for line in all_lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence

        if not in_fence and current_h2 is None and line.startswith("# "):
            doc_title = line[2:].strip()
            continue
        if not in_fence and line.startswith("## "):
            if current_h2 is not None:
                h2_blocks.append((current_h2, current_lines))
            current_h2 = line[3:].strip()
            current_lines = []
            continue

        if current_h2 is None:
            preamble_lines.append(line)
        else:
            current_lines.append(line)

    if current_h2 is not None:
        h2_blocks.append((current_h2, current_lines))

    intro_html, _ = render_markdown_blocks(preamble_lines)
    sections: list[MarkdownSection] = []
    for title, sec_lines in h2_blocks:
        if title.strip().lower() == "table of contents":
            continue
        sec_id = github_slug(title)
        sec_html, subs = render_markdown_blocks(sec_lines)
        plain_text = " ".join([title] + [ln.strip() for ln in sec_lines if ln.strip()])
        sections.append(
            MarkdownSection(
                id=sec_id,
                title=title,
                html=sec_html,
                subsections=subs,
                search_text=plain_text.lower(),
            )
        )

    return {
        "title": doc_title,
        "intro_html": intro_html,
        "sections": sections,
    }


def load_api_usage_document(md_path: Path) -> dict[str, Any]:
    """Load and parse API_Usage.md, automatically busting cache when file mtime changes."""
    stat = md_path.stat()
    return _parse_api_usage_cached(str(md_path), stat.st_mtime_ns)
