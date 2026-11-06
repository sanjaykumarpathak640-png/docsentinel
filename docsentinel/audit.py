"""Stage 5.9 - Tamper-evident audit trail.

Every event is appended to a JSON-lines file. Each entry stores the SHA-256 of
the previous entry, so editing or deleting any past entry breaks the chain and
is detected by verify(). (Inspired by ISO/IEC 27037 chain-of-custody practice.)
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


class AuditLog:
    GENESIS = "0" * 64

    def __init__(self, path: Path, actor: str = "docsentinel"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.actor = actor
        self.last_hash = self.GENESIS
        if self.path.exists():
            entries = self.entries()
            if entries:
                self.last_hash = entries[-1]["hash"]

    def log(self, event: str, actor: str | None = None, **details) -> dict:
        entry = {
            "seq": len(self.entries()) + 1,
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "actor": actor or self.actor,
            "event": event,
            "details": details,
            "prev_hash": self.last_hash,
        }
        entry["hash"] = self._hash(entry)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
        self.last_hash = entry["hash"]
        return entry

    @staticmethod
    def _hash(entry: dict) -> str:
        body = {k: v for k, v in entry.items() if k != "hash"}
        return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()

    def entries(self) -> list:
        if not self.path.exists():
            return []
        return [json.loads(l) for l in self.path.read_text(encoding="utf-8").splitlines() if l.strip()]

    def verify(self) -> tuple[bool, str]:
        prev = self.GENESIS
        for e in self.entries():
            if e["prev_hash"] != prev:
                return False, f"chain broken before entry {e['seq']}"
            if self._hash(e) != e["hash"]:
                return False, f"entry {e['seq']} was modified"
            prev = e["hash"]
        return True, f"{len(self.entries())} entries verified"
