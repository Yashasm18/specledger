"""Turn an uploaded document into pages of plain text.

Fact extraction downstream does not care what the file was — it needs text
with a page number and nothing else. So every supported document format is
reduced to that shape here, behind one function, rather than the worker
growing a branch per format.

Line structure is preserved deliberately. A specification value is
anchored to the end of its line (see ``extraction.PATTERNS``), so
collapsing a document into one long string would silently stop every
pattern from matching.
"""

from __future__ import annotations

import io
import re
import zipfile


class UnreadableDocument(Exception):
    """The bytes could not be read as the format their filename claims."""


def extract_pages(filename: str, content: bytes) -> list[dict]:
    """Read a document into ``[{"page": n, "text": ...}]``.

    Raises UnreadableDocument when the file cannot be read as its format,
    so intake can say what went wrong instead of storing an empty artifact.
    """
    extension = ("." + str(filename or "").rsplit(".", 1)[-1]).casefold() if "." in str(filename or "") else ""

    if extension == ".pdf":
        return _pdf_pages(content)
    if extension == ".txt":
        return [{"page": 1, "text": _decode(content)}]
    if extension == ".docx":
        return [{"page": 1, "text": _docx_text(content)}]
    if extension == ".rtf":
        return [{"page": 1, "text": _rtf_text(_decode(content))}]
    raise UnreadableDocument(f"'{extension}' is not a readable document format")


def _decode(content: bytes) -> str:
    """Decode text that may not be UTF-8, without losing the whole file."""
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _pdf_pages(content: bytes) -> list[dict]:
    try:
        import pymupdf
    except ImportError:  # pragma: no cover - exercised only without the dep
        try:
            import fitz as pymupdf  # type: ignore[no-redef]
        except ImportError as exc:
            raise UnreadableDocument("PyMuPDF is required to read PDFs") from exc
    try:
        document = pymupdf.open(stream=content, filetype="pdf")
    except Exception as exc:
        raise UnreadableDocument(f"File could not be opened as a PDF: {exc}") from exc
    try:
        return [
            {"page": index + 1, "text": page.get_text("text").strip()}
            for index, page in enumerate(document)
        ]
    finally:
        document.close()


# A .docx is a zip; the text lives in word/document.xml as <w:t> runs inside
# <w:p> paragraphs. Reading it directly keeps the dependency list unchanged —
# python-docx would add a dependency for a paragraph loop.
_DOCX_PARAGRAPH = re.compile(r"<w:p[ >].*?</w:p>|<w:p/>", re.S)
_DOCX_RUN = re.compile(r"<w:t[^>]*>(.*?)</w:t>", re.S)
_XML_TAG = re.compile(r"<[^>]+>")


def _docx_text(content: bytes) -> str:
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise UnreadableDocument("File is not a readable .docx (not a zip archive)") from exc
    try:
        with archive.open("word/document.xml") as handle:
            xml = handle.read().decode("utf-8", errors="replace")
    except KeyError as exc:
        raise UnreadableDocument("File is a zip but holds no word/document.xml") from exc
    finally:
        archive.close()

    lines: list[str] = []
    for paragraph in _DOCX_PARAGRAPH.findall(xml):
        runs = _DOCX_RUN.findall(paragraph)
        text = _unescape("".join(runs)).strip()
        if text:
            lines.append(text)
    if not lines:
        # No paragraph markup — fall back to every run in the document.
        runs = _DOCX_RUN.findall(xml)
        lines = [_unescape("".join(runs)).strip()] if runs else []
    return "\n".join(lines)


def _unescape(text: str) -> str:
    return (text.replace("&amp;", "&").replace("&lt;", "<")
                .replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'"))


# RTF is a control-word language, not markup. Paragraph breaks become real
# newlines so line-anchored patterns still work; groups that carry no body
# text (font and colour tables) are dropped rather than flattened in.
_RTF_SKIP_GROUP = re.compile(r"\{\\\*?\\(?:fonttbl|colortbl|stylesheet|info|pict)[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", re.S)
_RTF_PARAGRAPH = re.compile(r"\\(?:par|line|pard)\b")
_RTF_CONTROL = re.compile(r"\\[a-zA-Z]+-?\d*\s?")
_RTF_HEX = re.compile(r"\\'([0-9a-fA-F]{2})")


def _rtf_text(text: str) -> str:
    text = _RTF_SKIP_GROUP.sub(" ", text)
    text = _RTF_HEX.sub(lambda m: chr(int(m.group(1), 16)), text)
    text = _RTF_PARAGRAPH.sub("\n", text)
    text = _RTF_CONTROL.sub("", text)
    text = text.replace("{", "").replace("}", "")
    lines = [line.strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)
