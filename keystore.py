"""
keystore.py
-----------
Remembers your odds-API key on THIS computer so you don't have to paste it in
every time you launch the app.

The key is saved as plain text in a file next to the project, readable only by
your user account. That's normal for this kind of key (it's a free, low-value
API key), but it does mean anyone with access to your Mac account could read
it. Use "Forget key" in the app to delete it.

Nothing here ever sends the key anywhere except the odds service itself.
"""

import os
import stat

HERE = os.path.dirname(os.path.abspath(__file__))
KEY_PATH = os.path.join(HERE, ".apikey")


def is_local():
    """
    True only when running on your own Mac.

    On a hosted server (Streamlit Cloud etc.) we must NEVER save or reload a
    key: the file would be shared by the whole server, so the next visitor
    would see your key pre-filled in the box. Hosted users paste their own key
    each session instead.
    """
    if os.environ.get("DK_FORCE_LOCAL") == "1":
        return True
    hosted_markers = ("/mount/src", "/home/appuser", "/app")
    here = os.path.abspath(HERE)
    if any(here.startswith(m) for m in hosted_markers):
        return False
    return not os.environ.get("STREAMLIT_SERVER_HEADLESS_CLOUD")


def save_key(key):
    """Write the key to disk, locked down to your user account only."""
    if not is_local():
        return False
    key = (key or "").strip()
    if not key:
        return False
    with open(KEY_PATH, "w") as f:
        f.write(key)
    # chmod 600 = only the file's owner can read or write it.
    os.chmod(KEY_PATH, stat.S_IRUSR | stat.S_IWUSR)
    return True


def load_key():
    """Return the saved key, or None if there isn't one."""
    if not is_local():
        return None
    if not os.path.exists(KEY_PATH):
        return None
    try:
        with open(KEY_PATH) as f:
            key = f.read().strip()
        return key or None
    except OSError:
        return None


def forget_key():
    """Delete the saved key. Returns True if a key was actually removed."""
    if os.path.exists(KEY_PATH):
        os.remove(KEY_PATH)
        return True
    return False
