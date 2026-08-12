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
print("patched OK")
