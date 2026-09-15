"""Local single-user session storage, never served by HTTP or checked into Git."""
import hashlib
import json
import os
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo


class SessionStore:
    def __init__(self, path, api_key):
        self.path = Path(path)
        self.key_id = hashlib.sha256(api_key.encode()).hexdigest()

    def save(self, token):
        now = datetime.now(ZoneInfo('Asia/Kolkata'))
        expiry = datetime.combine(now.date(), time(6), now.tzinfo)
        if expiry <= now:
            expiry += timedelta(days=1)
        data = dict(access_token=token, key_id=self.key_id, expires_at=expiry.isoformat())
        descriptor, temporary = tempfile.mkstemp(prefix=self.path.name + '.', dir=self.path.parent)
        try:
            with os.fdopen(descriptor, 'w') as file:
                os.chmod(temporary, 0o600)
                json.dump(data, file)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def load(self):
        try:
            if self.path.is_symlink() or self.path.stat().st_mode & 0o077:
                return None
            data = json.loads(self.path.read_text())
            if data['key_id'] != self.key_id:
                return None
            if datetime.fromisoformat(data['expires_at']) <= datetime.now(timezone.utc):
                self.clear()
                return None
            token = data['access_token']
            return token if isinstance(token, str) and token else None
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def clear(self):
        self.path.unlink(missing_ok=True)
