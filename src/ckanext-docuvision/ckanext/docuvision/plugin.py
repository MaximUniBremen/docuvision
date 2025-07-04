import logging
import json
import mimetypes
import os
from datetime import datetime
import subprocess
import cv2
import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit
import requests
from ckan.lib.uploader import ResourceUpload
import PyPDF2
from pdf2image import convert_from_path
from docx import Document
import openpyxl
from PIL import Image
import pytesseract

# Create a logger for logging information and errors
log = logging.getLogger(__name__)


class DocuvisionPlugin(plugins.SingletonPlugin):
    """
    DocuvisionPlugin for processing PDF resources in CKAN.

    Implements:
    - IConfigurer: Allows adding custom templates, public resources, and fanstatic.
    - IResourceController: Hooks into resource creation/update events.
    - IActions: Defines a custom CKAN action API endpoint (docuvision_process_pdf).
    """

    # Register plugin interfaces
    plugins.implements(plugins.IConfigurer)          # For configuring CKAN (templates, public files, etc.)
    plugins.implements(plugins.IResourceController)  # Monitor and modify resource lifecycle events
    plugins.implements(plugins.IActions)             # Register custom actions in the CKAN API

    # --------------------------------------------------------------------------
    # IConfigurer
    # --------------------------------------------------------------------------
    def update_config(self, config_):
        """
        Called when CKAN loads this plugin to update or add configuration items.
        Here we add the plugin's templates, public files, and fanstatic resources.
        """
        # Add template directory so CKAN can find custom templates
        toolkit.add_template_directory(config_, "templates")
        # Add public directory for static files (images, CSS, etc.)
        toolkit.add_public_directory(config_, "public")
        # Register fanstatic resources (CSS/JS) to be served by CKAN
        toolkit.add_resource("fanstatic", "docuvision")

    # --------------------------------------------------------------------------
    # IResourceController - required methods
    # --------------------------------------------------------------------------
    def before_resource_create(self, context, resource):
        """
        Triggered right before a resource is created.
        Currently no specific action is taken here.
        """
        pass

    def after_resource_create(self, context, resource):
        """
        Triggered right after a resource is created.
        Checks if resource is a PDF; if so, calls _process_pdf for text extraction.
        """
        self._process_resource(resource)

    def before_resource_update(self, context, current, resource):
        """
        Triggered before a resource is updated.
        Currently no specific action is taken here.
        """
        pass

    def after_resource_update(self, context, resource):
        """
        Triggered right after a resource is updated.
        """
        self._process_resource(resource)

    def before_resource_delete(self, context, resource, resources):
        """
        Triggered before a resource is deleted.
        Currently no specific action is taken here.
        """
        pass

    def after_resource_delete(self, context, resources):
        """
        Triggered right after a resource is deleted.
        Currently no specific action is taken here.
        """
        pass

    def before_resource_show(self, resource_dict):
        """
        Triggered before showing resource details to the user.
        Any modifications to resource_dict here will affect the displayed or returned data.
        """
        return resource_dict  # Returning unmodified resource_dict

    # --------------------------------------------------------------------------
    # IActions - Custom CKAN Action API endpoints
    # --------------------------------------------------------------------------

    def get_actions(self):
        """
        Returns a dict mapping action names to functions.
        This makes the defined actions available via CKAN's action API.
        """
        return {
            "docuvision_process_document": lambda context, data_dict: self.docuvision_process_document(
                context, data_dict
            )
        }

    def docuvision_process_document(self, context, data_dict):
        """
        CKAN action: /api/3/action/docuvision_process_document
        Expects JSON data containing "resource_id" of the resource.
        Performs PDF text extraction and updates the resource with extracted information.
        """
        # Validate the required param 'resource_id'
        resource_id = data_dict.get("resource_id")
        if not resource_id:
            raise toolkit.ValidationError("Missing 'resource_id' in request data.")

        # Look up the resource in CKAN by ID
        try:
            resource = toolkit.get_action("resource_show")(
                {"ignore_auth": True}, {"id": resource_id}
            )
        except toolkit.ObjectNotFound:
            raise toolkit.ObjectNotFound(f"Resource with id '{resource_id}' not found.")
        except Exception as e:
            raise toolkit.ValidationError(f"Error fetching resource: {str(e)}")

        # Process the resource and return success if extraction runs smoothly
        try:
            self._process_resource(resource)
            return {
                "success": True,
                "message": f"Text extraction completed for resource {resource_id}.",
            }
        except Exception as e:
            raise toolkit.ValidationError(f"Error processing document: {str(e)}")

    # By default, CKAN logs action usage for auditing. This exempts it from auditing.
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
            # Open PDF in read-binary mode
            with open(filepath, "rb") as file:
                pdf_reader = PyPDF2.PdfReader(file)
                # Loop through each page to extract text
                for page in pdf_reader.pages:
                    text += (page.extract_text() or "") + "\n"
            if len(text)<5:
                text = self._extract_text_tesseract(filepath)
            return text
        except Exception as e:
            log.error(f"Error extracting text from PDF: {str(e)}")
            raise

    def _extract_text_tesseract(self, filepath):
        """
        Reads the PDF at the given filepath and returns extracted text as a string.
        """
        try:
            # Convert PDF pages to images
            images = convert_from_path(filepath, poppler_path="/usr/bin")
            extracted_text = []

            for i, image in enumerate(images):
                # Convert PIL image to RGB just to be sure
                img_rgb = image.convert("RGB")

                # Use pytesseract to extract text
                text = pytesseract.image_to_string(img_rgb)
                extracted_text.append(text)

            return "\n".join(extracted_text)

        except Exception as e:
            print(f"Error extracting text: {e}")
            return ""

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
        Saves the extracted text in resource extras as a JSON object.
        """
        try:
            # Get CKAN actions for package_show and package_update
            package_show = toolkit.get_action("package_show")
            package_update = toolkit.get_action("package_update")
            resource_show = toolkit.get_action("resource_show")
            resource = resource_show({"ignore_auth": True}, {"id": resource_id})
            dataset_id = resource["package_id"]

            filename = resource_id

            # Fetch the current dataset object
            dataset = package_show({"ignore_auth": True}, {"id": dataset_id})

            # Create "extras" field in the JSON if it doesn't exist yet
            if "extras" not in dataset:
                dataset["extras"] = []

            # Convert the resource's "extras" (a list of dicts) into a dictionary for easier manipulation
            extras_dict = {}
            for extra_item in dataset.get("extras", []):
                extras_dict[extra_item["key"]] = extra_item["value"]

            # Save each text extraction to a file and upload it to CKAN
            file_resources = {}
            if text:
                file_path = self._store_text_as_txt(text, filename)
                log.info(file_path)
                if file_path:
                    uploaded_resource_id = self._upload_to_ckan(file_path, dataset_id)
                    if uploaded_resource_id:
                        file_resources[filename] = uploaded_resource_id

            # Build JSON structure to store extracted text and metadata
            text_data = {
                "text_length": str(len(text)),
                "extracted_text": text,
                "extraction_date": datetime.utcnow().isoformat(),
                "version": "1.1",
            }

            # Put the new data under a custom key
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
            log.error(f"Error storing text in JSON: {str(e)}")
            raise

    def _upload_to_ckan(self, file_path, dataset_id):
        """
        Uploads a text file to CKAN as a resource.
        """
        try:
            url = "http://localhost:5000/api/3/action/resource_create"

            # Determine mimetype
            mimetype, _ = mimetypes.guess_type(file_path)
            if mimetype is None:
                mimetype = "text/plain"  # Default to plain text

            log.info(f"Uploading file: {file_path} with mimetype: {mimetype}")
            headers = {
                "Authorization": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiJqV3p6UHN4ZXdfaHZjZDI2elhBbDlpMmZEeW1EWVhBZ1k4dVVCc1UzV1dZIiwiaWF0IjoxNzUxNjE3NTMzfQ.Y2mEqDl_Tir8loe1nS3mw1E-QvV09kzas6x6WVkhLCg"
            }
            data = {"package_id": dataset_id, "name": os.path.basename(file_path),  "format": "txt",
                    "mimetype": f"{mimetype}; charset=utf-8" }

            log.info(f"Uploading file: {file_path}")

            # Ensure the file is closed properly
            with open(file_path, "rb") as file:
                files = {
                    "upload": (os.path.basename(file_path), file, f"{mimetype}; charset=utf-8")
                }
                response = requests.post(url, headers=headers, data=data, files=files, timeout=10)

            log.info(f"Response Status: {response.status_code}")
            log.info(f"Response Text: {response.text}")

            result = response.json()

            if result.get("success"):
                log.info(f"Successfully uploaded {file_path} to CKAN dataset {dataset_id}")
                return result["result"]["id"]
            else:
                log.error(f"Failed to upload {file_path}: {result}")
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

    def _store_text_as_txt(self, text_content, filename):
        """
        Save extracted text as a .txt file in a temporary file path.
        """
        try:
            file_path = f"/tmp/{filename}.txt"
            with open(file_path, "w", encoding="utf-8") as file:
                file.write(text_content)
            return file_path
        except Exception as e:
            log.error(f"Error saving text to file {filename}: {e}")
            return None
