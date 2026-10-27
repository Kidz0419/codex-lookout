"""Copy notices for the interpreter and PyInstaller bootloader into the app."""
import importlib.metadata
import shutil
import sys
import sysconfig
from pathlib import Path

destination = Path(sys.argv[1])
destination.mkdir(parents=True, exist_ok=True)
python_license = next((candidate for candidate in (
    Path(sysconfig.get_path("stdlib")) / "LICENSE.txt",
    Path(sys.base_prefix) / "LICENSE.txt",
    Path(sys.base_prefix) / "Resources/License.txt",
) if candidate.is_file()), None)
if python_license is None:
    raise SystemExit("Python LICENSE.txt is missing; use a complete Python distribution.")
shutil.copyfile(python_license, destination / "Python.txt")
distribution = importlib.metadata.distribution("pyinstaller")
license_path = next((distribution.locate_file(p) for p in distribution.files if p.name == "COPYING.txt"), None)
if license_path is None:
    raise SystemExit("PyInstaller COPYING.txt is missing.")
shutil.copyfile(license_path, destination / "PyInstaller.txt")
