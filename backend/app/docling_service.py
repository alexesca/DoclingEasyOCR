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


def _extract_assembled_text(element: Any) -> str:
    text = getattr(element, "text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()

    cluster = getattr(element, "cluster", None)
    cells = getattr(cluster, "cells", None) or []
    return " ".join(
        cell.text.strip()
        for cell in cells
        if isinstance(getattr(cell, "text", None), str) and cell.text.strip()
    )


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


def _read_bool_env_default(name: str, default: bool) -> bool:
    value = _read_bool_env(name)
    return default if value is None else value


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
        images_scale=float(os.getenv("DOCLING_IMAGES_SCALE", "2.0")),
        do_ocr=True,
        ocr_options=EasyOcrOptions(
            lang=_read_ocr_languages(),
            force_full_page_ocr=_read_bool_env_default(
                "DOCLING_EASYOCR_FORCE_FULL_PAGE",
                True,
            ),
            confidence_threshold=float(
                os.getenv("DOCLING_EASYOCR_CONFIDENCE_THRESHOLD", "0.25")
            ),
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

    for result_page in result.pages:
        page = pages.get(result_page.page_no)
        assembled = getattr(result_page, "assembled", None)
        elements = getattr(assembled, "elements", None) or []
        if page is None:
            continue

        for element_index, element in enumerate(elements):
            label = getattr(element, "label", None)
            cluster = getattr(element, "cluster", None)
            bbox = getattr(cluster, "bbox", None)
            if label is None or bbox is None:
                continue

            left, top, right, bottom = bbox.as_tuple()
            label_value = getattr(label, "value", str(label))

            page["items"].append(
                {
                    "id": f"page-{result_page.page_no}-element-{element_index}",
                    "label": label_value,
                    "level": 1,
                    "text": _extract_assembled_text(element),
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
