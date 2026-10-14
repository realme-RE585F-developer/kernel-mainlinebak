SM7475 GT Neo5 SE early boot diagnosis
=====================================

Current Android v4 image set
----------------------------

The current package is ``artifacts/sm7475-linux-7.2.8/mainline-v4``. It
follows the stock split layout: ``boot.img`` contains the kernel and generic
ramdisk, while ``vendor_boot.img`` contains the vendor ramdisk, ramdisk
table, bootconfig and replacement mainline DTB. The package's ``dtbo.img``
is an unchanged stock copy. The two v4 images form one matched set; testing
only ``boot.img`` with ``fastboot boot`` leaves the installed ``vendor_boot``
and DTBO in use and does not test the packaged mainline DTB.

Standard fastboot ``boot`` accepts one boot image and cannot stage a separate
v4 ``vendor_boot`` image. Therefore a temporary ``fastboot boot boot.img``
result is inconclusive for this package. Testing the matched pair requires
the bootloader to load both images from their partitions. Do not flash either
partition until a full stock recovery image pair is available and a recovery
path is confirmed. A bootloader message such as ``Status read failed (No such
device)`` only indicates that USB disconnected during the handoff; it does
not reveal whether Linux was entered or why the phone reset.

The stock DTBO is not yet known to be compatible with the mainline DTB. ABL
was observed selecting stock DTBO entry 0, whose 129 external references are
absent from the mainline base DTB. Thus matching the v4 image pair is
necessary to test the package but is not sufficient to make it boot.

If a failed boot leaves the phone in fastboot, first inspect the current and
unbootable slot variables. The previously working system was recovered by
reselecting its original slot; do not use ``fastboot continue`` as a recovery
step. Never guess the original slot or overwrite a slot without its stock
images:

.. code-block:: sh

   fastboot getvar current-slot
   fastboot getvar slot-unbootable:a
   fastboot getvar slot-unbootable:b

The earlier v2 ``fastboot boot`` experiments below are historical diagnostics
and do not test the current v4 package.

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

The old v2 header used 0x8000, 0x1000000 and 0x1f00000 as absolute kernel,
ramdisk and DTB addresses. They are below the device's RAM start and also
place ramdisk and DTB inside the kernel's runtime extent. Merely adding a
RAM base would retain these overlaps. The new defaults place kernel at
0xa8000000, ramdisk at 0xc0000000 and DTB/tags at 0xaf000000. They lie in the
first RAM bank and outside the fixed reserved-memory regions in the board
DTB. The tool checks RAM containment, reserved regions, alignment and
pairwise overlap using the Image header's runtime size, including BSS.
It requires ``fdtget`` from the dtc package for these checks.

These are checks on header addresses, not measurements of ABL's actual
placement. The Qualcomm reference ABL computes kernel, ramdisk and DTB
addresses from firmware's kernel allocation and payload sizes. Correcting
the header alone therefore does not establish the cause of the failure.

The board DTS provides the first RAM bank (0x80000000, size 0x6a000000)
as a fallback, taken from the installed device's exported tree. The
bootloader may replace it with the full RAM banks. The framebuffer console
is selected with ``console=tty0`` in addition to the UART console. For a
verbose comparison, pass the following ``--cmdline`` value when packaging:

.. code-block:: text

   earlycon=qcom_geni,0x0099c000 console=tty0 console=ttyMSM0,115200n8 panic=0 loglevel=8 ignore_loglevel initcall_debug printk.time=1 fbcon=map:0

The original appended-DTB v4 test was reported to restart, while the old v2
test stayed at the splash screen during temporary ``fastboot boot``. The
new address layout fixes identifiable header defects; it does not establish
that the stock bootloader honors the addresses, selects the boot DTB or
boots the mainline kernel. UART logs or a running shell are still needed
to confirm the handoff and identify any remaining failure.

Device tests and slot recovery
------------------------------

The corrected v2 load-address image was temporarily loaded with
``fastboot boot``. Fastboot returned ``Booting OKAY``, but the screen stayed
at the OEM logo and the device subsequently responded to fastboot queries.
This does not establish kernel entry or DTB selection.

A subsequent v2 control using the backup stock kernel and ramdisk with the
same mainline DTB disconnected from fastboot and was reported to black-screen
or restart. The device then failed to start its installed Android system.
Both slots were reported ``slot-unbootable: yes``; before testing, slot A
had been bootable. No partition was flashed in these tests. A normal
``fastboot reboot`` alone did not recover the system.

Recovery used the originally active slot A:

.. code-block:: sh

   fastboot getvar current-slot
   fastboot getvar slot-unbootable:a
   fastboot set_active a
   fastboot getvar slot-unbootable:a
   fastboot reboot

``set_active a`` cleared A's unbootable flag and reset its retry count to 7.
Android then reconnected over ADB; ``sys.boot_completed=1``, slot ``_a`` and
the original 5.10.236 kernel confirmed recovery. The official vendor_boot
and DTBO were not flashed. The stock-kernel control must not be presented
as a known-good boot test. Additional tests require understanding this
bootloader's slot-state changes and obtaining evidence of the kernel handoff.

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

Installed ABL and stock DTBO evidence (2026-10-14)
-------------------------------------------------

Root access to the installed Android exposed ``/proc/bootloader_log`` and
``/sys/firmware/fdt``. ABL selected stock DTB index 2 and DTBO index 0.
The SoC ID is 0x24f, revision 0x10000, foundry 0; the board variant is 8,
major 0x10000, minor/subtype 0. These agree with the mainline board IDs.

The installed ABL contains the branch which skips board overlays only on
a complete DTB match. Its match mask is 0x1aaaaaaaaa8000e; unlike the
generic reference version, this includes OPlus project, hardware and
region matching as well as all sixteen PMIC model matches. Board IDs
alone do not bypass the stock DTBO. An experimental full-match DTB was
temporarily booted, but automatically restarted into stock Android; its
PMIC and OPlus properties have been removed. It is not a working fix.
The firmware's PMIC arrays have fifteen entries, while the full-match
mask requires sixteen slots, so extending the table is not a dependable
way to bypass the installed overlay selection.

The mainline base DTB has none of the 129 external symbols required by
stock DTBO entry 0. Check reference availability before another test:

.. code-block:: sh

   python3 tools/boot/check_dtbo_refs.py \
     --dtb sm7475-realme-gt-neo5-se.dtb \
     --stock-dtbo dtbo_a.img --index 0

This tool only reads the supplied files and reports missing symbols or
phandles. Entry selection must come from the device's ABL log; the tool
does not emulate ABL selection. Passing establishes reference availability
only, not overlay compatibility or bootability. ``fdtoverlay`` reports
NOTFOUND with the mainline base, but BADVALUE even with the stock base;
libfdt merge results alone cannot model the vendor's ufdt implementation.
For comparison, AOSP libufdt (revision
4f5784f8f46b38bd0e0249c3b1d0ce4b4faf36a8) successfully merged the stock
base and an experimental mainline base with 129 disabled target nodes.
The latter preserved mainline model, memory and /soc nodes and produced
a 1511093-byte DTB. A temporary boot of that experiment still stayed at
the OEM logo and remained accessible via fastboot. Thus resolving overlay
references alone does not fix the handoff. Neither experiment is included
in the board DTS.

``fastboot continue`` after the failed experiment disconnected USB and
led to black screen/restarts. On re-entering fastboot, slot A was marked
unbootable. Recovery again used ``set_active a`` followed by ``reboot``;
do not use ``continue`` as the recovery command for these failed tests.

ABL updates the splash reservation at the literal path
``/reserved-memory/splash_region``. The mainline DTS now uses that name,
just as it retains ``/memory``. Both intentionally lack unit addresses
to accommodate the installed firmware; dtc warns about these names.

Following the full-match experiment, Android reported boot completion,
slot _a and the original 5.10.236 kernel. Root reads verified that the
vendor_boot_a and dtbo_a partition hashes were unchanged before and after
the experiment. No partition was flashed. Pstore had no retained mainline
log; the current bootloader log describes the subsequent Android boot,
not the failed temporary handoff. Mainline kernel entry is still unproven.
