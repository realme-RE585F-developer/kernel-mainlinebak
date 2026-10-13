#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Reject malformed DT tables before passing device data to fdtget."""

import struct
import unittest

from check_dtbo_refs import extract_entry


class DtTableTests(unittest.TestCase):
    def setUp(self):
        self.blob = struct.pack('>2I', 0xd00dfeed, 40) + bytes(32)
        self.image = (struct.pack('>8I', 0xd7b7ab1e, 104, 32, 32, 1, 32, 4096, 0)
                      + struct.pack('>8I', 40, 64, 0, 0, 0, 0, 0, 0) + self.blob)

    def test_partition_padding_is_not_part_of_payload(self):
        self.assertEqual(extract_entry(self.image + bytes(4096), 0), self.blob)

    def test_payload_cannot_point_into_table(self):
        image = bytearray(self.image)
        struct.pack_into('>I', image, 36, 32)
        with self.assertRaisesRegex(ValueError, 'payload outside'):
            extract_entry(image, 0)

    def test_payload_cannot_exceed_declared_image_size(self):
        image = bytearray(self.image + bytes(4096))
        struct.pack_into('>I', image, 32, 90)
        with self.assertRaisesRegex(ValueError, 'payload outside'):
            extract_entry(image, 0)

    def test_index_and_compressed_table_are_rejected(self):
        for index in (-1, 1):
            with self.assertRaises(ValueError):
                extract_entry(self.image, index)
        image = bytearray(self.image)
        struct.pack_into('>I', image, 28, 1)
        with self.assertRaisesRegex(ValueError, 'uncompressed'):
            extract_entry(image, 0)


if __name__ == '__main__':
    unittest.main()
