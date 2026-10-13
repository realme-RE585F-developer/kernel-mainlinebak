SM7475 GT Neo5 SE early boot diagnosis
=====================================

The diagnostic fragment is
``arch/arm64/configs/fragments/sm7475-mainline-diagnostic.config``.
Merge it with arm64 defconfig or the previously built configuration and run
olddefconfig before building Image and the board DTB. Build from a source
path without spaces; Kbuild does not support spaces in the source path.

Android boot header v4 stores the DTB in ``vendor_boot``, after the vendor
ramdisk and before the vendor ramdisk table and bootconfig. To test the
mainline board DTB, replace that field in a copy of ``vendor_boot`` while
preserving the vendor ramdisk, table, bootconfig, DTB load address, and
partition padding. ``tools/boot/build_vendor_boot_dtb.py`` performs this
operation and refuses layouts it cannot verify. The output is unsigned:
the input AVB footer is discarded because it cannot authenticate the new DTB.
Replacing ``boot`` alone does not select the mainline DTB in the standard v4
layout. Appended-DTB support in the stock bootloader has not been established.

For example, after building
``arch/arm64/boot/dts/qcom/sm7475-realme-gt-neo5-se.dtb``:

.. code-block:: sh

   python3 tools/boot/build_vendor_boot_dtb.py \
     --input vendor_boot_a.img \
     --dtb arch/arm64/boot/dts/qcom/sm7475-realme-gt-neo5-se.dtb \
     --output vendor_boot-mainline.img

``fastboot boot`` cannot temporarily load this vendor_boot image. Testing
requires installing it into the intended vendor_boot slot, with a backup and
a matching mainline boot image. Before doing so, establish how the bootloader
selects and applies the installed DTBO: stock overlays cannot be assumed
compatible with the mainline DTB. This script does not modify DTBO or flash
the device.

A v4 boot image with an appended DTB and a v2 boot image with a standard DTB
field are diagnostic experiments only; they are not the normal layout for
this phone.

An appended-DTB v4 test was reported to restart, while the v2 test stayed at
the splash screen. Neither result establishes which DTB was passed to Linux,
whether Linux started, or which component caused the failure. Obtain UART
logs or inspect the active device tree after reaching a shell before drawing
conclusions about bootloader format support.

The stock UART compatible is ``qcom,msm-geni-console``; the mainline GENI
console driver matches ``qcom,geni-debug-uart``. Building the console driver
in does not make these bindings interchangeable. The board DTS exposes the
bootloader scanout with simple-framebuffer; native panel support is not
implemented, so the bootloader splash is not evidence that Linux started.

A temporary boot with ``panic=10 loglevel=8 ignore_loglevel`` was reported
to reset after about eight seconds at the first splash screen. Stock
Android subsequently reported boot reason ``bootloader``. That reason and
the elapsed time do not establish whether Linux ran or why it reset.
Pstore and dmesg were inaccessible to the Android shell.

Use a separate boot image with ``panic=0 loglevel=8 ignore_loglevel`` as a
controlled comparison, keeping its kernel and ramdisk identical. In this
kernel panic=0 prevents the panic handler from requesting an automatic
restart; an external watchdog or firmware can still reset the device.
If resetting continues, investigate those paths and whether the command
line actually reached Linux. If it stops, a panic timer becomes a candidate,
but UART or persistent logs are still required to identify the failure.
This comparison does not validate bootability or AVB signatures.

The stock reserved-memory ramoops node has dynamic allocation properties
(size 0x240000, console-size 0x40000, pmsg-size 0x200000), without a fixed
reg address. Do not choose an arbitrary physical address for ramoops.
The stock UFS PHY compatible ``qcom,ufs-phy-qmp-v4-cape`` has no matching
mainline driver in this tree. Enabling the UFS configuration alone does
not enable storage on the board. Capturing early logs and validating the
bootloader's mainline DTB/DTBO selection remain necessary.
