import logging
import json
from datetime import datetime

import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit
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
        Save the extracted text in resource extras as a JSON object.
        """
        try:
            # Get CKAN actions for package_show and package_update
            package_show = toolkit.get_action('package_show')
            package_update = toolkit.get_action('package_update')

            # Fetch the current state of the dataset
            dataset = package_show({'ignore_auth': True}, {'id': 'skoda'})

            # Create 'extras' field in the JSON if it doesn't exist yet
            if "extras" not in dataset:
                dataset["extras"] = []

            # Convert the resource's 'extras' (a list of dicts) into a dictionary for easier manipulation
            extras_dict = {}
            for extra_item in dataset.get('extras', []):
                extras_dict[extra_item['key']] = extra_item['value']

            # Build JSON structure to store extracted text and metadata
            text_data = {
                'extracted_text': text,
                'extraction_date': datetime.utcnow().isoformat(),
                'version': '1.0'
            }

            # Put the new data under a custom key
            extras_dict['extracted_text_data'] = json.dumps(text_data)

            # Convert dictionary back into the list-of-dicts format CKAN expects
            new_extras_list = []
            for k, v in extras_dict.items():
                new_extras_list.append({'key': k, 'value': v})

            # Assign updated extras back to the resource
            dataset['extras'] = new_extras_list

            # Save the updated dataset
            package_update({'ignore_auth': True}, dataset)

        except Exception as e:
            # Log and re-raise exceptions for error reporting
            log.error(f"Error storing text in JSON: {str(e)}")
            raise