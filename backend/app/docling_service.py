from __future__ import annotations

import os
import time
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

from docling.backend.docling_parse_backend import DoclingParseDocumentBackend
from docling.datamodel.accelerator_options import AcceleratorOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.layout_model_specs import DOCLING_LAYOUT_HERON
from docling.datamodel.pipeline_options import (
    EasyOcrOptions,
    LayoutOptions,
    PdfPipelineOptions,
    TableStructureOptions,
)
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.pipeline.standard_pdf_pipeline import StandardPdfPipeline

PIPELINE_METADATA = {
    "pipeline": "standard_pdf",
    "backend": "docling_parse",
    "displayName": "Heron + EasyOCR",
    "layoutModel": DOCLING_LAYOUT_HERON.name,
    "ocrEngine": "easyocr",
    "tableStructureModel": "tableformer",
}


def _extract_item_text(item: Any, document: Any) -> str:
    text = getattr(item, "text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()

    caption_text = getattr(item, "caption_text", None)
    if callable(caption_text):
        try:
            value = caption_text(document)
        except Exception:
            value = None
        if isinstance(value, str) and value.strip():
            return value.strip()

    name = getattr(item, "name", None)
    if isinstance(name, str) and name.strip():
        return name.strip()

    return ""


def _read_bool_env(name: str) -> bool | None:
    value = os.getenv(name)
    if value is None:
        return None

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean value for {name}: {value}")


def _read_ocr_languages() -> list[str]:
    raw_value = os.getenv("DOCLING_EASYOCR_LANGS", "en")
    languages = [value.strip() for value in raw_value.split(",") if value.strip()]
    return languages or ["en"]


@lru_cache(maxsize=1)
def get_converter() -> DocumentConverter:
    pipeline_options = PdfPipelineOptions(
        accelerator_options=AcceleratorOptions(
            num_threads=int(os.getenv("DOCLING_NUM_THREADS", "4")),
            device=os.getenv("DOCLING_DEVICE", "auto"),
        ),
        do_ocr=True,
        ocr_options=EasyOcrOptions(
            lang=_read_ocr_languages(),
            use_gpu=_read_bool_env("DOCLING_EASYOCR_USE_GPU"),
            recog_network=os.getenv("DOCLING_EASYOCR_RECOG_NETWORK", "standard"),
        ),
        do_table_structure=True,
        table_structure_options=TableStructureOptions(do_cell_matching=True),
        layout_options=LayoutOptions(model_spec=DOCLING_LAYOUT_HERON),
        generate_page_images=False,
    )

    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                backend=DoclingParseDocumentBackend,
                pipeline_cls=StandardPdfPipeline,
                pipeline_options=pipeline_options,
            )
        }
    )


def convert_pdf(source_path: Path) -> dict[str, Any]:
    start_time = time.perf_counter()
    result = get_converter().convert(source=source_path)
    elapsed_seconds = time.perf_counter() - start_time
    document = result.document

    pages: dict[int, dict[str, Any]] = {}
    for page_no, page in sorted(document.pages.items()):
        pages[page_no] = {
            "pageNo": page_no,
            "width": page.size.width,
            "height": page.size.height,
            "items": [],
        }

    label_counts: Counter[str] = Counter()
    total_items = 0

    for item, level in document.iterate_items():
        label = getattr(item, "label", None)
        if label is None:
            continue

        label_value = getattr(label, "value", str(label))
        item_text = _extract_item_text(item, document)
        prov_items = getattr(item, "prov", None) or []

        for prov_index, prov in enumerate(prov_items):
            page = pages.get(prov.page_no)
            if page is None:
                continue

            bbox = prov.bbox.to_top_left_origin(page["height"])
            left, top, right, bottom = bbox.as_tuple()

            page["items"].append(
                {
                    "id": f"{item.self_ref}:{prov_index}",
                    "label": label_value,
                    "level": level,
                    "text": item_text,
                    "bbox": {
                        "left": left,
                        "top": top,
                        "width": max(0.0, right - left),
                        "height": max(0.0, bottom - top),
                    },
                }
            )
            label_counts[label_value] += 1
            total_items += 1

    for page in pages.values():
        page["items"].sort(
            key=lambda item: (
                item["bbox"]["top"],
                item["bbox"]["left"],
                -(item["bbox"]["width"] * item["bbox"]["height"]),
            )
        )

    runtime = {
        **PIPELINE_METADATA,
        "ocrLang": _read_ocr_languages(),
        "elapsedSeconds": round(elapsed_seconds, 3),
    }

    return {
        "markdown": document.export_to_markdown(),
        "pages": list(pages.values()),
        "summary": {
            "pageCount": len(pages),
            "itemCount": total_items,
            "labels": dict(sorted(label_counts.items())),
        },
        "runtime": runtime,
    }
