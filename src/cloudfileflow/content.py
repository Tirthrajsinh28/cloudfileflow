import json
from pathlib import Path


class ContentRejectedError(ValueError):
    pass


def validate_content(path: Path, declared_media_type: str) -> str:
    content = path.read_bytes()
    if declared_media_type == "application/pdf":
        if not content.startswith(b"%PDF-"):
            raise ContentRejectedError("PDF signature is missing")
        return "application/pdf"

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ContentRejectedError("Content is not valid UTF-8") from error

    if "\x00" in text:
        raise ContentRejectedError("Text content contains a null byte")

    if declared_media_type == "application/json":
        try:
            json.loads(text)
        except json.JSONDecodeError as error:
            raise ContentRejectedError("JSON syntax is invalid") from error
        return "application/json"

    if declared_media_type == "text/plain":
        return "text/plain"

    raise ContentRejectedError("Declared media type is unsupported")
