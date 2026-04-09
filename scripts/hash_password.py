"""Generate a password hash for config.json auth.password_hash."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.auth.service import hash_password

if __name__ == "__main__":
    import getpass
    password = getpass.getpass("Enter password: ")
    confirm = getpass.getpass("Confirm password: ")

    if password != confirm:
        print("Passwords do not match.")
        sys.exit(1)

    hashed = hash_password(password)
    print(f"\nAdd this to config.json under auth.password_hash:\n")
    print(f'  "password_hash": "{hashed}"')
