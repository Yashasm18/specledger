"""Turning an uploaded document into pages of text.

Extraction used to be PDF-only and inlined in the worker. A specification
arrives as often in a Word file or a pasted text file as it does in a PDF,
and the fact-extraction step downstream does not care which — it only
needs text with a page number. So the format handling lives here, behind
one function, and the worker asks for pages.
"""

import io
import unittest
import zipfile

from backend.specledger.document_text import extract_pages, UnreadableDocument


def _docx(paragraphs: list[str]) -> bytes:
    """A minimal but genuine .docx: a zip whose word/document.xml holds runs."""
    body = "".join(
        f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", document)
    return buffer.getvalue()


class PlainTextTests(unittest.TestCase):
    def test_text_file_is_one_page(self) -> None:
        pages = extract_pages("spec.txt", b"Material: Bronze ASTM B584")
        assert len(pages) == 1
        assert "Bronze ASTM B584" in pages[0]["text"]

    def test_utf8_is_decoded(self) -> None:
        pages = extract_pages("spec.txt", "Temperature: −20 °C".encode("utf-8"))
        assert "°C" in pages[0]["text"]

    def test_windows_encoding_does_not_crash(self) -> None:
        pages = extract_pages("spec.txt", "Size: 1⁄2 in".encode("cp1252", errors="replace"))
        assert pages[0]["text"]


class WordDocumentTests(unittest.TestCase):
    def test_docx_paragraphs_are_read(self) -> None:
        pages = extract_pages("spec.docx", _docx(["Part Number: 70-104-01", "Material: Bronze"]))
        assert len(pages) == 1
        assert "70-104-01" in pages[0]["text"]
        assert "Bronze" in pages[0]["text"]

    def test_docx_paragraphs_are_separated_by_lines(self) -> None:
        # Line structure matters: a specification value is anchored to the
        # end of its line, so runs must not be concatenated into one blob.
        pages = extract_pages("spec.docx", _docx(["Material: Bronze", "Size: 2 in"]))
        assert "Bronze\n" in pages[0]["text"] or pages[0]["text"].count("\n") >= 1

    def test_a_file_that_is_not_a_zip_is_reported(self) -> None:
        with self.assertRaises(UnreadableDocument):
            extract_pages("spec.docx", b"this is not a docx")


class RichTextTests(unittest.TestCase):
    def test_rtf_control_words_are_stripped(self) -> None:
        rtf = rb"{\rtf1\ansi\deff0 {\fonttbl{\f0 Arial;}}\f0\fs20 Material: Bronze ASTM B584\par}"
        pages = extract_pages("spec.rtf", rtf)
        assert "Material: Bronze ASTM B584" in pages[0]["text"]

    def test_rtf_paragraph_breaks_become_newlines(self) -> None:
        rtf = rb"{\rtf1\ansi Material: Bronze\par Size: 2 in\par}"
        text = extract_pages("spec.rtf", rtf)[0]["text"]
        assert "\n" in text


class UnsupportedTests(unittest.TestCase):
    def test_an_unsupported_extension_is_reported(self) -> None:
        with self.assertRaises(UnreadableDocument):
            extract_pages("photo.jpg", b"\xff\xd8\xff")


if __name__ == "__main__":
    unittest.main()
