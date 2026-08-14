#!/usr/bin/env python3
"""DIAGNOSTIC STOPGAP -- NOT A FIX, AND NOT RECOMMENDED FOR ANYONE ELSE.

Disables Waydroid's host-EGL bind mount so the vendor image's own ANGLE drivers
stay visible. The result is SOFTWARE rendering (ANGLE + pastel) only. It does
not, and cannot, give hardware acceleration -- see CONCLUSIONS.md section 4a.

This edits /usr/lib/waydroid/tools/helpers/images.py, which is OWNED BY THE
WAYDROID PACKAGE. `apt upgrade waydroid` reverts it, after which Waydroid stops
booting with "couldn't find an OpenGL ES implementation". The original is saved
alongside as images.py.orig.

If your Waydroid is new enough to contain find_aidl (upstream 9bd8db0), do NOT
run this -- retest instead, because the whole picture changes.
"""
import shutil, os, sys
p = "/usr/lib/waydroid/tools/helpers/images.py"
orig = p + ".orig"
if not os.path.exists(orig):
    shutil.copy2(p, orig)
    print("backup created:", orig)
s = open(orig).read()
a = '    for egl_path in ["/vendor/lib/egl", "/vendor/lib64/egl"]:'
b = ('    # DIAGNOSTIC (restore from images.py.orig): do NOT bind the host EGL\n'
     '    # dir over the vendor image, which ships its own libEGL_angle.so there.\n'
     '    for egl_path in []:')
if s.count(a) != 1:
    print("ERROR: anchor not unique, count =", s.count(a)); sys.exit(1)
open(p, "w").write(s.replace(a, b))
print("patched OK -- software rendering only; reverts on apt upgrade")
