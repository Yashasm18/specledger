"""One resolver decides what an uploaded file is.

Which extensions are accepted, and what each one *does*, had started to
live in several places at once — the ingest endpoint's ALLOWED_EXTENSIONS,
read_catalogue's suffix branch, the intake endpoint's content-type check,
and three separate pieces of UI copy. That shape of duplication has caused
the same defect five times in this codebase, so the rule lives here and
every caller asks this module.
"""

import unittest

from backend.specledger.file_types import classify_upload


class CatalogueFormatTests(unittest.TestCase):
    """Structured data becomes rows in a 252-column batch."""

    def test_csv_is_a_catalogue(self) -> None:
        assert classify_upload("feed.csv").kind == "catalogue"

    def test_tsv_is_a_catalogue(self) -> None:
        assert classify_upload("feed.tsv").kind == "catalogue"

    def test_xlsx_is_a_catalogue(self) -> None:
        assert classify_upload("feed.xlsx").kind == "catalogue"

    def test_json_is_a_catalogue(self) -> None:
        assert classify_upload("feed.json").kind == "catalogue"

    def test_xml_is_a_catalogue(self) -> None:
        assert classify_upload("feed.xml").kind == "catalogue"

    def test_case_and_path_are_ignored(self) -> None:
        assert classify_upload("/tmp/Some Feed.CSV").kind == "catalogue"


class DocumentFormatTests(unittest.TestCase):
    """Prose and datasheets are read for facts; they create no rows."""

    def test_pdf_is_a_document(self) -> None:
        assert classify_upload("datasheet.pdf").kind == "document"

    def test_txt_is_a_document(self) -> None:
        assert classify_upload("spec.txt").kind == "document"

    def test_docx_is_a_document(self) -> None:
        assert classify_upload("spec.docx").kind == "document"

    def test_rtf_is_a_document(self) -> None:
        assert classify_upload("spec.rtf").kind == "document"


class RejectedFormatTests(unittest.TestCase):
    """A refusal has to say why, and what to do instead."""

    def test_image_is_rejected(self) -> None:
        result = classify_upload("photo.jpg")
        assert result.kind == "unsupported"
        assert "image" in result.reason.casefold()

    def test_every_image_format_is_rejected(self) -> None:
        for name in ["a.jpg", "a.jpeg", "a.png", "a.gif", "a.svg"]:
            assert classify_upload(name).kind == "unsupported", name

    def test_audio_and_video_are_rejected(self) -> None:
        for name in ["a.mp3", "a.wav", "a.mp4", "a.avi", "a.mov"]:
            assert classify_upload(name).kind == "unsupported", name

    def test_archive_and_executable_are_rejected(self) -> None:
        for name in ["a.zip", "a.exe", "a.iso"]:
            assert classify_upload(name).kind == "unsupported", name

    def test_legacy_excel_names_its_replacement(self) -> None:
        result = classify_upload("book.xls")
        assert result.kind == "unsupported"
        assert ".xlsx" in result.reason

    def test_legacy_word_names_its_replacement(self) -> None:
        result = classify_upload("spec.doc")
        assert result.kind == "unsupported"
        assert ".docx" in result.reason

    def test_unknown_extension_is_rejected_with_a_reason(self) -> None:
        result = classify_upload("mystery.qqq")
        assert result.kind == "unsupported"
        assert result.reason

    def test_a_file_with_no_extension_is_rejected(self) -> None:
        assert classify_upload("README").kind == "unsupported"


if __name__ == "__main__":
    unittest.main()
