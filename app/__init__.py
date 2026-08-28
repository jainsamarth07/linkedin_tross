"""
Load a local .env (if present) before any submodule reads os.environ.

Several modules capture env vars at import time (OUTBOUND_PROXY,
IMPERSONATE_TARGET, LI_COOKIE_STRING, ...), and this package __init__ runs
before all of them. No-op in production, where the platform injects real
environment variables and there is no .env file.
"""

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv not installed (e.g. minimal prod image)
    pass
