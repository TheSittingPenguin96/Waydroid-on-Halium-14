#!/usr/bin/env python3
"""Backport upstream Waydroid's find_aidl() gralloc probe into 1.5.1.

The change itself is upstream 9bd8db0 "Detect AIDL gralloc5" by Jami Kettunen;
this script only applies it to an older installed Waydroid so the result can be
verified on device.

WHAT IT ACHIEVES: the container stops falling back to swiftshader/angle and
selects the host's real EGL driver. That is all. It does NOT produce working
hardware-accelerated Waydroid -- the driver then loads and aborts further along,
and the ceiling underneath (CONCLUSIONS.md section 4a) is unresolved.

WARNING -- THIS CAN STOP WAYDROID BOOTING. It reverts patch_egl.py by restoring
images.py from images.py.orig. If your device currently boots Waydroid only
because patch_egl.py is applied, running this will stop it booting. Re-apply
patch_egl.py to get back.
"""
import shutil, os, sys

# ---- 1. revert the images.py diagnostic hack -------------------------------
img = "/usr/lib/waydroid/tools/helpers/images.py"
if os.path.exists(img + ".orig"):
    shutil.copy2(img + ".orig", img)
    print("images.py  : restored from .orig (egl bind mount active again)")
else:
    print("images.py  : no .orig found -- assuming stock")

# ---- 2. backport find_aidl into lxc.py -------------------------------------
p = "/usr/lib/waydroid/tools/helpers/lxc.py"
orig = p + ".orig"
if not os.path.exists(orig):
    shutil.copy2(p, orig)
    print("lxc.py     : backup created at .orig")

s = open(orig).read()

find_hidl_block = '''    def find_hidl(intf):
        if args.vendor_type == "MAINLINE":
            return False

        try:
            sm = gbinder.ServiceManager("/dev/hwbinder")
            return intf in sm.list_sync()
        except:
            return False
'''

find_aidl_block = '''
    def find_aidl(intf):
        if args.vendor_type == "MAINLINE":
            return False

        try:
            sm = gbinder.ServiceManager("/dev/binder")
            return intf in sm.list_sync()
        except:
            return False
'''

if s.count(find_hidl_block) != 1:
    print("ERROR: find_hidl anchor not unique (count=%d)" % s.count(find_hidl_block))
    sys.exit(1)
s = s.replace(find_hidl_block, find_hidl_block + find_aidl_block)

old_branch = '''        if find_hidl("android.hardware.graphics.allocator@4.0::IAllocator/default"):
            gralloc = "android"
'''
new_branch = '''        if find_hidl("android.hardware.graphics.allocator@4.0::IAllocator/default"):
            gralloc = "android"
        elif find_aidl("android.hardware.graphics.allocator.IAllocator/default"):
            gralloc = "android"
'''
if s.count(old_branch) != 1:
    print("ERROR: gralloc branch anchor not unique (count=%d)" % s.count(old_branch))
    sys.exit(1)
s = s.replace(old_branch, new_branch)

open(p, "w").write(s)
print("lxc.py     : find_aidl backported")

# ---- 3. verify it parses ---------------------------------------------------
import py_compile
try:
    py_compile.compile(p, doraise=True)
    print("lxc.py     : syntax OK")
except Exception as e:
    print("ERROR: syntax check failed: %s" % e)
    shutil.copy2(orig, p)
    print("lxc.py     : reverted")
    sys.exit(1)
