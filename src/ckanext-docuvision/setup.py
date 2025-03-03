import os
from setuptools import setup, find_namespace_packages

# Read the long description from README.md
with open(os.path.join(os.path.dirname(__file__), 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

setup(
    # Basic package information
    name='ckanext-docuvision',
    version='0.2.0',  # Incremented version for the upgraded setup
    description='CKAN extension for PDF processing and text extraction',
    long_description=long_description,
    long_description_content_type='text/markdown',

    # Author details
    author='MaximUniBremen',
    author_email='Your Email',
    url='https://github.com/MaximUniBremen/ckanext-docuvision',
    license='AGPL',

    # Package configuration
    packages=find_namespace_packages(include=['ckanext.*']),
    include_package_data=True,
    zip_safe=False,

    # Python versions supported
    python_requires='>=3.8',

    # Dependencies (adjust versions as necessary)
    install_requires=[
        'ckan>=2.11',         # Tested, or higher if you plan to support CKAN 2.12+
        'PyPDF2>=3.0.0',      # For PDF text extraction
        'pillow>=9.0.0',      # For advanced OCR image processing if needed
        'pytesseract>=0.3.8', # For OCR functionality
        'flask_sqlalchemy>=3.1.1', 'sqlalchemy>=2.0.38', 'psycopg2-binary>=2.9.10' # For Postgres database functionality
    ],

    # CKAN plugin entry point
    entry_points='''
        [ckan.plugins]
        docuvision=ckanext.docuvision.plugin:DocuvisionPlugin
    ''',

    # Package metadata
    classifiers=[
        'Development Status :: 4 - Beta',
        'Framework :: CKAN',
        'Intended Audience :: Developers',
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: GNU Affero General Public License v3 or later (AGPLv3+)',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Topic :: Internet :: WWW/HTTP :: Dynamic Content',
        'Topic :: Text Processing :: General',
    ],

    # Keywords for PyPI
    keywords='CKAN PDF OCR text-extraction document-processing',

    # Project URLs
    project_urls={
        'Source': 'https://github.com/MaximUniBremen/ckanext-docuvision',
        'Issues': 'https://github.com/MaximUniBremen/ckanext-docuvision/issues',
        'Documentation': 'https://github.com/MaximUniBremen/ckanext-docuvision#readme',
    },
)
