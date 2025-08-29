import logging
import mimetypes
import os
import re
import tempfile
import ckan.plugins as plugins
import requests

# Create a logger for logging information and errors
log = logging.getLogger(__name__)


def upload_pdf_from_url(file_url, dataset_id):
    """
    Downloads a PDF file from a URL and uploads it to CKAN.
    """
    try:
        log.info(f"Downloading file from {file_url}")
        response = requests.get(file_url, stream=True, timeout=30)
        response.raise_for_status()

        # Try to get original filename from Content-Disposition header
        cd = response.headers.get("Content-Disposition")
        original_name = None
        if cd:
            match = re.findall("filename=\"?([^\";]+)\"?", cd)
            if match:
                original_name = match[0]

        # Fallback: take from URL
        if not original_name:
            original_name = os.path.basename(file_url.split("?")[0]) or "document.pdf"

        # Ensure it ends with .pdf
        if not original_name.lower().endswith(".pdf"):
            original_name += ".pdf"

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            for chunk in response.iter_content(chunk_size=8192):
                tmp.write(chunk)
            tmp_path = tmp.name

        log.info(f"File downloaded to temp: {tmp_path}, now uploading to CKAN")
        upload_to_ckan(tmp_path, dataset_id, original_name)

        # Clean up temp file
        os.remove(tmp_path)
        log.info(f"Temp file {tmp_path} removed after upload")

    except requests.Timeout:
        log.error(f"Timeout while downloading file: {file_url}")
    except Exception as e:
        log.error(f"Error downloading/uploading file {file_url}: {e}")


def upload_to_ckan(file_path, dataset_id, original_name=None):
    """
    Uploads a text file to CKAN as a resource.
    """
    try:
        url = "http://localhost:5000/api/3/action/resource_create"

        # Determine mimetype
        mimetype, _ = mimetypes.guess_type(file_path)
        if mimetype is None:
            mimetype = "text/plain"  # Default to plain text

        # Use file extension (without the dot) as format
        ext = os.path.splitext(original_name or file_path)[1].lstrip(".").lower() or "bin"

        resource_name = original_name or os.path.basename(file_path)

        headers = {
            "Authorization": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiJZVHFpZTRTWldwZXRSZTlrMEZRZHVUU2lDV1VnZ0RPTlVBTHQwZlg1NnY4IiwiaWF0IjoxNzU1OTExMTczfQ.ksAFaQ87-R9Pdd09blYiUPCHlPVpCTXpKurOIOA3m2I"
        }
        data = {"package_id": dataset_id, "name": resource_name, "format": ext,
                "mimetype": mimetype}

        log.info(f"Uploading file: {resource_name} with mimetype: {mimetype}")

        # Ensure the file is closed properly
        with open(file_path, "rb") as file:
            files = {
                "upload": (resource_name, file, mimetype)
            }
            response = requests.post(url, headers=headers, data=data, files=files, timeout=100)

        log.info(f"Response Status: {response.status_code}")
        log.info(f"Response Text: {response.text}")

        result = response.json()

        if result.get("success"):
            log.info(f"Successfully uploaded {resource_name} to CKAN dataset {dataset_id}")
            return result["result"]["id"]
        else:
            log.error(f"Failed to upload {resource_name}: {result}")
            return None

    except requests.exceptions.Timeout:
        log.error("Request to CKAN timed out.")
        return None
    except requests.exceptions.RequestException as e:
        log.error(f"Request failed: {e}")
        return None
    except Exception as e:
        log.error(f"Error uploading to CKAN: {e}")
        return None
