SM7475 GT Neo5 SE early boot diagnosis
=====================================

The diagnostic fragment is
``arch/arm64/configs/fragments/sm7475-mainline-diagnostic.config``.
Merge it with arm64 defconfig or the previously built configuration and run
olddefconfig before building Image and the board DTB. Build from a source
path without spaces; Kbuild does not support spaces in the source path.

Current boot-only tests retain the installed vendor_boot DTB and DTBO.
The compiled mainline board DTB is not selected by replacing boot alone.
The stock UART compatible is ``qcom,msm-geni-console``; the mainline GENI
console driver matches ``qcom,geni-debug-uart``. Building the console driver
in does not make these bindings interchangeable. Display output is not
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
not enable storage on the board. Capturing early logs and establishing a
bootloader-compatible mainline DTB/DTBO path remain necessary.
