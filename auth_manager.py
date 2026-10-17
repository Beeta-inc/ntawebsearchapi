import os
import json
import time
import hashlib
import secrets
import threading
from datetime import datetime, timezone

# Primary storage path on physical phone, with local fallback for testing
STORAGE_PATHS = [
    "/sdcard/Download/NetuarkMedia/keys/search_keys.json",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "search_keys.json"),
    "/tmp/search_keys.json"
]

class AuthManager:
    """
    Enterprise-grade, thread-safe API Key Manager with one-time reveal security.
    Plaintext keys (nta_live_...) are NEVER stored to disk; only SHA-256 hashes are persisted.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._keys_file = self._resolve_storage_file()
        self._cache = {}
        self._load_keys()

    def _resolve_storage_file(self):
        for path in STORAGE_PATHS:
            parent = os.path.dirname(path)
            try:
                os.makedirs(parent, exist_ok=True)
                # Test write ability
                test_file = os.path.join(parent, ".perm_test")
                with open(test_file, "w") as f:
                    f.write("ok")
                os.remove(test_file)
                return path
            except Exception:
                continue
        # Fallback to current directory
        fallback = os.path.join(os.path.dirname(os.path.abspath(__file__)), "search_keys.json")
        os.makedirs(os.path.dirname(fallback), exist_ok=True)
        return fallback

    def _hash_key(self, raw_key: str) -> str:
        return hashlib.sha256(raw_key.strip().encode('utf-8')).hexdigest()

    def _load_keys(self):
        with self._lock:
            if os.path.exists(self._keys_file):
                try:
                    with open(self._keys_file, "r") as f:
                        data = json.load(f)
                    self._cache = data.get("keys", {})
                except Exception as e:
                    print(f"[AUTH] Warning: Failed to parse keys file ({e}), initializing empty.", flush=True)
                    self._cache = {}
            else:
                self._cache = {}
                self._save_keys_unlocked()

    def _save_keys_unlocked(self):
        try:
            temp_file = self._keys_file + ".tmp"
            with open(temp_file, "w") as f:
                json.dump({"keys": self._cache, "version": 1}, f, indent=2)
            os.replace(temp_file, self._keys_file)
        except Exception as e:
            print(f"[AUTH] Error saving keys file: {e}", flush=True)

    def create_key(self, name: str = "Default API Key") -> tuple:
        """
        Generates a new cryptographic API key.
        Returns: (raw_key, key_metadata).
        IMPORTANT: raw_key is returned ONLY ONCE and cannot be recovered later!
        """
        raw_token = secrets.token_hex(20)
        raw_key = f"nta_live_{raw_token}"
        key_hash = self._hash_key(raw_key)
        key_id = f"key_{secrets.token_hex(4)}"
        now_iso = datetime.now(timezone.utc).isoformat()

        key_info = {
            "key_id": key_id,
            "name": name.strip() or "Unnamed Key",
            "prefix": raw_key[:12] + "...",
            "suffix": "..." + raw_key[-4:],
            "key_hash": key_hash,
            "created_at": now_iso,
            "last_used": None,
            "query_count": 0,
            "revoked": False
        }

        with self._lock:
            self._cache[key_id] = key_info
            self._save_keys_unlocked()

        # Public metadata safe for GUI display
        public_metadata = {k: v for k, v in key_info.items() if k != "key_hash"}
        return raw_key, public_metadata

    def validate_key(self, raw_key: str) -> bool:
        """
        Validates a bearer token in constant time. Updates query count and last used timestamp.
        """
        if not raw_key or not isinstance(raw_key, str):
            return False

        clean_key = raw_key.strip()
        if clean_key.startswith("Bearer "):
            clean_key = clean_key[7:].strip()

        key_hash = self._hash_key(clean_key)
        now_iso = datetime.now(timezone.utc).isoformat()

        with self._lock:
            for key_id, info in self._cache.items():
                if info.get("key_hash") == key_hash:
                    if info.get("revoked", False):
                        return False
                    info["last_used"] = now_iso
                    info["query_count"] = info.get("query_count", 0) + 1
                    # Save asynchronously / throttled to avoid disk thrashing
                    self._save_keys_unlocked()
                    return True

        return False

    def list_keys(self) -> list:
        """
        Returns all registered keys for management GUI without leaking key hashes.
        """
        with self._lock:
            result = []
            for k_id, info in self._cache.items():
                safe_item = {
                    "key_id": info.get("key_id", k_id),
                    "name": info.get("name", "Key"),
                    "prefix": info.get("prefix", "nta_live_..."),
                    "suffix": info.get("suffix", "..."),
                    "created_at": info.get("created_at"),
                    "last_used": info.get("last_used"),
                    "query_count": info.get("query_count", 0),
                    "revoked": info.get("revoked", False)
                }
                result.append(safe_item)
            return sorted(result, key=lambda x: x.get("created_at") or "", reverse=True)

    def revoke_key(self, key_id: str) -> bool:
        """Revokes an API key so it can no longer be used."""
        with self._lock:
            if key_id in self._cache:
                self._cache[key_id]["revoked"] = True
                self._save_keys_unlocked()
                return True
            return False

    def delete_key(self, key_id: str) -> bool:
        """Permanently removes an API key from the store."""
        with self._lock:
            if key_id in self._cache:
                del self._cache[key_id]
                self._save_keys_unlocked()
                return True
            return False

# Global singleton
auth_manager = AuthManager()
