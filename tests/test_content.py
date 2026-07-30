from pathlib import Path

import pytest

from cloudfileflow.content import ContentRejectedError, validate_content


def write_fixture(tmp_path: Path, name: str, content: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(content)
    return path


def test_pdf_signature_and_plain_utf8_are_detected(tmp_path: Path) -> None:
    pdf = write_fixture(tmp_path, "fixture.pdf", b"%PDF-1.7\nsynthetic")
    text = write_fixture(tmp_path, "fixture.txt", "Synthetic café".encode())

    assert validate_content(pdf, "application/pdf") == "application/pdf"
    assert validate_content(text, "text/plain") == "text/plain"


@pytest.mark.parametrize(
    ("content", "media_type"),
    [
        (b"not a pdf", "application/pdf"),
        (b"\xff\xfe", "text/plain"),
        (b"contains\x00null", "text/plain"),
        (b"content", "application/octet-stream"),
    ],
)
def test_invalid_or_unsupported_content_is_rejected(
    tmp_path: Path,
    content: bytes,
    media_type: str,
) -> None:
    path = write_fixture(tmp_path, "fixture.bin", content)

    with pytest.raises(ContentRejectedError):
        validate_content(path, media_type)
