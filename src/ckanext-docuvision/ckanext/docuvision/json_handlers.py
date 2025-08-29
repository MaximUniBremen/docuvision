from .uploaders import upload_pdf_from_url

import logging
import pytesseract

# Create a logger for logging information and errors
log = logging.getLogger(__name__)


def upload_from_json(json_obj, dataset_id):
    """
    Handles a JSON object containing document metadata and uploads
    the corresponding files to CKAN.
    """

    try:
        # Case 1: JSON is from TED
        if "releases" in json_obj:
            for release in json_obj.get("releases", []):
                for doc in release.get("tender", {}).get("documents", []):
                    file_url = doc.get("url")
                    if file_url:
                        log.info(f"Found tender document URL: {file_url}")
                        upload_pdf_from_url(file_url, dataset_id)

        # Case 2: JSON is from Bescha
        else:
            pdf_links = json_obj.get("links", {}).get("pdf", {})
            deu_url = pdf_links.get("DEU")
            if deu_url:
                log.info(f"Found German PDF URL: {deu_url}")

                # Now fetch and upload this file
                upload_pdf_from_url(deu_url, dataset_id)
            else:
                log.warning("No German (DEU) PDF URL found in JSON")

    except Exception as e:
        log.error(f"Error while uploading from JSON: {e}")
