#!/usr/bin/env python3
"""
Make MediaTek's GPU capability XML visible to the gralloc mapper inside the
Waydroid container.

WHY
  android.hardware.graphics.mapper@4.0-impl-mediatek.so reads GPU capability
  descriptions from the DIRECTORY /vendor/etc/gralloc. Recovered from the
  binary itself:

      $ readelf -d  mapper.so        # libxml2 is statically linked
      $ strings -a  mapper.so
        /vendor/etc/gralloc
        Failed to open capability directory:
        Read capability file from
        Failed to stat file for capability reading:

  On the host that directory holds cam.xml, dpu.xml, dpu_aeu.xml, gpu.xml and
  vpu.xml (<capabilities version="0.2">). Inside the container the host vendor
  partition is rbind-mounted at /vendor_extra, while /vendor is Waydroid's own
  vendor image -- which contains no etc/gralloc at all. So the mapper looks in a
  directory that does not exist and aborts:

      'Unable to retrieve GPU capabilities. XML file either not found or
       contains syntax errors. Aborting.'

WHAT THIS DOES
  Copies the host's capability files into Waydroid's vendor overlay, so they
  appear at /vendor/etc/gralloc inside the container. Uses the overlay rather
  than a bind mount because the container's /vendor is read-only and the
  gralloc directory does not exist there to mount onto.

REVERSING IT
  sudo rm -rf /var/lib/waydroid/overlay/vendor/etc/gralloc

Run with sudo. Restart the container/session afterwards, and launch Waydroid
from the app grid (never start a session over SSH).
"""
import os
import shutil
import sys

SRC = "/vendor/etc/gralloc"
DST = "/var/lib/waydroid/overlay/vendor/etc/gralloc"

if os.geteuid() != 0:
    sys.exit("must be run as root (sudo)")

if not os.path.isdir(SRC):
    sys.exit("ERROR: %s does not exist on this host.\n"
             "This device may not be MediaTek, or may lay the files out "
             "differently. Check with:\n"
             "  strings -a <mapper>.so | grep -i 'capability directory'" % SRC)

names = sorted(n for n in os.listdir(SRC) if n.endswith(".xml"))
if not names:
    sys.exit("ERROR: no .xml capability files in %s" % SRC)

os.makedirs(DST, exist_ok=True)
for n in names:
    shutil.copy2(os.path.join(SRC, n), os.path.join(DST, n))
    os.chmod(os.path.join(DST, n), 0o644)

print("copied %d capability file(s) from %s" % (len(names), SRC))
for n in names:
    print("   ", n)
print("\nthey will appear at /vendor/etc/gralloc inside the container")
print("restart the container, then launch Waydroid FROM THE APP GRID:")
print("  waydroid session stop")
print("  sudo systemctl restart waydroid-container")
