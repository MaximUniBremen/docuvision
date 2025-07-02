import logging
import json
import mimetypes
import os
from datetime import datetime

import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit
import requests
from ckan.lib.uploader import ResourceUpload
import PyPDF2

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
        toolkit.add_template_directory(config_, 'templates')
        # Add public directory for static files (images, CSS, etc.)
        toolkit.add_public_directory(config_, 'public')
        # Register fanstatic resources (CSS/JS) to be served by CKAN
        toolkit.add_resource('fanstatic', 'docuvision')

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
        if resource.get('format', '').lower() == 'pdf':
            self._process_pdf(resource)

    def before_resource_update(self, context, current, resource):
        """
        Triggered before a resource is updated.
        Currently no specific action is taken here.
        """
        pass

    def after_resource_update(self, context, resource):
        """
        Triggered right after a resource is updated.
        Checks if resource is a PDF; if so, calls _process_pdf for text extraction.
        """
        if resource.get('format', '').lower() == 'pdf':
            self._process_pdf(resource)

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
            'docuvision_process_pdf': lambda context, data_dict: self.docuvision_process_pdf(context, data_dict)
        }

    def docuvision_process_pdf(self, context, data_dict):
        """
        CKAN action: /api/3/action/docuvision_process_pdf
        Expects JSON data containing "resource_id" of the PDF resource.
        Performs PDF text extraction and updates the resource with extracted information.
        """
        # Validate the required param 'resource_id'
        resource_id = data_dict.get('resource_id')
        if not resource_id:
            raise toolkit.ValidationError("Missing 'resource_id' in request data.")

        # Look up the resource in CKAN by ID
        try:
            resource = toolkit.get_action('resource_show')(
                {'ignore_auth': True},
                {'id': resource_id}
            )
        except toolkit.ObjectNotFound:
            raise toolkit.ObjectNotFound(f"Resource with id '{resource_id}' not found.")
        except Exception as e:
            raise toolkit.ValidationError(f"Error fetching resource: {str(e)}")

        # Verify the resource is a PDF
        if resource.get('format', '').lower() != 'pdf':
            raise toolkit.ValidationError("Resource format is not PDF or is missing.")

        # Process the PDF and return success if extraction runs smoothly
        try:
            self._process_pdf(resource)
            return {
                'success': True,
                'message': f"PDF text extraction completed for resource {resource_id}."
            }
        except Exception as e:
            raise toolkit.ValidationError(f"Error processing PDF: {str(e)}")

    # By default, CKAN logs action usage for auditing. This exempts it from auditing.
    docuvision_process_pdf.auth_audit_exempt = True

    # --------------------------------------------------------------------------
    # Helper methods for PDF processing
    # --------------------------------------------------------------------------
    def _process_pdf(self, resource):
        """
        Internal helper to open, read, and store data extracted from a PDF resource.
        """
        # Attempt to open, extract, and store text; log any errors
        try:
            # ResourceUpload helps get the path to the resource file on the server
            upload = ResourceUpload(resource)
            filepath = upload.get_path(resource['id'])

            # Extract text from the actual file
            extracted_text_var = self._extract_text(filepath)

            # Store extracted data in CKAN resource extras
            self._store_text_in_json(resource['id'], extracted_text_var)

            # Log a success message
            log.info(f"Successfully processed PDF for resource {resource['id']}")
        except Exception as e:
            # Log and re-raise exception for higher-level handling
            log.error(f"Error processing PDF for resource {resource['id']}: {str(e)}")
            raise

    def _extract_text(self, filepath):
        """
        Reads the PDF at the given filepath and returns extracted text as a string.
        """
        text = ""
        try:
            # Open PDF in read-binary mode
            with open(filepath, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                # Loop through each page to extract text
                for page in pdf_reader.pages:
                    text += (page.extract_text() or "") + "\n"
            return text
        except Exception as e:
            # Log error and re-raise
            log.error(f"Error extracting text from PDF: {str(e)}")
            raise

    def _store_text_in_json(self, resource_id, text):
        """
        Saves the extracted text in resource extras as a JSON object.
        """
        try:
            # Get CKAN actions
            resource_show = toolkit.get_action('resource_show')
            package_show = toolkit.get_action('package_show')
            package_update = toolkit.get_action('package_update')

            # Use the resource ID to find its dataset
            resource = resource_show({'ignore_auth': True}, {'id': resource_id})
            dataset_id = resource['package_id']

            filename = dataset_id + resource_id

            # Fetch the current dataset object
            dataset = package_show({'ignore_auth': True}, {'id': dataset_id})

            # Ensure 'extras' exists
            if "extras" not in dataset:
                dataset["extras"] = []

            # Convert extras to a dictionary
            extras_dict = {item['key']: item['value'] for item in dataset['extras']}

            # Save each text extraction to a file and upload it to CKAN
            file_resources = {}
            if text:
                file_path = self._store_text_as_txt(text, filename)
                log.info(file_path)
                if file_path:
                    uploaded_resource_id = self._upload_to_ckan(file_path, dataset_id)
                    if uploaded_resource_id:
                        file_resources[filename] = uploaded_resource_id

            # Build metadata as JSON structure, currently only has text length and extraction date
            text_data = {
                'text_length': str(len(text)),
                'extraction_date': datetime.utcnow().isoformat()
            }

            # Save metadata in 'extras'
            extras_dict['extracted_text_data'] = json.dumps(text_data)

            # Reformat for CKAN
            dataset['extras'] = [{'key': k, 'value': v} for k, v in extras_dict.items()]

            # Save updates
            package_update({'ignore_auth': True}, dataset)

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
                "Authorization": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiIzRF9qWkY2anpNRVFlbjVqRWxNOTBOUDNLNGlxUEFvX20xVnhQLVYxem1FIiwiaWF0IjoxNzQ4ODg3MjIzfQ.f4kveIh6FtinK0xotxZ65O_9mPfcVLPWeCPrMHZvtfk"
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
