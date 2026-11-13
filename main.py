"""Convenience entry point for local development."""

import subprocess


def main() -> None:
    """Start Django's development server through the project environment."""
    subprocess.run(["uv", "run", "manage.py", "runserver"], check=True)


if __name__ == "__main__":
    main()
