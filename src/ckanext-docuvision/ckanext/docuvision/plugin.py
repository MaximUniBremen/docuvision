# ckanext/docuvision/plugin.py

import logging
import json
from datetime import datetime

import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit
from ckan.lib.uploader import ResourceUpload
import PyPDF2

log = logging.getLogger(__name__)


class DocuvisionPlugin(plugins.SingletonPlugin):
    """
    DocuvisionPlugin for processing PDF resources in CKAN

    This plugin implements:
    - IConfigurer: For adding templates and static files
    - IResourceController: For handling resource creation and processing
    - IActions: For exposing a custom Action API endpoint (docuvision_process_pdf)
    """
    plugins.implements(plugins.IConfigurer)
    plugins.implements(plugins.IResourceController)
    plugins.implements(plugins.IActions)

    # --------------------------------------------------------------------------
    # IConfigurer
    # --------------------------------------------------------------------------
    def update_config(self, config_):
        """
        Update CKAN's configuration by adding templates, public resources, and fanstatic.
        """
        toolkit.add_template_directory(config_, 'templates')
        toolkit.add_public_directory(config_, 'public')
        toolkit.add_resource('fanstatic', 'docuvision')

    # --------------------------------------------------------------------------
    # IResourceController - required methods
    # --------------------------------------------------------------------------
    def before_resource_create(self, context, resource):
        pass

    def after_resource_create(self, context, resource):
        """
        Called after a resource is created
        If resource is a PDF, trigger _process_pdf.
        """
        if resource.get('format', '').lower() == 'pdf':
            self._process_pdf(resource)

    def before_resource_update(self, context, current, resource):
        pass

    def after_resource_update(self, context, resource):
        """
        Called after a resource is updated
        If resource is a PDF, trigger _process_pdf.
        """
        if resource.get('format', '').lower() == 'pdf':
            self._process_pdf(resource)

    def before_resource_delete(self, context, resource, resources):
        pass

    def after_resource_delete(self, context, resources):
        pass

    def before_resource_show(self, resource_dict):
        return resource_dict

    # --------------------------------------------------------------------------
    # IActions - Custom CKAN Action API endpoints
    # --------------------------------------------------------------------------
    def get_actions(self):
        """
        Register custom actions so they appear under /api/3/action/[action_name].
        """
        return {
            'docuvision_process_pdf': self.docuvision_process_pdf
        }

    def docuvision_process_pdf(self, context, data_dict):
        """
        Action: docuvision_process_pdf
        Usage (POST to /api/3/action/docuvision_process_pdf):
        {
          "resource_id": "UUID of your PDF resource"
        }

        This action triggers PDF text extraction and updates the resource extras
        with the extracted text. Returns a success message if extraction completes.
        """
        # Check resource_id in the request
        resource_id = data_dict.get('resource_id')
        if not resource_id:
            raise toolkit.ValidationError("Missing 'resource_id' in request data.")

        # Fetch resource
        try:
            resource = toolkit.get_action('resource_show')(
                {'ignore_auth': True},
                {'id': resource_id}
            )
        except toolkit.ObjectNotFound:
            raise toolkit.ObjectNotFound(f"Resource with id '{resource_id}' not found.")
        except Exception as e:
            raise toolkit.ValidationError(f"Error fetching resource: {str(e)}")

        # Check if it is a PDF resource
        if resource.get('format', '').lower() != 'pdf':
            raise toolkit.ValidationError("Resource format is not PDF or is missing.")

        # Process PDF
        try:
            self._process_pdf(resource)
            return {
                'success': True,
                'message': f"PDF text extraction completed for resource {resource_id}."
            }
        except Exception as e:
            raise toolkit.ValidationError(f"Error processing PDF: {str(e)}")

    docuvision_process_pdf.auth_audit_exempt = True

    # --------------------------------------------------------------------------
    # Helper methods for PDF processing
    # --------------------------------------------------------------------------
    def _process_pdf(self, resource):
        """
        Process PDF and store extracted text in resource extras.
        """
        try:
            # Get file path from CKAN's resource storage
            upload = ResourceUpload(resource)
            filepath = upload.get_path(resource['id'])

            # Extract text from the PDF
            extracted_text_var = self._extract_text(filepath)

            # Store text in JSON (resource extras)
            self._store_text_in_json(resource['id'], extracted_text_var)

            log.info(f"Successfully processed PDF for resource {resource['id']}")
        except Exception as e:
            log.error(f"Error processing PDF for resource {resource['id']}: {str(e)}")
            raise

    def _extract_text(self, filepath):
        """
        Extract text from a PDF file at the specified filepath.
        Return the extracted text as a string.
        """
        text = ""
        try:
            with open(filepath, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                for page in pdf_reader.pages:
                    text += (page.extract_text() or "") + "\n"
            return text
        except Exception as e:
            log.error(f"Error extracting text from PDF: {str(e)}")
            raise

    def _store_text_in_json(self, resource_id, text):
        """
        Store extracted text in JSON format within the resource extras.
        """
        try:
            resource_show = toolkit.get_action('resource_show')
            resource_update = toolkit.get_action('resource_update')

            # Get existing resource
            resource = resource_show({'ignore_auth': True}, {'id': resource_id})

            # Create JSON structure
            text_data = {
                'extracted_text': text,
                'extraction_date': datetime.utcnow().isoformat(),
                'version': '1.0'
            }

            # Update resource extras
            if 'extras' not in resource:
                resource['extras'] = {}

            # Save the text data under a custom key
            resource['extras']['extracted_text_data'] = json.dumps(text_data)

            # Update the resource in CKAN
            resource_update({'ignore_auth': True}, resource)

        except Exception as e:
            log.error(f"Error storing text in JSON: {str(e)}")
            raise