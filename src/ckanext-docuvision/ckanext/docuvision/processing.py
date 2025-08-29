from .extractors import extract_text_image, extract_text_docx, extract_text_xlsx, extract_text_doc, extract_text_pdf, extract_text_tesseract
from .storage import store_text_in_json
from .json_handlers import upload_from_json

import logging
import json
import os
import re
import ckan.plugins as plugins
from ckan.lib.uploader import ResourceUpload
import pytesseract

# Create a logger for logging information and errors
log = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Robust document processing
# --------------------------------------------------------------------------
def process_resource(resource):
    """
    Determines resource type robustly and extracts text accordingly.
    """
    format_map = {
        "pdf": "pdf",
        "doc": "doc",
        "docx": "docx",
        "xls": "xls",
        "xlsx": "xlsx",
        "jpeg": "jpeg",
        "jpg": "jpeg",
        "png": "png",
        "tiff": "tiff",
        "tif": "tiff",
        "bmp": "bmp",
        "gif": "gif",
        "json": "json",
    }

    # Normalize the declared format of the resource (e.g., 'CSV', 'json') by:
    # 1. Fetching it from the resource dict and converting to lowercase.
    # 2. Mapping it to a known internal format using `format_map` (e.g., 'csv' -> 'csv', 'application/json' -> 'json').

    fmt = (resource.get("format") or "").lower().strip()
    fmt = format_map.get(fmt, fmt)

    # Attempt to determine the format based on the resource URL or name:
    # 1. Get the URL, or fall back to the name if the URL is missing.
    # 2. Extract the file extension from the URL (e.g., '.csv', '.json').
    # 3. Clean the extension and map it to the internal format using `format_map`.

    url = resource.get("url", "") or resource.get("name", "")
    _, ext = os.path.splitext(url)
    ext = ext.lower().lstrip(".")
    ext_fmt = format_map.get(ext, ext)

    # If the format inferred from the file extension differs from the declared format,
    # and it is a valid format in our format_map, prefer the one from the extension.
    # This helps fix cases where the declared format is inaccurate or missing.

    if ext_fmt != fmt and ext_fmt in format_map.values():
        fmt = ext_fmt  # Trust the file extension over the declared format

    log.info(
        f"Resource format field: {resource.get('format')}, file/url: {url}, resolved fmt: {fmt}"
    )

    upload = ResourceUpload(resource)
    filepath = upload.get_path(resource["id"])

    if not os.path.isfile(filepath):
        log.error(
            f"File not found for resource {resource['id']}: {filepath} (resource: {resource})"
        )
        raise Exception(f"File not found: {filepath}")

    if fmt == "pdf":
        extracted_text = extract_text_pdf(filepath)
    elif fmt == "docx":
        extracted_text = extract_text_docx(filepath)
    elif fmt == "doc":
        extracted_text = extract_text_doc(filepath)
    elif fmt in ("xlsx", "xls"):
        extracted_text = extract_text_xlsx(filepath)
    elif fmt in ("jpeg", "png", "tiff", "bmp", "gif"):
        extracted_text = extract_text_image(filepath)
    elif fmt == "json":
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read().strip()
                # Replace MongoDB ObjectId("...") with just "...".
                cleaned = re.sub(r'ObjectId\("([0-9a-f]+)"\)', r'"\1"', content)
                log.info(f"Raw JSON snippet: {content[:200]}")  # debugging
                json_obj = json.loads(cleaned)
            upload_from_json(json_obj, resource["package_id"])
            return
        except Exception as e:
            log.error(f"Error processing JSON resource {resource['id']}: {e}")
            return
    else:
        log.info(
            f"Unsupported format for text extraction: format field='{resource.get('format')}', resolved fmt='{fmt}', resource={resource}"
        )
        return

    url = resource.get("url", "") or resource.get("name", "")
    original_name = os.path.basename(url.split("?")[0])

    store_text_in_json(resource["id"], extracted_text, original_name)
    log.info(f"Successfully processed {fmt} for resource {resource['id']}")
