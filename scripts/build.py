"""Build an installable archive from the integration, excluding private artifacts."""

import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

root = Path(__file__).resolve().parents[1]
component = root / "custom_components" / "airproce_proxy"
version = json.loads((component / "manifest.json").read_text())["version"]
target = root / "dist" / f"ha-airproce-proxy-{version}.zip"
target.parent.mkdir(exist_ok=True)
paths = [
    path
    for path in component.rglob("*")
    if path.is_file() and path.suffix in (".py", ".json") and "__pycache__" not in path.parts
]
paths += [root / "LICENSE", root / "THIRD_PARTY_NOTICES"]
with ZipFile(target, "w", compression=ZIP_DEFLATED) as archive:
    for path in sorted(paths):
        archive.write(path, path.relative_to(root).as_posix())
with ZipFile(target) as archive:
    if archive.testzip() is not None:
        raise RuntimeError("Archive verification failed")
print(target)
