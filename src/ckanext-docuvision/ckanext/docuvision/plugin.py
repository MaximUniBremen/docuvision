import logging
import json
import os
from datetime import datetime
import subprocess

import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit
from ckan.lib.uploader import ResourceUpload
import PyPDF2

from docx import Document
import openpyxl
from PIL import Image
import pytesseract

log = logging.getLogger(__name__)


class DocuvisionPlugin(plugins.SingletonPlugin):
    plugins.implements(plugins.IConfigurer)
    plugins.implements(plugins.IResourceController)
    plugins.implements(plugins.IActions)

    def update_config(self, config_):
        toolkit.add_template_directory(config_, "templates")
        toolkit.add_public_directory(config_, "public")
        toolkit.add_resource("fanstatic", "docuvision")

    def before_resource_create(self, context, resource):
        pass

    def after_resource_create(self, context, resource):
        self._process_resource(resource)

    def before_resource_update(self, context, current, resource):
        pass

    def after_resource_update(self, context, resource):
        self._process_resource(resource)

    def before_resource_delete(self, context, resource, resources):
        pass

    def after_resource_delete(self, context, resources):
        pass

    def before_resource_show(self, resource_dict):
        return resource_dict

    def get_actions(self):
        return {
            "docuvision_process_document": lambda context, data_dict: self.docuvision_process_document(
                context, data_dict
            )
        }

    def docuvision_process_document(self, context, data_dict):
        resource_id = data_dict.get("resource_id")
        if not resource_id:
            raise toolkit.ValidationError("Missing 'resource_id' in request data.")

        try:
            resource = toolkit.get_action("resource_show")(
                {"ignore_auth": True}, {"id": resource_id}
            )
        except toolkit.ObjectNotFound:
            raise toolkit.ObjectNotFound(f"Resource with id '{resource_id}' not found.")
        except Exception as e:
            raise toolkit.ValidationError(f"Error fetching resource: {str(e)}")

        try:
            self._process_resource(resource)
            return {
                "success": True,
                "message": f"Text extraction completed for resource {resource_id}.",
            }
        except Exception as e:
            raise toolkit.ValidationError(f"Error processing document: {str(e)}")

    docuvision_process_document.auth_audit_exempt = True

    # --------------------------------------------------------------------------
    # Robust document processing
    # --------------------------------------------------------------------------
    def _process_resource(self, resource):
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
            extracted_text = self._extract_text_pdf(filepath)
        elif fmt == "docx":
            extracted_text = self._extract_text_docx(filepath)
        elif fmt == "doc":
            extracted_text = self._extract_text_doc(filepath)
        elif fmt in ("xlsx", "xls"):
            extracted_text = self._extract_text_xlsx(filepath)
        elif fmt in ("jpeg", "png", "tiff", "bmp", "gif"):
            extracted_text = self._extract_text_image(filepath)
        else:
            log.info(
                f"Unsupported format for text extraction: format field='{resource.get('format')}', resolved fmt='{fmt}', resource={resource}"
            )
            return

        self._store_text_in_json(resource["id"], extracted_text)
        log.info(f"Successfully processed {fmt} for resource {resource['id']}")

    def _extract_text_pdf(self, filepath):
        text = ""
        try:
            with open(filepath, "rb") as file:
                pdf_reader = PyPDF2.PdfReader(file)
                for page in pdf_reader.pages:
                    text += (page.extract_text() or "") + "\n"
            return text
        except Exception as e:
            log.error(f"Error extracting text from PDF: {str(e)}")
            raise

    def _extract_text_docx(self, filepath):
        try:
            doc = Document(filepath)
            text = "\n".join([p.text for p in doc.paragraphs])
            return text
        except Exception as e:
            log.error(f"Error extracting text from DOCX: {str(e)}")
            raise

    def _extract_text_doc(self, filepath):
        """
        Robustly extract text from .doc (Word 97-2003) files.
        First try textract (requires antiword/catdoc), then fallback to antiword directly.
        """
        try:
            import textract

            try:
                text_bytes = textract.process(filepath)
                text = text_bytes.decode("utf-8", errors="replace")
                return text
            except Exception as textract_err:
                log.warning(
                    f"Textract failed for DOC: {textract_err}, trying antiword fallback."
                )
                # Try antiword directly if textract fails
                try:
                    output = subprocess.check_output(["antiword", filepath])
                    return output.decode("utf-8", errors="replace")
                except Exception as antiword_err:
                    log.error(
                        f"Both textract and antiword failed for DOC: {antiword_err}"
                    )
                    raise Exception(
                        f"Failed to extract DOC text: textract error: {textract_err}, antiword error: {antiword_err}"
                    )
        except Exception as e:
            log.error(f"Error extracting text from DOC: {str(e)}")
            raise

    def _extract_text_xlsx(self, filepath):
        # Try openpyxl first (for .xlsx and compatible)
        try:
            log.info(f"Attempting to read file: {filepath}")
            if not os.path.isfile(filepath):
                log.error(f"File does not exist: {filepath}")
                raise Exception(f"File does not exist: {filepath}")
            size = os.path.getsize(filepath)
            log.info(f"File size: {size} bytes")
            if size == 0:
                log.error("File size is zero bytes, cannot extract.")
                raise Exception(f"File is empty: {filepath}")
            wb = openpyxl.load_workbook(filepath, data_only=True)
            text = ""
            for ws in wb.worksheets:
                for row in ws.iter_rows(values_only=True):
                    text += (
                        "\t".join(
                            [str(cell) if cell is not None else "" for cell in row]
                        )
                        + "\n"
                    )
            return text
        except Exception as e:
            log.warning(
                f"openpyxl failed on {filepath} with error: {e}, trying xlrd as fallback."
            )
        # Fallback to xlrd if openpyxl fails (maybe it's actually an .xls file or old Excel format)
        try:
            import xlrd

            wb = xlrd.open_workbook(filepath)
            text = ""
            for sheet in wb.sheets():
                for row_idx in range(sheet.nrows):
                    row = sheet.row_values(row_idx)
                    text += (
                        "\t".join(
                            [str(cell) if cell is not None else "" for cell in row]
                        )
                        + "\n"
                    )
            return text
        except Exception as e2:
            log.error(
                f"Both openpyxl and xlrd failed to read Excel file {filepath}: {e2}"
            )
            raise Exception(
                f"Failed to extract text from Excel file. openpyxl error: {e}, xlrd error: {e2}"
            )

    def _extract_text_image(self, filepath):
        try:
            log.info(f"Attempting OCR on image file: {filepath}")
            if not os.path.isfile(filepath):
                log.error(f"Image file does not exist: {filepath}")
                raise Exception(f"Image file does not exist: {filepath}")
            size = os.path.getsize(filepath)
            log.info(f"Image file size: {size} bytes")
            if size == 0:
                log.error("Image file is empty, cannot extract.")
                raise Exception(f"Image file is empty: {filepath}")
            image = Image.open(filepath)
            text = pytesseract.image_to_string(image)
            return text
        except pytesseract.pytesseract.TesseractNotFoundError as e:
            log.error(f"Tesseract is not installed or not in PATH: {str(e)}")
            raise Exception("Tesseract OCR is not installed or not in system PATH.")
        except pytesseract.pytesseract.TesseractError as e:
            log.error(f"Tesseract OCR failed: {str(e)}")
            raise Exception(f"Tesseract OCR failed: {str(e)}")
        except Exception as e:
            log.error(f"Error extracting text from image: {str(e)}")
            raise

    def _store_text_in_json(self, resource_id, text):
        """
        Save the extracted text in resource extras as a JSON object.
        """
        try:
            # Get CKAN actions for package_show and package_update
            package_show = toolkit.get_action("package_show")
            package_update = toolkit.get_action("package_update")
            resource_show = toolkit.get_action("resource_show")
            resource = resource_show({"ignore_auth": True}, {"id": resource_id})
            dataset_id = resource["package_id"]

            # Fetch the current state of the dataset
            dataset = package_show({"ignore_auth": True}, {"id": dataset_id})

            # Create "extras" field in the JSON if it doesn't exist yet
            if "extras" not in dataset:
                dataset["extras"] = []

            # Convert the resource's "extras" (a list of dicts) into a dictionary for easier manipulation
            extras_dict = {}
            for extra_item in dataset.get("extras", []):
                extras_dict[extra_item["key"]] = extra_item["value"]

            # Build JSON structure to store extracted text and metadata
            text_data = {
                "extracted_text": text,
                "extraction_date": datetime.utcnow().isoformat(),
                "version": "1.1",
            }

            extras_dict["extracted_text_data"] = json.dumps(text_data)

            # Convert dictionary back into the list-of-dicts format CKAN expects
            new_extras_list = []
            for k, v in extras_dict.items():
                new_extras_list.append({"key": k, "value": v})

            # Assign updated extras back to the resource
            dataset["extras"] = new_extras_list

            # Save the updated dataset
            package_update({"ignore_auth": True}, dataset)

        except Exception as e:
            # Log and re-raise exceptions for error reporting
            log.error(f"Error storing text in JSON: {str(e)}")
            raise
