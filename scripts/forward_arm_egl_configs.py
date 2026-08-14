#!/usr/bin/env python3
"""
Forward the host's ro.vendor.arm.egl.configs.* properties into the Waydroid
container.

NOTE: this removes ONE abort and reveals the next. Afterwards EGL initialises
and the crash loop stops -- and rendering still does not work, because the
blocker underneath is unresolved (CONCLUSIONS.md 4a). Nothing in this repo,
including this script, produces working hardware-accelerated Waydroid.

WHY
  Arm's Mali EGL winsys builds its EGLConfig list from Android system
  properties. Recovered from libGLES_mali.so: a table of thunks, each loading a
  property-name string and calling a shared getter, with symbols such as

    vendor::arm::egl::properties::r8_g8_b8_a8_32bit_fixed_hal_format()
    vendor::arm::egl::properties::r8_g8_b8_a8_32bit_fixed_recordable()

  and strings such as

    ro.vendor.arm.egl.configs.r8_g8_b8_a8_32bit_fixed.hal_format
    ro.vendor.arm.egl.configs.nv12.recordable
    ro.vendor.arm.egl.configs.r8_g8_b8_a0_32bit_fixed.framebuffer_target

  This host has 42 such properties. Waydroid's container runs its own property
  service and has NONE of them: they are absent from Waydroid's vendor image
  (checked with debugfs) and lxc.py never forwards them.

  Consequence, traced by disassembly: get_configs() populates two config lists
  from these properties, computes total = countA + countB, and calls
  malloc(total * 56). With no properties the counts come out inconsistent, the
  allocation fails, and the DDK aborts:

    "failed to allocate winsys_configs"   (libGLES_mali.so, get_configs)

  which surfaces as surfaceflinger crash-looping inside eglInitialize.

WHAT THIS DOES
  Copies every ro.vendor.arm.egl.* property from the host into the
  [properties] section of /var/lib/waydroid/waydroid.cfg. Waydroid appends that
  section last when generating waydroid_base.prop, and since nothing else in the
  container defines these names, they take effect despite ro.* being
  first-write-wins.

REVERSING IT
  A backup is written next to waydroid.cfg before any change. Restore with:
    sudo cp /var/lib/waydroid/waydroid.cfg.pre-armegl /var/lib/waydroid/waydroid.cfg

Run with sudo, restart the container, then launch Waydroid FROM THE APP GRID.
"""
import configparser
import os
import shutil
import subprocess
import sys

CFG = "/var/lib/waydroid/waydroid.cfg"
PREFIX = "ro.vendor.arm.egl."

if os.geteuid() != 0:
    sys.exit("must be run as root (sudo)")
if not os.path.exists(CFG):
    sys.exit("ERROR: %s not found -- has waydroid been initialised?" % CFG)

out = subprocess.run(["getprop"], capture_output=True, text=True).stdout
props = {}
for line in out.splitlines():
    line = line.strip()
    if not line.startswith("["):
        continue
    try:
        key, val = line.split("]: [", 1)
    except ValueError:
        continue
    key = key[1:]
    val = val.rstrip("]")
    if key.startswith(PREFIX):
        props[key] = val

if not props:
    sys.exit("ERROR: no %s* properties on this host.\n"
             "This device may not use an Arm Mali EGL stack." % PREFIX)

cfg = configparser.ConfigParser()
cfg.optionxform = str          # preserve key case
cfg.read(CFG)
if not cfg.has_section("properties"):
    cfg.add_section("properties")

added = 0
for k, v in sorted(props.items()):
    if cfg.get("properties", k, fallback=None) != v:
        cfg.set("properties", k, v)
        added += 1

if not os.path.exists(CFG + ".pre-armegl"):
    shutil.copy2(CFG, CFG + ".pre-armegl")
    print("  backup: %s.pre-armegl" % CFG)

with open(CFG, "w") as f:
    cfg.write(f)

print("  forwarded %d of %d ro.vendor.arm.egl.* properties" % (added, len(props)))
for k in sorted(props)[:6]:
    print("    %s = %s" % (k, props[k]))
if len(props) > 6:
    print("    ... and %d more" % (len(props) - 6))
print("\nnext:")
print("  waydroid session stop")
print("  sudo systemctl restart waydroid-container")
print("  then launch Waydroid FROM THE APP GRID")
