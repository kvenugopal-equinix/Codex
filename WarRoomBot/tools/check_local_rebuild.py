"""Rebuild an old installed payload with an SDK that refuses Intel targets."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    app, old_builder = (Path(value).resolve() for value in sys.argv[1:3])
    helper = Path(__file__).with_name("rebuild_installed_app.sh")
    with tempfile.TemporaryDirectory(prefix="war-room-bot-arm-only-check-") as scratch:
        work = Path(scratch)
        old_app = work / "legacy" / "War Room Bot.app"
        subprocess.run(["ditto", "--noextattr", "--noqtn", str(app), str(old_app)],
                       check=True, timeout=60)
        (old_app / "Contents/Resources/payload/tools/build_app.sh").write_bytes(old_builder.read_bytes())
        shim = work / "commands"
        shim.mkdir()
        targets = work / "targets.jsonl"
        compiler = shim / "xcrun"
        compiler.write_text('''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
if "-target" in args:
    target = args[args.index("-target") + 1]
    with open(os.environ["WARROOM_TEST_TARGET_LOG"], "a") as stream:
        stream.write(json.dumps(target) + "\\n")
    if target.startswith("x86_64-"):
        print("TEST SDK: Intel Swift compatibility libraries are unavailable.", file=sys.stderr)
        sys.exit(99)
if "lipo" in args:
    print("TEST SDK: this local rebuild must produce a single native architecture.", file=sys.stderr)
    sys.exit(99)
os.execv("/usr/bin/xcrun", ["/usr/bin/xcrun"] + args)
''')
        compiler.chmod(0o755)
        environment = os.environ.copy()
        environment["PATH"] = str(shim) + os.pathsep + environment.get("PATH", "")
        environment["WARROOM_TEST_TARGET_LOG"] = str(targets)
        subprocess.run(["/bin/bash", str(helper), "--no-open", "--app", str(old_app)],
                       env=environment, check=True, timeout=330)
        built = [json.loads(line) for line in targets.read_text().splitlines()]
        if built != ["arm64-apple-macos12.0", "arm64-apple-macos12.0"]:
            raise RuntimeError("The old-payload rebuild requested unexpected targets: " + repr(built))
        print("Old-payload rebuild passed with Intel targets and universal merging disabled.")


if __name__ == "__main__":
    main()
