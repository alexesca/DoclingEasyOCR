# Docling Heron + EasyOCR Layout Viewer

Containerized PDF layout viewer built with:

- Docling's standard PDF pipeline
- the `docling_layout_heron` layout model
- EasyOCR for OCR
- Docling's table structure extraction
- FastAPI for upload and conversion
- a Vite frontend using PDF.js to overlay detected regions

## What it does

Upload a PDF and the app will:

1. run Docling with the Heron layout model, EasyOCR, and table structure extraction on the backend
2. extract page provenance boxes from the resulting `DoclingDocument`
3. render the source PDF in the browser
4. overlay the detected layout regions directly on each page
5. show the exported Markdown, timing, and a label legend beside the viewer

## Run with Docker

```bash
docker compose up --build
```

Then open `http://localhost:8001`.

If you also run the Granite VLM viewer from `/home/miguel/git/DoclingViewer`, you can compare them side by side:

- Granite VLM viewer: `http://localhost:8000`
- Heron + EasyOCR viewer: `http://localhost:8001`

## Notes

- The first run will download Docling's local model artifacts, including the Heron layout model, table structure model, and EasyOCR assets.
- This implementation currently accepts PDF uploads only, because the frontend viewer is intentionally centered on PDF page rendering plus layout overlays.
- Conversion is synchronous for now. Large PDFs will take noticeable time while the request is processed.
- The default OCR language is `en`. Override it with `DOCLING_EASYOCR_LANGS=en,es` in `docker-compose.yml` if you need broader language coverage.

## Backend model configuration

The backend uses Docling's standard PDF pipeline with an explicit Heron layout model and EasyOCR:

```python
pipeline_options = PdfPipelineOptions(
    do_ocr=True,
    ocr_options=EasyOcrOptions(lang=["en"]),
    do_table_structure=True,
    table_structure_options=TableStructureOptions(do_cell_matching=True),
    layout_options=LayoutOptions(model_spec=DOCLING_LAYOUT_HERON),
)
```

This matches Docling's documented standard PDF workflow while pinning the Heron layout model instead of relying on the default implicitly.
