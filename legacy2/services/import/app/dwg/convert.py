"""DWG -> DXF conversion.

DWG is a closed format, so we shell out to an external converter:
  1. ODA File Converter (most accurate; free download from opendesign.com)
  2. LibreDWG `dwg2dxf` (open source; `conda install -c conda-forge libredwg`)
Converter binaries are looked up in $DWG3D_ODA / $DWG3D_DWG2DXF, then PATH,
then the project-local `.tools/` directory.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# LibreDWG parses untrusted files and has a history of memory bugs: cap its
# address space. ODA (Qt, AppImage) reserves large virtual areas, so it only
# gets the CPU-time cap.
CONVERTER_MEM_MB = int(os.environ.get("DWG3D_CONVERTER_MEM_MB", "4096"))


def limits(timeout: int, memory: bool):
    """preexec_fn for subprocess.run: CPU-time (and optionally memory) limits."""
    def apply():
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_CPU, (timeout, timeout + 5))
            if memory and CONVERTER_MEM_MB > 0:
                lim = CONVERTER_MEM_MB * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_AS, (lim, lim))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        except Exception:      # non-POSIX: rely on the wall-clock timeout
            pass
    return apply if os.name == "posix" else None


class ConversionError(RuntimeError):
    pass


def _find(env: str, names: list[str], extra_dirs: list[Path]) -> str | None:
    if os.environ.get(env):
        return os.environ[env]
    for n in names:
        if p := shutil.which(n):
            return p
    for d in extra_dirs:
        for n in names:
            if (d / n).is_file():
                return str(d / n)
    return None


def find_oda() -> str | None:
    return _find("DWG3D_ODA", ["ODAFileConverter", "ODAFileConverter.AppImage"],
                 [PROJECT_ROOT / ".tools", Path("/usr/bin")])


def find_libredwg() -> str | None:
    return _find("DWG3D_DWG2DXF", ["dwg2dxf"], [PROJECT_ROOT / ".tools/libredwg/bin"])


def available_converters() -> dict[str, str | None]:
    return {"oda": find_oda(), "libredwg": find_libredwg()}


def dwg_to_dxf(src: Path, dst: Path, timeout: int = 600) -> str:
    """Convert `src` DWG into `dst` DXF. Returns the converter name used."""
    src, dst = Path(src), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    errors = []

    if oda := find_oda():
        with tempfile.TemporaryDirectory() as tin, tempfile.TemporaryDirectory() as tout:
            shutil.copy(src, Path(tin) / "in.dwg")
            cmd = [oda, tin, tout, "ACAD2018", "DXF", "0", "1", "*.DWG"]
            env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env,
                               preexec_fn=limits(timeout, memory=False))
            out = Path(tout) / "in.dxf"
            if out.exists() and out.stat().st_size > 0:
                shutil.move(out, dst)
                return "oda"
            errors.append(f"ODA: {r.stderr.strip() or r.stdout.strip() or 'no output'}")

    if lr := find_libredwg():
        cmd = [lr, "-y", "-o", str(dst), str(src)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           preexec_fn=limits(timeout, memory=True))
        if dst.exists() and dst.stat().st_size > 0:
            return "libredwg"
        errors.append(f"libredwg: {r.stderr.strip()[-500:]}")

    if not errors:
        raise ConversionError(
            "No DWG converter found. Install ODA File Converter or LibreDWG "
            "(conda install -c conda-forge libredwg), or upload a DXF instead.")
    raise ConversionError("DWG conversion failed: " + " | ".join(errors))


def ensure_dxf(path: Path, work_dir: Path) -> tuple[Path, str]:
    """Return a DXF path for `path` (converting DWG if needed) and the method."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".dxf":
        return path, "none"
    if suffix == ".dwg":
        dst = Path(work_dir) / (path.stem + ".dxf")
        return dst, dwg_to_dxf(path, dst)
    raise ConversionError(f"Unsupported file type: {suffix}")
