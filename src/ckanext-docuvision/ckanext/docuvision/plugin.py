from .processing import process_resource

import logging
import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit
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
        process_resource(resource)

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
        process_resource(resource)

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
            process_resource(resource)
            return {
                "success": True,
                "message": f"Text extraction completed for resource {resource_id}.",
            }
        except Exception as e:
            raise toolkit.ValidationError(f"Error processing document: {str(e)}")

    # By default, CKAN logs action usage for auditing. This exempts it from auditing.
    docuvision_process_document.auth_audit_exempt = True
