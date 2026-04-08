"""Извлечение текста из вложений резюме (pdf, docx, doc, txt)."""

from __future__ import annotations

import io
import logging
import re
import shutil
import subprocess
import tempfile
from typing import Final

logger = logging.getLogger(__name__)

_EXT_PDF: Final = "pdf"
_EXT_DOCX: Final = "docx"
_EXT_DOC: Final = "doc"
_EXT_TXT: Final = "txt"


def normalize_extension(filename: str | None, mime_type: str | None) -> str | None:
    name = (filename or "").lower()
    for ext in (_EXT_PDF, _EXT_DOCX, _EXT_DOC, _EXT_TXT):
        if name.endswith(f".{ext}"):
            return ext
    mime = (mime_type or "").lower().strip()
    if mime == "application/pdf":
        return _EXT_PDF
    if mime in (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ):
        return _EXT_DOCX
    if mime == "application/msword":
        return _EXT_DOC
    if mime in ("text/plain", "application/octet-stream") and name.endswith(".txt"):
        return _EXT_TXT
    if mime == "text/plain":
        return _EXT_TXT
    return None


def extract_text_from_bytes(file_type: str, data: bytes) -> str:
    if not data:
        return ""
    ft = (file_type or "").lower().strip()
    try:
        if ft == _EXT_TXT:
            return _extract_txt(data)
        if ft == _EXT_PDF:
            return _extract_pdf(data)
        if ft == _EXT_DOCX:
            return _extract_docx(data)
        if ft == _EXT_DOC:
            return _extract_doc(data)
    except Exception as exc:
        logger.warning("attachment extract failed (%s): %s", ft, exc)
    return ""


def _extract_txt(data: bytes) -> str:
    for enc in ("utf-8", "cp1251", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    parts: list[str] = []
    for page in reader.pages:
        t = page.extract_text()
        if t:
            parts.append(t)
    return "\n".join(parts)


def _extract_docx(data: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs if p.text)


def _extract_doc(data: bytes) -> str:
    if shutil.which("antiword"):
        with tempfile.NamedTemporaryFile(suffix=".doc", delete=False) as tmp:
            tmp.write(data)
            path = tmp.name
        try:
            proc = subprocess.run(
                ["antiword", path],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout:
                return proc.stdout
        finally:
            try:
                import os

                os.unlink(path)
            except OSError:
                pass
    # Старый .doc без antiword: пробуем вытащить читаемые фрагменты (слабая эвристика)
    raw = data.decode("latin-1", errors="ignore")
    chunks = re.findall(r"[\x20-\x7e\u0400-\u04ff]{4,}", raw)
    return "\n".join(chunks[:500])
