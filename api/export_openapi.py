"""Write the current API contract for frontend type generation.

Run `python -m api.export_openapi` after changing response models or routes.
"""

import json
from pathlib import Path

from api.main import app


def main() -> None:
    destination = Path(__file__).with_name("openapi.json")
    destination.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")
    print(destination)


if __name__ == "__main__":
    main()
