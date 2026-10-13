#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Pack a mainline DTB into the standard Android boot header v2 DTB section.

Extract kernel and ramdisk from a v4 boot image and use AOSP mkbootimg to
produce boot.img. No vendor_boot input or output is used. Output is unsigned.
Load addresses are configurable and checked against the supplied DTB's RAM
and reserved-memory ranges. Bootloader compatibility still needs device tests.
"""

import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile


PAGE = 4096


def align(size):
    return (size + PAGE - 1) // PAGE * PAGE


def digest(data):
    return hashlib.sha256(data).hexdigest()


def memory_map(dtb):
    """Read the two-cell RAM/reservation layout using dtc's fdtget."""
    def prop(node, name):
        result = subprocess.run(['fdtget', '-t', 'x', str(dtb), node, name],
                                capture_output=True, text=True)
        if result.returncode:
            return []
        return [int(value, 16) for value in result.stdout.split()]

    def children(node):
        return subprocess.run(['fdtget', '-l', str(dtb), node], check=True,
                              capture_output=True, text=True).stdout.split()

    def ranges(node):
        cells = prop(node, 'reg')
        if len(cells) % 4:
            raise ValueError(f'unsupported reg layout at {node}')
        return [(cells[i] * 2**32 + cells[i + 1],
                 cells[i + 2] * 2**32 + cells[i + 3])
                for i in range(0, len(cells), 4) if cells[i + 2] or cells[i + 3]]

    if prop('/', '#address-cells') != [2] or prop('/', '#size-cells') != [2]:
        raise ValueError('expected two-cell root memory addresses and sizes')
    ram = [region for node in children('/') if node.split('@')[0] == 'memory'
           for region in ranges('/' + node)]
    if not ram:
        raise ValueError('DTB has no usable RAM ranges for load-address validation')
    root_children = children('/')
    reserved = []
    if 'reserved-memory' in root_children:
        if (prop('/reserved-memory', '#address-cells') != [2]
                or prop('/reserved-memory', '#size-cells') != [2]):
            raise ValueError('expected two-cell reserved-memory layout')
        reserved = [region for node in children('/reserved-memory')
                    for region in ranges('/reserved-memory/' + node)]
    return ram, reserved


def validate_loads(addresses, sizes, ram, reserved):
    regions = [(name, addresses[name], sizes[name]) for name in sizes]
    for name, start, size in regions:
        end = start + size
        if not any(base <= start and end <= base + length for base, length in ram):
            raise ValueError(f'{name} load range {start:#x}..{end:#x} is outside RAM')
        if any(start < base + length and base < end for base, length in reserved):
            raise ValueError(f'{name} load range overlaps reserved memory')
    for index, (name, start, size) in enumerate(regions):
        for other, other_start, other_size in regions[index + 1:]:
            if start < other_start + other_size and other_start < start + size:
                raise ValueError(f'{name} and {other} load ranges overlap')
    if addresses['kernel'] % (2 * 1024 * 1024):
        raise ValueError('kernel load address must be 2 MiB aligned for this Image')
    if addresses['dtb'] % 8:
        raise ValueError('DTB load address must be 8-byte aligned')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-boot', type=Path, required=True,
                        help='v4 boot image supplying kernel and initramfs')
    parser.add_argument('--dtb', type=Path, required=True)
    parser.add_argument('--mkbootimg', type=Path, required=True,
                        help='AOSP mkbootimg.py')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--base', type=lambda v: int(v, 0), default=0x80000000)
    parser.add_argument('--kernel-offset', type=lambda v: int(v, 0), default=0x28000000)
    parser.add_argument('--ramdisk-offset', type=lambda v: int(v, 0), default=0x40000000)
    parser.add_argument('--tags-offset', type=lambda v: int(v, 0), default=0x2f000000)
    parser.add_argument('--dtb-offset', type=lambda v: int(v, 0), default=0x2f000000)
    parser.add_argument('--cmdline', help='override base boot command line')
    args = parser.parse_args()
    inputs = (args.base_boot, args.dtb, args.mkbootimg)
    outputs = (args.output, Path(str(args.output) + '.json'),
               Path(str(args.output) + '.sha256'))
    if any(out.resolve() == inp.resolve() for out in outputs for inp in inputs):
        parser.error('output must not overwrite an input')

    boot = args.base_boot.read_bytes()
    if len(boot) < PAGE or boot[:8] != b'ANDROID!':
        parser.error('invalid base boot image')
    if struct.unpack_from('<I', boot, 40)[0] != 4:
        parser.error('base boot must use header v4')
    kernel_size, ramdisk_size, os_value, header_size = struct.unpack_from('<4I', boot, 8)
    if header_size != 1584:
        parser.error('unexpected v4 header size')
    kernel = boot[PAGE:PAGE + kernel_size]
    ramdisk_offset = PAGE + align(kernel_size)
    ramdisk = boot[ramdisk_offset:ramdisk_offset + ramdisk_size]
    if len(kernel) != kernel_size or len(ramdisk) != ramdisk_size:
        parser.error('truncated base boot')
    if kernel[56:60] != b'ARMd':
        parser.error('expected an uncompressed arm64 Image')
    dtb = args.dtb.read_bytes()
    if len(dtb) < 40 or struct.unpack_from('>II', dtb) != (0xd00dfeed, len(dtb)):
        parser.error('expected one complete DTB with a valid FDT header')
    cmdline = (args.cmdline if args.cmdline is not None
               else boot[44:1580].split(b'\0')[0].decode())
    os_version = os_value >> 11
    os_version = f'{os_version >> 14}.{(os_version >> 7) & 127}.{os_version & 127}'
    patch = os_value & 2047
    patch = f'{2000 + (patch >> 4):04d}-{patch & 15:02d}'
    addresses = {
        'kernel': args.base + args.kernel_offset,
        'ramdisk': args.base + args.ramdisk_offset,
        'tags': args.base + args.tags_offset,
        'dtb': args.base + args.dtb_offset,
    }
    if any(v < 0 or v >= 2**32 for k, v in addresses.items() if k != 'dtb'):
        parser.error('kernel, ramdisk and tags addresses must fit in 32 bits')
    if not 0 <= addresses['dtb'] < 2**64:
        parser.error('DTB address must fit in 64 bits')
    kernel_runtime_size = max(len(kernel), struct.unpack_from('<Q', kernel, 16)[0])
    sizes = {'kernel': kernel_runtime_size, 'ramdisk': len(ramdisk), 'dtb': len(dtb)}
    try:
        ram, reserved = memory_map(args.dtb)
        validate_loads(addresses, sizes, ram, reserved)
    except ValueError as error:
        parser.error(str(error))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='boot-dtb-v2-') as temporary:
        temp = Path(temporary)
        (temp / 'kernel').write_bytes(kernel)
        (temp / 'ramdisk').write_bytes(ramdisk)
        packed = temp / 'boot.img'
        subprocess.run([
            sys.executable, str(args.mkbootimg), '--header_version', '2',
            '--kernel', str(temp / 'kernel'), '--ramdisk', str(temp / 'ramdisk'),
            '--dtb', str(args.dtb), '--pagesize', str(PAGE),
            '--base', str(args.base), '--kernel_offset', str(args.kernel_offset),
            '--ramdisk_offset', str(args.ramdisk_offset),
            '--tags_offset', str(args.tags_offset), '--dtb_offset', str(args.dtb_offset),
            '--cmdline', cmdline, '--os_version', os_version, '--os_patch_level', patch,
            '--output', str(packed),
        ], check=True)
        result = packed.read_bytes()

    dtb_file_offset = PAGE + align(len(kernel)) + align(len(ramdisk))
    # Inspect header fields and compare all payloads before publishing output.
    checks = [
        result[:8] == b'ANDROID!',
        struct.unpack_from('<I', result, 40)[0] == 2,
        struct.unpack_from('<I', result, 36)[0] == PAGE,
        struct.unpack_from('<I', result, 1644)[0] == 1660,
        struct.unpack_from('<I', result, 8)[0] == len(kernel),
        struct.unpack_from('<I', result, 16)[0] == len(ramdisk),
        struct.unpack_from('<I', result, 24)[0] == 0,
        struct.unpack_from('<I', result, 1632)[0] == 0,
        struct.unpack_from('<I', result, 1648)[0] == len(dtb),
        struct.unpack_from('<Q', result, 1652)[0] == addresses['dtb'],
        struct.unpack_from('<I', result, 12)[0] == addresses['kernel'],
        struct.unpack_from('<I', result, 20)[0] == addresses['ramdisk'],
        struct.unpack_from('<I', result, 32)[0] == addresses['tags'],
        result[PAGE:PAGE + len(kernel)] == kernel,
        result[ramdisk_offset:ramdisk_offset + len(ramdisk)] == ramdisk,
        result[dtb_file_offset:dtb_file_offset + len(dtb)] == dtb,
        len(result) == dtb_file_offset + align(len(dtb)),
    ]
    if not all(checks):
        raise ValueError('packed boot header or payload verification failed')
    args.output.write_bytes(result)
    manifest = {
        'header_version': 2, 'page_size': PAGE,
        'base_boot': str(args.base_boot), 'base_boot_sha256': digest(boot),
        'kernel_sha256': digest(kernel), 'ramdisk_sha256': digest(ramdisk),
        'dtb_sha256': digest(dtb), 'cmdline': cmdline,
        'dtb_file_offset': dtb_file_offset, 'dtb_size': len(dtb),
        'load_addresses': addresses, 'image_bytes': len(result),
        'load_sizes': sizes, 'dtb_ram_ranges': ram,
        'image_sha256': digest(result),
        'validation': 'Header and payload checks passed; bootability unverified.',
        'signing': 'Unsigned; no AVB footer.',
    }
    outputs[1].write_text(json.dumps(manifest, indent=2) + '\n')
    outputs[2].write_text(f'{digest(result)}  {args.output.name}\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
