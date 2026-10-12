#!/usr/bin/env python3
"""Compare the installed native app with a retained local build without changing either."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import tempfile


FILES = {
    "main": "Contents/MacOS/WarRoomBot",
    "helper": "Contents/MacOS/axctl",
    "Info.plist": "Contents/Info.plist",
    "VERSION": "Contents/Resources/payload/VERSION",
}


def run(command, timeout=5):
    """Bound execution and cleanup; signal only the child this call started."""
    def tail(stream):
        length = stream.seek(0, 2)
        stream.seek(max(0, length - 65536))
        prefix = "[Earlier diagnostic output omitted]\n" if length > 65536 else ""
        return prefix + stream.read(65536).decode("utf-8", errors="replace")

    # Private temporary files avoid pipe deadlocks and unbounded captured memory.
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        try:
            child = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                     stdout=stdout, stderr=stderr)
        except OSError as error:
            return {"code": None, "timeout": False, "stdout": "", "stderr": str(error)}
        timed_out = False
        unreaped = None
        try:
            child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                child.terminate()
            except OSError:
                pass
            try:
                child.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                try:
                    child.kill()
                except OSError:
                    pass
                try:
                    child.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    unreaped = child.pid
        finally:
            if sys.exc_info()[0] is KeyboardInterrupt:
                # Cancel only this probe, even during timeout cleanup.
                try:
                    child.kill()
                except OSError:
                    pass
                try:
                    child.wait(timeout=1)
                except (OSError, subprocess.TimeoutExpired):
                    pass
        result = {"code": child.poll(), "timeout": timed_out,
                  "stdout": tail(stdout), "stderr": tail(stderr)}
        if unreaped is not None:
            result["unreaped_diagnostic_pid"] = unreaped
        return result


def successful_build_log(dmg):
    log = dmg.parent.parent / "build.log"
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, None
    complete = any(line.startswith("Built ") and dmg.name in line
                   for line in text.splitlines())
    smoke = None
    for line in text.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict) and "ok" in value and "bundle_id" in value and "payload" in value:
            smoke = {key: value[key] for key in ("ok", "version", "bundle_id", "name", "home",
                                               "payload", "helper", "errors") if key in value}
    return complete, smoke


def latest_local_dmg():
    candidates = []
    for folder in Path(tempfile.gettempdir()).glob("WarRoomBot-local-build-*"):
        for dmg in (folder / "dist").glob("War-Room-Bot-*.dmg"):
            try:
                complete, _ = successful_build_log(dmg)
                if dmg.is_file() and dmg.stat().st_size and complete:
                    candidates.append(dmg)
            except OSError:
                continue
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


def mounted_app(dmg, information):
    """Accept only a mount belonging to the exact chosen image path."""
    try:
        images = plistlib.loads(information.encode("utf-8")).get("images", [])
    except (ValueError, plistlib.InvalidFileException):
        return None
    for image in images:
        image_path = image.get("image-path")
        if not isinstance(image_path, str) or Path(image_path).resolve() != dmg.resolve():
            continue
        for entity in image.get("system-entities", []):
            mount = entity.get("mount-point")
            if isinstance(mount, str):
                app = Path(mount) / "War Room Bot.app"
                if app.is_dir():
                    return app
    return None


def fingerprint(app):
    result = {}
    for label, relative in FILES.items():
        path = app / relative
        digest = run(["/usr/bin/shasum", "-a", "256", str(path)])
        fields = digest["stdout"].split()
        entry = {"sha256": fields[0] if digest["code"] == 0 and fields
                 and re.fullmatch(r"[0-9a-f]{64}", fields[0]) else None}
        if entry["sha256"] is None:
            entry["error"] = "hash timed out" if digest["timeout"] else "file missing, unreadable or hash failed"
        if label in ("main", "helper"):
            architecture = run(["/usr/bin/file", "-b", str(path)])
            entry["architecture"] = architecture["stdout"].strip() if architecture["code"] == 0 else "unavailable"
        result[label] = entry
    return result


def inspect(app, label):
    print("\n{} app: {}".format(label, app), flush=True)
    hashes = fingerprint(app)
    for name, values in hashes.items():
        print("  {}: {}".format(name, json.dumps(values, sort_keys=True)), flush=True)
    verified = run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)])
    status = "timed out" if verified["timeout"] else "valid" if verified["code"] == 0 else "failed"
    print("  Codesign verification: " + status, flush=True)
    if status == "failed":
        print("  " + verified["stderr"].strip()[:600], flush=True)
    executable = app / FILES["main"]
    if not executable.is_file():
        smoke = {"code": None, "timeout": False, "stdout": "", "stderr": "Native executable is missing."}
    else:
        print("  Probing --smoke-test only (8-second deadline)…", flush=True)
        smoke = run([str(executable), "--smoke-test"], timeout=8)
    report_ok = False
    for line in smoke["stdout"].splitlines():
        try:
            report = json.loads(line)
        except ValueError:
            continue
        if isinstance(report, dict) and report.get("ok") is True:
            report_ok = True
    smoke["passed"] = smoke["code"] == 0 and not smoke["timeout"] and report_ok
    smoke["codesign_valid"] = verified["code"] == 0 and not verified["timeout"]
    print("  Smoke result: " + json.dumps(smoke, sort_keys=True), flush=True)
    return hashes, smoke


def summarize(installed, reference, build_smoke=None):
    if reference is None:
        print("\nNo exact rebuilt reference was available. The installed smoke result alone does not identify the cause.")
        return 1
    hashes, smoke = installed
    reference_hashes, reference_smoke = reference
    unknown = [name for name in FILES if hashes[name]["sha256"] is None
               or reference_hashes[name]["sha256"] is None]
    differences = [name for name in FILES if name not in unknown
                   and hashes[name]["sha256"] != reference_hashes[name]["sha256"]]
    if differences:
        print("\nInstalled and rebuilt files differ: " + ", ".join(differences) + ".")
        print("The installed bundle is not identical to this exact local build; check which DMG was used for replacement.")
        return 1
    elif unknown:
        print("\nCould not compare these files: " + ", ".join(unknown) + ". No copy mismatch is established.")
        return 1
    else:
        print("\nAll four compared files match the exact local build.")
        if smoke["timeout"] and reference_smoke["passed"]:
            print("The same compared files pass smoke from the rebuilt image but stall at the installed location. This narrows the launch context; it does not establish a security-policy cause.")
        elif smoke["timeout"] and reference_smoke["timeout"]:
            previous = " The retained build log reports an earlier successful smoke check." if build_smoke and build_smoke.get("ok") is True else ""
            print("Both current smoke probes stall." + previous + " No GUI, Python backend or Zoom action was involved in these probes.")
        elif smoke["passed"]:
            print("Installed smoke now completes. This checks early bundle initialization, not window startup or Accessibility.")
        else:
            print("Inspect the bounded smoke results above; matching files alone do not establish why launch fails.")
    return 0 if all(result["passed"] and result["codesign_valid"]
                    for result in (smoke, reference_smoke)) else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, default=Path("/Applications/War Room Bot.app"))
    parser.add_argument("--dmg", type=Path, help="exact locally rebuilt DMG; otherwise choose latest successful retained build")
    args = parser.parse_args(argv)
    if sys.platform != "darwin":
        parser.error("Run this diagnostic on the Mac where the app stalls.")
    app = args.app.expanduser().resolve()
    dmg = args.dmg.expanduser().resolve() if args.dmg else latest_local_dmg()
    print("This diagnostic changes no app, private data, signatures or permissions.", flush=True)
    machine = run(["/usr/bin/uname", "-m"])
    print("Current process architecture: " + machine["stdout"].strip(), flush=True)
    installed = inspect(app, "Installed")
    reference = None
    build_smoke = None
    scratch = None
    owned_mount = None
    try:
        if dmg is None or not dmg.is_file():
            print("\nNo retained successful local DMG found. Supply --dmg with its exact path to compare.", flush=True)
        else:
            print("\nChosen exact rebuilt DMG: " + str(dmg), flush=True)
            complete, build_smoke = successful_build_log(dmg)
            print("Build log completion marker: {}".format(complete), flush=True)
            print("Build log smoke metadata: " + json.dumps(build_smoke, sort_keys=True), flush=True)
            info = run(["/usr/bin/hdiutil", "info", "-plist"])
            rebuilt = mounted_app(dmg, info["stdout"]) if info["code"] == 0 else None
            if rebuilt is None:
                scratch = Path(tempfile.mkdtemp(prefix="WarRoomBot-launch-check-"))
                owned_mount = scratch / "mount"
                owned_mount.mkdir()
                print("Attaching the chosen image read-only at a private mount…", flush=True)
                attached = run(["/usr/bin/hdiutil", "attach", "-readonly", "-nobrowse", "-noautoopen",
                                "-mountpoint", str(owned_mount), "-plist", str(dmg)], timeout=15)
                if attached["code"] == 0 and not attached["timeout"]:
                    candidate = owned_mount / "War Room Bot.app"
                    rebuilt = candidate if candidate.is_dir() else None
                else:
                    print("Read-only attach failed or timed out: " + attached["stderr"].strip()[:600], flush=True)
            else:
                print("Using its existing exact-image mount; this diagnostic will not detach that mount.", flush=True)
            if rebuilt is not None:
                reference = inspect(rebuilt, "Rebuilt reference")
    finally:
        if owned_mount is not None:
            detached = run(["/usr/bin/hdiutil", "detach", str(owned_mount)])
            if detached["code"] != 0 or detached["timeout"]:
                print("The diagnostic-owned read-only mount could not be detached: " + str(owned_mount), flush=True)
            # Never recursively delete a directory that might still be mounted.
            try:
                owned_mount.rmdir()
                scratch.rmdir()
            except OSError:
                pass
    return summarize(installed, reference, build_smoke)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nDiagnostic cancelled; cleanup was limited to its own probes and private mount.", file=sys.stderr)
        sys.exit(130)
