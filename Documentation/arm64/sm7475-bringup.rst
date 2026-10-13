SM7475 GT Neo5 SE early boot diagnosis
=====================================

The diagnostic fragment is
``arch/arm64/configs/fragments/sm7475-mainline-diagnostic.config``.
Merge it with arm64 defconfig or the previously built configuration and run
olddefconfig before building Image and the board DTB. Build from a source
path without spaces; Kbuild does not support spaces in the source path.

The current test keeps the official ``vendor_boot`` and puts the mainline
DTB in the standard Android boot header v2 DTB section of ``boot.img``.
``tools/boot/build_boot_dtb.py`` extracts the kernel and ramdisk from the v4
test boot image, then uses AOSP ``mkbootimg.py`` to write the v2 header,
kernel, ramdisk, and DTB sections. It does not read or modify ``vendor_boot``.
The output is unsigned and has no AVB footer.

After building the board DTB, run:

.. code-block:: sh

   python3 tools/boot/build_boot_dtb.py \
     --base-boot boot-mainline-screen-diagnostic.img \
     --dtb arch/arm64/boot/dts/qcom/sm7475-realme-gt-neo5-se.dtb \
     --mkbootimg /path/to/mkbootimg.py \
     --output boot-mainline-dtb.img

Keep the official ``vendor_boot`` and ``dtbo`` unchanged. Temporarily load
``boot-mainline-dtb.img`` using ``fastboot boot``. The standard v2 DTB section
is separate from the kernel payload. Android boot v3/v4 has no equivalent
boot DTB field; stock bootloader support for v2 still requires verification.

The default base is zero and the kernel, ramdisk, tags and DTB offsets are
0x8000, 0x1000000, 0x100 and 0x1f00000 respectively. These reproduce the
previous v2 experiment; they came from stock header metadata and are not
validated physical load addresses. Override them using the script's address
options only when bootloader evidence establishes the required values.

An appended-DTB v4 test was reported to restart, while the previous v2 test
stayed at the splash screen. Rebuilding the same v2 payload and addresses
reproduces that image and does not fix its boot failure. Neither result
establishes which DTB was passed to Linux, whether Linux started, or which
component caused the failure. Obtain UART logs or inspect the active device
tree after reaching a shell before drawing conclusions.

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
