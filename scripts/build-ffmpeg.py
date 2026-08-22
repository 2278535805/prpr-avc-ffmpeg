#!/usr/bin/env python3
import argparse
import os
import re
import shutil
import subprocess
import tarfile
from pathlib import Path

import tomllib


def load_toml(path: Path) -> dict:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError:
        raise SystemExit(f"config not found: {path}")
    except tomllib.TOMLDecodeError as exc:
        raise SystemExit(f"invalid toml in {path}: {exc}")


def run(cmd: list[str], cwd: Path | None = None, env: dict | None = None) -> None:
    print(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


VAR_PATTERN = re.compile(r"\$\{([^}]+)\}|\$([A-Za-z_][A-Za-z0-9_]*)")


def expand_vars(value: str, env: dict[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1) or match.group(2)
        return env.get(key, match.group(0))

    return VAR_PATTERN.sub(repl, value)


def expand_list(items: list[str], env: dict[str, str]) -> list[str]:
    return [expand_vars(item, env) for item in items]


def resolve_source_dir(root: Path, ffmpeg_cfg: dict) -> Path:
    source_dir = root / str(ffmpeg_cfg.get("source_dir", "FFmpeg"))
    if not source_dir.exists():
        raise SystemExit(
            f"FFmpeg source not found: {source_dir}. "
            "Initialize the FFmpeg submodule before building locally."
        )
    if not (source_dir / "configure").exists():
        raise SystemExit(
            f"FFmpeg source is not initialized in {source_dir}. "
            "Run `git submodule update --init FFmpeg` before building locally."
        )
    return source_dir


def resolve_x264_dir(root: Path, ffmpeg_cfg: dict) -> Path:
    source_dir = root / str(ffmpeg_cfg.get("x264_source_dir", "x264"))
    if not (source_dir / "configure").exists():
        raise SystemExit(
            f"x264 source is not initialized in {source_dir}. "
            "Run `git submodule update --init x264` before building."
        )
    return source_dir


def prepare_source_dir(source_dir: Path, dest_dir: Path) -> Path:
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    shutil.copytree(source_dir, dest_dir, ignore=shutil.ignore_patterns(".git"))
    return dest_dir


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build FFmpeg static libs for a target"
    )
    parser.add_argument("target", help="target name defined in config/targets.toml")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    ffmpeg_cfg = load_toml(root / "config" / "ffmpeg.toml")
    targets_cfg = load_toml(root / "config" / "targets.toml")

    target_name = args.target
    target_cfg = None
    for item in targets_cfg.get("targets", []):
        if item.get("name") == target_name:
            target_cfg = item
            break
    if not target_cfg:
        available = [t.get("name") for t in targets_cfg.get("targets", [])]
        raise SystemExit(f"target not found: {target_name}. available: {available}")

    source_root = resolve_source_dir(root, ffmpeg_cfg)
    x264_root = resolve_x264_dir(root, ffmpeg_cfg)
    print(f"Using FFmpeg source from {source_root}")
    print(f"Using x264 source from {x264_root}")

    build_root = root / "build" / target_name
    src_dir = build_root / "src"
    source_dir = prepare_source_dir(source_root, src_dir)
    x264_dir = prepare_source_dir(x264_root, build_root / "x264")

    install_dir = build_root / "install"
    install_dir.mkdir(parents=True, exist_ok=True)
    x264_install_dir = build_root / "x264-install"
    x264_install_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    raw_env = target_cfg.get("env") or {}
    for key, value in raw_env.items():
        env[key] = str(value)
    for key, value in raw_env.items():
        env[key] = expand_vars(str(value), env)

    target_flags = expand_list(target_cfg.get("configure", []), env)
    x264_flags = expand_list(target_cfg.get("x264_configure", []), env)
    for flag in target_flags:
        if flag.startswith("--cc="):
            env["CC"] = flag.removeprefix("--cc=")
        elif flag.startswith("--cxx="):
            env["CXX"] = flag.removeprefix("--cxx=")
        elif flag.startswith("--ar="):
            env["AR"] = flag.removeprefix("--ar=")
        elif flag.startswith("--ranlib="):
            env["RANLIB"] = flag.removeprefix("--ranlib=")

    common_flags = expand_list(ffmpeg_cfg.get("configure_common", []), env)
    extra_flags = expand_list(target_cfg.get("extra_configure", []), env)
    
    prefix_path = str(install_dir)
    if os.name == "nt":
        prefix_path = prefix_path.replace("\\", "/")
        if ":" in prefix_path:
            drive, path = prefix_path.split(":", 1)
            prefix_path = f"/{drive.lower()}{path}"
    configure_flags = (
        common_flags + target_flags + extra_flags + [f"--prefix={prefix_path}"]
    )

    extra_cflags = expand_vars(target_cfg.get("extra_cflags", ""), env)
    extra_ldflags = expand_vars(target_cfg.get("extra_ldflags", ""), env)
    if extra_cflags:
        env["CFLAGS"] = f"{env.get('CFLAGS', '')} {extra_cflags}".strip()
    if extra_ldflags:
        env["LDFLAGS"] = f"{env.get('LDFLAGS', '')} {extra_ldflags}".strip()

    jobs = int(ffmpeg_cfg.get("make_jobs", 0) or 0)
    if jobs <= 0:
        jobs = os.cpu_count() or 4

    x264_prefix = str(x264_install_dir)
    if os.name == "nt":
        x264_prefix = x264_prefix.replace("\\", "/")
        if ":" in x264_prefix:
            drive, path = x264_prefix.split(":", 1)
            x264_prefix = f"/{drive.lower()}{path}"
    x264_cmd = [
        "./configure",
        "--disable-cli",
        "--enable-static",
        "--disable-opencl",
        "--bit-depth=8",
        "--chroma-format=420",
        *x264_flags,
        f"--prefix={x264_prefix}",
    ]
    if os.name == "nt":
        x264_cmd = ["sh", *x264_cmd]
    x264_env = env.copy()
    # x264 selects NASM by default; FFmpeg targets may set AS to GNU as.
    x264_env.pop("AS", None)
    run(x264_cmd, cwd=x264_dir, env=x264_env)
    run(["make", f"-j{jobs}"], cwd=x264_dir, env=x264_env)
    run(["make", "install"], cwd=x264_dir, env=x264_env)

    pkgconfig_dir = x264_install_dir / "lib" / "pkgconfig"
    env["PKG_CONFIG_PATH"] = os.pathsep.join(filter(None, [str(pkgconfig_dir), env.get("PKG_CONFIG_PATH", "")]))

    configure_cmd = ["./configure", *configure_flags]
    if os.name == "nt":
        configure_cmd = ["sh", "./configure", *configure_flags]
        
    run(configure_cmd, cwd=source_dir, env=env)

    run(["make", f"-j{jobs}"], cwd=source_dir, env=env)
    run(["make", "install"], cwd=source_dir, env=env)

    package_libs = target_cfg.get("package_libs") or ffmpeg_cfg.get("package_libs", [])
    if not package_libs:
        raise SystemExit("package_libs is empty")

    dist_dir = root / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    tar_output = dist_dir / f"{target_name}.tar.gz"
    if tar_output.exists():
        tar_output.unlink()

    layout = ffmpeg_cfg.get("package_layout", "flat")
    with tarfile.open(tar_output, "w:gz") as tar:
        for lib_name in package_libs:
            lib_path = (x264_install_dir if lib_name == "libx264.a" else install_dir) / "lib" / lib_name
            if not lib_path.exists():
                raise SystemExit(f"missing library: {lib_path}")
            if layout == "flat":
                arcname = lib_name
            elif layout == "target-dir":
                arcname = f"{target_name}/{lib_name}"
            else:
                raise SystemExit(f"unknown package_layout: {layout}")
            tar.add(lib_path, arcname=arcname)

    print(f"Packaged {tar_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
