#!/usr/bin/env python3
"""Build Android v4 boot and vendor_boot images for the SM7475 board.

The phone uses the standard Android v4 split layout: boot.img contains the
kernel and generic ramdisk, while vendor_boot.img contains the vendor ramdisk,
ramdisk table, bootconfig, and DTB.  This tool keeps those sections from the
stock images and replaces only the requested kernel, generic ramdisk, and DTB.
It never modifies the input images and emits unsigned, partition-sized images.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile


PAGE = 4096
BOOT_HEADER = 1584
VENDOR_HEADER = 2128
ANDROID = b"ANDROID!"
VENDOR = b"VNDRBOOT"


def pages(size):
    return (size + PAGE - 1) // PAGE


def padded(data):
    return data + b"\0" * (pages(len(data)) * PAGE - len(data))


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def section(data, offset, size):
    end = offset + size
    if end > len(data):
        raise ValueError(f"section exceeds input: {offset:#x}+{size:#x}")
    return data[offset:end]


def valid_dtb(data):
    return len(data) >= 40 and struct.unpack_from(">II", data) == (0xD00DFEED, len(data))


def stock_boot_layout(data):
    if len(data) < PAGE or data[:8] != ANDROID:
        raise ValueError("boot input is not an Android image")
    version = struct.unpack_from("<I", data, 40)[0]
    if version != 4 or struct.unpack_from("<I", data, 20)[0] != BOOT_HEADER:
        raise ValueError("boot input must use Android boot header v4")
    kernel_size, ramdisk_size, os_value = struct.unpack_from("<3I", data, 8)
    kernel = section(data, PAGE, kernel_size)
    ramdisk = section(data, PAGE + pages(kernel_size) * PAGE, ramdisk_size)
    cmdline = data[44:1580].split(b"\0", 1)[0].decode("ascii")
    return kernel, ramdisk, os_value, cmdline


def stock_vendor_layout(data):
    if len(data) < PAGE or data[:8] != VENDOR:
        raise ValueError("vendor_boot input is not an Android image")
    version, page_size = struct.unpack_from("<II", data, 8)
    if version != 4 or page_size != PAGE:
        raise ValueError("vendor_boot input must use v4 and 4096-byte pages")
    if struct.unpack_from("<I", data, 2096)[0] != VENDOR_HEADER:
        raise ValueError("unexpected vendor_boot header size")
    ramdisk_size = struct.unpack_from("<I", data, 24)[0]
    dtb_size = struct.unpack_from("<I", data, 2100)[0]
    table_size = struct.unpack_from("<I", data, 2112)[0]
    table_entries = struct.unpack_from("<I", data, 2116)[0]
    table_entry_size = struct.unpack_from("<I", data, 2120)[0]
    bootconfig_size = struct.unpack_from("<I", data, 2124)[0]
    if table_entry_size != 108 or table_size != table_entries * table_entry_size:
        raise ValueError("unsupported vendor ramdisk table")
    ramdisk_off = PAGE
    dtb_off = ramdisk_off + pages(ramdisk_size) * PAGE
    table_off = dtb_off + pages(dtb_size) * PAGE
    bootconfig_off = table_off + pages(table_size) * PAGE
    ramdisk = section(data, ramdisk_off, ramdisk_size)
    dtb = section(data, dtb_off, dtb_size)
    table = section(data, table_off, table_size)
    bootconfig = section(data, bootconfig_off, bootconfig_size)
    return bytearray(data[:PAGE]), ramdisk, dtb, table, bootconfig


def build_boot(mkbootimg, base_boot, kernel, ramdisk, cmdline, output):
    _, _, os_value, base_cmdline = stock_boot_layout(base_boot)
    if not cmdline:
        cmdline = base_cmdline
    os_version = os_value >> 11
    os_version = f"{os_version >> 14}.{(os_version >> 7) & 127}.{os_version & 127}"
    patch = os_value & 2047
    patch = f"{2000 + (patch >> 4):04d}-{patch & 15:02d}"
    with tempfile.TemporaryDirectory(prefix="mainline-boot-") as temp_name:
        temp = Path(temp_name)
        kernel_file = temp / "kernel"
        ramdisk_file = temp / "ramdisk"
        packed = temp / "boot.img"
        kernel_file.write_bytes(kernel)
        ramdisk_file.write_bytes(ramdisk)
        subprocess.run([
            sys.executable, str(mkbootimg), "--header_version", "4",
            "--kernel", str(kernel_file), "--ramdisk", str(ramdisk_file),
            "--cmdline", cmdline, "--os_version", os_version,
            "--os_patch_level", patch, "--output", str(packed),
        ], check=True)
        result = packed.read_bytes()
    if result[:8] != ANDROID or struct.unpack_from("<I", result, 40)[0] != 4:
        raise ValueError("mkbootimg did not produce a v4 boot image")
    return result, cmdline


def build_vendor(base_vendor, dtb):
    header, ramdisk, old_dtb, table, bootconfig = stock_vendor_layout(base_vendor)
    if not valid_dtb(dtb):
        raise ValueError("DTB must contain exactly one complete FDT")
    struct.pack_into("<I", header, 2100, len(dtb))
    result = bytes(header) + padded(ramdisk) + padded(dtb) + padded(table) + padded(bootconfig)
    if len(result) > len(base_vendor):
        raise ValueError("replacement vendor_boot exceeds the input partition")
    return result + b"\0" * (len(base_vendor) - len(result))


def publish(data, output, partition_size):
    if partition_size and len(data) > partition_size:
        raise ValueError(f"{output.name} exceeds partition size")
    if partition_size:
        data += b"\0" * (partition_size - len(data))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mkbootimg", type=Path, required=True)
    parser.add_argument("--base-boot", type=Path, required=True)
    parser.add_argument("--base-vendor-boot", type=Path, required=True)
    parser.add_argument("--kernel", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--kernel-release", required=True)
    parser.add_argument("--ramdisk", type=Path, required=True)
    parser.add_argument("--dtb", type=Path, required=True)
    parser.add_argument("--dtbo", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cmdline", default="")
    args = parser.parse_args()
    inputs = [args.mkbootimg, args.base_boot, args.base_vendor_boot,
              args.kernel, args.config, args.ramdisk, args.dtb, args.dtbo]
    boot_base = args.base_boot.read_bytes()
    vendor_base = args.base_vendor_boot.read_bytes()
    kernel = args.kernel.read_bytes()
    config = args.config.read_bytes()
    ramdisk = args.ramdisk.read_bytes()
    dtb = args.dtb.read_bytes()
    dtbo = args.dtbo.read_bytes()
    boot, cmdline = build_boot(args.mkbootimg, boot_base, kernel, ramdisk,
                               args.cmdline, args.output_dir / "boot.img")
    vendor = build_vendor(vendor_base, dtb)
    boot_path = args.output_dir / "boot.img"
    vendor_path = args.output_dir / "vendor_boot.img"
    boot = publish(boot, boot_path, len(boot_base))
    vendor = publish(vendor, vendor_path, len(vendor_base))
    dtbo_path = args.output_dir / "dtbo.img"
    shutil.copyfile(args.dtbo, dtbo_path)
    manifest = {
        "layout": "Android boot header v4; DTB in vendor_boot",
        "cmdline": cmdline,
        "kernel_release": args.kernel_release,
        "partition_bytes": {"boot": len(boot), "vendor_boot": len(vendor)},
        "payload_sha256": {
            "kernel": sha256(kernel), "boot_ramdisk": sha256(ramdisk),
            "dtb": sha256(dtb), "boot": sha256(boot), "vendor_boot": sha256(vendor),
            "dtbo": sha256(dtbo), "stock_boot": sha256(boot_base),
            "stock_vendor_boot": sha256(vendor_base), "config": sha256(config),
        },
        "inputs": {"kernel": str(args.kernel), "config": str(args.config),
                   "ramdisk": str(args.ramdisk),
                   "dtb": str(args.dtb), "dtbo": str(args.dtbo),
                   "base_boot": str(args.base_boot),
                   "base_vendor_boot": str(args.base_vendor_boot)},
        "preserved": ["vendor ramdisk", "vendor ramdisk table", "vendor bootconfig", "DTB load address", "dtbo input untouched"],
        "signing": "unsigned; AVB footer not generated",
        "validation": "v4 headers, payload sections, partition sizes and DTB FDT header checked",
    }
    manifest_path = args.output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    for path, data in ((boot_path, boot), (vendor_path, vendor), (dtbo_path, dtbo)):
        (path.with_suffix(path.suffix + ".sha256")).write_text(f"{sha256(data)}  {path.name}\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
