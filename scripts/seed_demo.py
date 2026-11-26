"""Seed the demo household without starting the server."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.db import SessionLocal, init_db
from server.services.demo import seed


def main() -> None:
    init_db()
    session = SessionLocal()
    try:
        info = seed(session)
        print("Demo ready.")
        print(f"  email:    {info['credentials']['email']}")
        print(f"  password: {info['credentials']['password']}")
        print(f"  household {info['family_id']} · main case {info['case_id']}")
        print("  open /app and press 'Run analysis' on the main case")
    finally:
        session.close()


if __name__ == "__main__":
    main()
