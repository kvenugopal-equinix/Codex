"""Build a clean source distribution without install-specific data."""
import argparse
from pathlib import Path
import stat
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FILES = ['README.md', 'MAC_SETUP.md', 'BUILD_NOTES.md', 'VERSION', '.env.example',
         '.gitignore', 'requirements.txt', 'requirements-dev.txt', 'install.sh', 'watch.sh']
DIRS = ['warroom', 'tests', 'app', 'tools']


def package(destination):
    paths = [ROOT / name for name in FILES if (ROOT / name).is_file()]
    for folder in DIRS:
        paths.extend(p for p in (ROOT / folder).rglob('*') if p.is_file()
                     and '__pycache__' not in p.parts
                     and p.suffix in ('.py', '.sh', '.swift', '.applescript', '.txt'))
    destination = Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in sorted(paths):
            name = 'WarRoomBot/' + p.relative_to(ROOT).as_posix()
            info = zipfile.ZipInfo(name, (2026, 10, 12, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | (0o755 if p.suffix == '.sh' else 0o644)) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, p.read_bytes())
    print(destination)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('destination', type=Path)
    package(parser.parse_args().destination)
