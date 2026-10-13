#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Regression checks for physical load placement, including kernel BSS."""

import unittest

from build_boot_dtb import validate_loads


class LoadPlacementTests(unittest.TestCase):
    def setUp(self):
        self.ram = [(0x80000000, 0x6a000000)]
        self.reserved = [(0x80000000, 0x600000), (0xb8000000, 0x2b00000)]
        self.addresses = {
            'kernel': 0xa8000000, 'ramdisk': 0xc0000000, 'dtb': 0xaf000000,
        }
        self.sizes = {'kernel': 43515904, 'ramdisk': 34128128, 'dtb': 9066}

    def test_disjoint_ram_loads(self):
        validate_loads(self.addresses, self.sizes, self.ram, self.reserved)

    def test_offsets_are_not_physical_ram_addresses(self):
        addresses = {'kernel': 0x8000, 'ramdisk': 0x1000000, 'dtb': 0x1f00000}
        with self.assertRaisesRegex(ValueError, 'outside RAM'):
            validate_loads(addresses, self.sizes, self.ram, self.reserved)

    def test_ramdisk_must_not_overlap_kernel_bss(self):
        addresses = dict(self.addresses, ramdisk=0xaa900000)
        # This lies beyond the 42326528-byte Image file but inside its
        # 43515904-byte runtime extent, where BSS is cleared at startup.
        self.assertGreater(addresses['ramdisk'], addresses['kernel'] + 42326528)
        with self.assertRaisesRegex(ValueError, 'kernel and ramdisk.*overlap'):
            validate_loads(addresses, self.sizes, self.ram, self.reserved)

    def test_framebuffer_reservation_is_not_load_storage(self):
        addresses = dict(self.addresses, ramdisk=0xb8000000)
        with self.assertRaisesRegex(ValueError, 'reserved memory'):
            validate_loads(addresses, self.sizes, self.ram, self.reserved)


if __name__ == '__main__':
    unittest.main()
