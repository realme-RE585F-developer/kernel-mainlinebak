#!/usr/bin/env python3
"""Replace the DTB in an Android vendor_boot v4 image.

The vendor ramdisk, vendor ramdisk table, bootconfig, header addresses and
partition-sized padding are copied from the input image. This is the normal
Android v4 vendor_boot layout; the script does not append a DTB to Image and
does not change boot.img.

The output has no AVB footer. Any input signatures are discarded because
they cannot authenticate the replacement DTB.
"""

import argparse
import hashlib
from pathlib import Path
import struct


MAGIC = b"VNDRBOOT"
PAGE = 4096
HEADER_SIZE = 2128
DTB_SIZE_OFFSET = 2100
DTB_OFFSET_OFFSET = 2104
RAMDISK_SIZE_OFFSET = 24
TABLE_SIZE_OFFSET = 2112
BOOTCONFIG_SIZE_OFFSET = 2124


def pages(size):
    return (size + PAGE - 1) // PAGE


def padded(data):
    return data + b"\0" * (pages(len(data)) * PAGE - len(data))


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def section(image, offset, size):
    end = offset + size
    if end > len(image):
        raise ValueError(f"section exceeds image: {offset:#x}+{size:#x}")
    return image[offset:end]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True,
                        help="stock or previously generated vendor_boot.img")
    parser.add_argument("--dtb", type=Path, required=True,
                        help="mainline DTB compiled with dtc")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve() in (args.input.resolve(), args.dtb.resolve()):
        parser.error("output must not overwrite an input")

    source = args.input.read_bytes()
    if len(source) < PAGE or source[:8] != MAGIC:
        parser.error("input is not an Android vendor_boot image")
    version, page_size = struct.unpack_from("<II", source, 8)
    if version != 4 or page_size != PAGE:
        parser.error("only vendor_boot header v4 with 4096-byte pages is supported")
    if struct.unpack_from("<I", source, 2096)[0] != HEADER_SIZE:
        parser.error("unexpected vendor_boot v4 header size")

    ramdisk_size = struct.unpack_from("<I", source, RAMDISK_SIZE_OFFSET)[0]
    dtb_size = struct.unpack_from("<I", source, DTB_SIZE_OFFSET)[0]
    table_size = struct.unpack_from("<I", source, TABLE_SIZE_OFFSET)[0]
    table_entries = struct.unpack_from("<I", source, 2116)[0]
    table_entry_size = struct.unpack_from("<I", source, 2120)[0]
    bootconfig_size = struct.unpack_from("<I", source, BOOTCONFIG_SIZE_OFFSET)[0]
    if table_entry_size != 108 or table_size != table_entries * table_entry_size:
        parser.error("unsupported vendor ramdisk table")

    old_dtb_offset = PAGE + pages(ramdisk_size) * PAGE
    old_table_offset = old_dtb_offset + pages(dtb_size) * PAGE
    bootconfig_offset = old_table_offset + pages(table_size) * PAGE
    ramdisk = section(source, PAGE, ramdisk_size)
    table = section(source, old_table_offset, table_size)
    bootconfig = section(source, bootconfig_offset, bootconfig_size)
    for offset in range(0, table_size, table_entry_size):
        fragment_size, fragment_offset = struct.unpack_from("<II", table, offset)
        if fragment_offset + fragment_size > ramdisk_size:
            parser.error("vendor ramdisk table entry exceeds ramdisk")
    dtb = args.dtb.read_bytes()
    if len(dtb) < 40 or struct.unpack_from(">II", dtb) != (0xD00DFEED, len(dtb)):
        parser.error("expected one complete DTB with a valid FDT header")

    header = bytearray(source[:PAGE])
    struct.pack_into("<I", header, DTB_SIZE_OFFSET, len(dtb))
    # Keep the input DTB load address. Bootloader firmware commonly expects
    # this address and only the payload size changes here.
    dtb_address = struct.unpack_from("<Q", header, DTB_OFFSET_OFFSET)[0]
    output = bytes(header) + padded(ramdisk) + padded(dtb) + padded(table) + padded(bootconfig)
    if len(output) > len(source):
        parser.error(f"replacement layout exceeds input partition ({len(output)} > {len(source)})")
    output += b"\0" * (len(source) - len(output))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output)
    # Reparse the result and verify every section that should be preserved.
    result = args.output.read_bytes()
    result_dtb_offset = PAGE + pages(ramdisk_size) * PAGE
    result_table_offset = result_dtb_offset + pages(len(dtb)) * PAGE
    result_bootconfig_offset = result_table_offset + pages(table_size) * PAGE
    assert struct.unpack_from("<I", result, DTB_SIZE_OFFSET)[0] == len(dtb)
    assert struct.unpack_from("<Q", result, DTB_OFFSET_OFFSET)[0] == dtb_address
    assert section(result, PAGE, ramdisk_size) == ramdisk
    assert section(result, result_dtb_offset, len(dtb)) == dtb
    assert section(result, result_table_offset, table_size) == table
    assert section(result, result_bootconfig_offset, bootconfig_size) == bootconfig
    print(f"output={args.output}")
    print(f"partition_bytes={len(result)}")
    print(f"dtb_bytes={len(dtb)}")
    print(f"dtb_load_address={dtb_address:#x}")
    print(f"dtb_offset={result_dtb_offset:#x}")
    print(f"dtb_sha256={sha256(dtb)}")
    print(f"image_sha256={sha256(result)}")


if __name__ == "__main__":
    main()
