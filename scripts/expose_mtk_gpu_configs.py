#!/usr/bin/env python3
"""
Expose MediaTek's GPU configuration files to the Waydroid container.

NOTE: this removes ONE abort. It does not produce working or accelerated
Waydroid, and on its own it achieves nothing useful. See CONCLUSIONS.md 4a.

THE PROBLEM
  MediaTek's graphics stack reads several configuration files from /vendor/etc.
  Inside the Waydroid container, /vendor is Waydroid's own vendor image, which
  contains none of them; the real vendor partition is rbind-mounted out of the
  way at /vendor_extra. So every one of these lookups fails.

WHAT NEEDS EXPOSING, AND HOW IT WAS FOUND
  Each path below was recovered from the shipped binaries with readelf/strings,
  not from documentation:

  /vendor/etc/gralloc/          (directory, 5 XML files)
      android.hardware.graphics.mapper@4.0-impl-mediatek.so
        "/vendor/etc/gralloc", "Failed to open capability directory:"
      Missing -> 'Unable to retrieve GPU capabilities ... Aborting.'
      CONFIRMED on device: supplying it eliminates that abort.

  /vendor/etc/mali_platform.config
      libGLES_mali.so, symbol arm::mali::mali_platform_config()
      Real content on this device:
        PLATFORM_AGT_FREQUENCY_KHZ=13000
        OSU_PROTECTED_MEMORY_HEAP_NAME=mtk_svp_page-uncached
      The second value names a dma-buf heap, consistent with the
      libdmabufheap.so dependency. This WAS a candidate cause of the
      libGLES_mali.so eglInitialize abort; it is DISPROVED -- supplying it left
      the abort unchanged at the identical address. The real cause was missing
      ro.vendor.arm.egl.configs.* properties; see forward_arm_egl_configs.py.
      Copied here for completeness only.

  /vendor/etc/meow.cfg
      libGLES_meow.so, "meow reload base cfg path: %s" (logs "na" when absent)
      Only 9 bytes ("[global]") on this device, so probably not critical, but
      copied for completeness. meow_dev.cfg is an optional dev overlay and does
      not exist here.

METHOD
  Copies into Waydroid's vendor overlay rather than bind-mounting, because the
  container's /vendor is read-only and these targets do not exist there to
  mount onto.

REVERSING IT
  sudo rm -rf /var/lib/waydroid/overlay/vendor/etc/gralloc
  sudo rm -f  /var/lib/waydroid/overlay/vendor/etc/mali_platform.config
  sudo rm -f  /var/lib/waydroid/overlay/vendor/etc/meow.cfg

Run with sudo, restart the container, then launch Waydroid FROM THE APP GRID.
"""
import os
import shutil
import sys

OVERLAY = "/var/lib/waydroid/overlay/vendor/etc"

# (host path, is_directory, required)
ITEMS = [
    ("/vendor/etc/gralloc", True, True),
    ("/vendor/etc/mali_platform.config", False, False),
    ("/vendor/etc/meow.cfg", False, False),
    ("/vendor/etc/meow_dev.cfg", False, False),
]

if os.geteuid() != 0:
    sys.exit("must be run as root (sudo)")

os.makedirs(OVERLAY, exist_ok=True)
copied, skipped, missing_required = [], [], []

for src, is_dir, required in ITEMS:
    name = os.path.basename(src)
    dst = os.path.join(OVERLAY, name)
    if not os.path.exists(src):
        (missing_required if required else skipped).append(src)
        continue
    if is_dir:
        if os.path.isdir(dst):
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        for f in os.listdir(dst):
            os.chmod(os.path.join(dst, f), 0o644)
        copied.append("%s/  (%d files)" % (src, len(os.listdir(dst))))
    else:
        shutil.copy2(src, dst)
        os.chmod(dst, 0o644)
        copied.append(src)

for c in copied:
    print("  copied   %s" % c)
for s in skipped:
    print("  absent   %s  (optional on this device)" % s)
for m in missing_required:
    print("  MISSING  %s  <- required; is this a MediaTek device?" % m)

if missing_required:
    sys.exit("\nrequired path(s) not found on this host; nothing usable copied")

print("\nthese now appear under /vendor/etc/ inside the container")
print("next:")
print("  waydroid session stop")
print("  sudo systemctl restart waydroid-container")
print("  then launch Waydroid FROM THE APP GRID (never start a session over SSH)")
