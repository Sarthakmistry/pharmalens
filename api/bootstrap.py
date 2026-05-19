"""
api/bootstrap.py
Runs at import time (before any google-genai client is created).

On Render (or any cloud host), set the env var GOOGLE_CREDENTIALS_JSON
to the full contents of the service-account JSON file.  This module
writes it to a temp file and points GOOGLE_APPLICATION_CREDENTIALS at it,
so the rest of the code works identically to local dev.

Locally, GOOGLE_CREDENTIALS_JSON is not set and the .env file's
GOOGLE_APPLICATION_CREDENTIALS path is used as-is.
"""

import os
import tempfile

_creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
if _creds_json and not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
    _tf = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    _tf.write(_creds_json)
    _tf.close()
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = _tf.name
