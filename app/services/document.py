"""Document service (brief §6).

PyMuPDF text extraction; if there is little/no text layer, OCR the rendered
pages. Embedded images are run through the image service (including ELA) — this
catches the pasted-stamp forgery. Extracted text goes to the text service.
Structural inconsistencies (many distinct fonts) are a mild signal.
"""
from __future__ import annotations

from app.core.logging import get_logger
from app.schemas.analysis import ContentType, ServiceOutput, Signal

log = get_logger("document")


def analyze(pdf_bytes: bytes, db=None) -> ServiceOutput:
    from app.services import image as image_service
    from app.services import text as text_service

    signals: list[Signal] = []
    text = ""
    fonts: set[str] = set()
    embedded_images: list[bytes] = []

    try:
        import fitz  # PyMuPDF

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        for page in doc:
            text += page.get_text("text") + "\n"
            for f in page.get_fonts(full=True):
                fonts.add(f[3])
            for img in page.get_images(full=True):
                try:
                    xref = img[0]
                    pix = fitz.Pixmap(doc, xref)
                    if pix.n >= 5:  # CMYK/alpha -> convert
                        pix = fitz.Pixmap(fitz.csRGB, pix)
                    embedded_images.append(pix.tobytes("png"))
                except Exception:  # noqa: BLE001
                    continue

        # Little/no text layer -> OCR the rendered pages.
        if len(text.strip()) < 40:
            for page in doc:
                pix = page.get_pixmap(dpi=150)
                ocr = image_service._ocr_text(pix.tobytes("png"))  # noqa: SLF001
                text += ocr + "\n"
        doc.close()
    except Exception as exc:  # noqa: BLE001
        log.warning("PDF parse failed: %s", exc)
        signals.append(Signal(
            name="doc_parse", label="This document could not be fully read",
            risk=0.2, direction="neutral", detail="PDF parsing failed.",
            raw={"error": str(exc)[:120]},
        ))

    if len(fonts) >= 6:
        signals.append(Signal(
            name="doc_fonts",
            label="The document mixes an unusual number of fonts",
            risk=0.4, direction="risk",
            detail=f"{len(fonts)} distinct fonts — can indicate pasted-in content.",
            raw={"font_count": len(fonts), "forensic": True},
        ))

    sub_outputs = []
    # Run embedded images (stamps/signatures) through the forensic image check.
    for img_bytes in embedded_images[:6]:
        try:
            sub = image_service.analyze(img_bytes, db)
            sub_outputs.append(sub)
            signals.extend(s for s in sub.signals if s.raw.get("forensic"))
        except Exception as exc:  # noqa: BLE001
            log.info("embedded image check failed: %s", exc)

    if text.strip():
        sub = text_service.analyze(text, db)
        sub_outputs.append(sub)
        signals.extend(sub.signals)

    return ServiceOutput(
        content_type=ContentType.document,
        extracted_text=text.strip() or None,
        signals=signals,
        sub_outputs=sub_outputs,
        notes=[f"{len(embedded_images)} embedded image(s)"],
    )
