from .uploaders import upload_to_ckan

import logging
import json
import os
from datetime import datetime
import cv2
import ckan.plugins.toolkit as toolkit

# Create a logger for logging information and errors
log = logging.getLogger(__name__)


def store_text_in_json(resource_id, text, original_name):
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
        filename = os.path.splitext(original_name)[0] + ".txt"

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
            file_path = store_text_as_txt(text, filename)
            log.info(file_path)
            if file_path:
                uploaded_resource_id = upload_to_ckan(file_path, dataset_id)
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

        # Save the updated dataset
        package_update({"ignore_auth": True}, dataset)

    except Exception as e:
        log.error(f"Error storing text in JSON: {str(e)}")
        raise

def store_text_as_txt(text_content, filename):
    """
    Save extracted text as a .txt file in a temporary file path.
    """
    try:
        file_path = f"/tmp/{filename}"
        with open(file_path, "w", encoding="utf-8") as file:
            file.write(text_content)
        return file_path
    except Exception as e:
        log.error(f"Error saving text to file {filename}: {e}")
        return None
