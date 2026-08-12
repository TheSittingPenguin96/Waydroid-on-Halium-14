# How the investigation actually went

A record of the route, kept because the wrong turns are more instructive than
the answer. **For what is actually true, read [CONCLUSIONS.md](CONCLUSIONS.md).**
Nothing in this file should be acted on directly.

---

## The route

**Starting point.** Community consensus: Waydroid does not support Halium 14.
The visible symptom was `waydroid init` dying on a 404 for
`HALIUM_14.json`, and — once that was bypassed with a locally served
`HALIUM_13` manifest — zygote and surfaceflinger aborting with
`couldn't find an OpenGL ES implementation`.

**First position: "`angle` is a bug."** The container reported
`ro.hardware.egl=angle` while the host said `meow`, and no ANGLE driver was
visible anywhere. Days of searching failed to find where `angle` came from. Two
things were wrong with that search: it looked for the literal `egl=angle` when
Android also writes `egl?=angle` and `setprop x y`, and several greps ran as an
unprivileged user over root-only files and returned meaningless negatives.

A canary property finally distinguished "the override lost" from "the file was
never read", proving no property file could win — which pointed at code.

**Second position: "the bind mount is the bug."** Unpacking the published vendor
image showed it *does* ship `libEGL_angle.so`, `libGLESv2_angle.so` and
`vulkan.pastel.so` — and that Waydroid's own `mount_rootfs()` bind-mounts the
host's `/vendor/lib64/egl` over them. Disabling that loop made the device boot
to the Android launcher for the first time.

That felt like the answer. It was not. It removed hardware GL from every Halium
device, and it treated a load-bearing mechanism as a defect.

**Third position, and the correct one.** Reading Waydroid's own patch series
(`vendor/extra/waydroid-patches/base-patches-33/system/core/`) showed that
`angle` is substituted **only when the value is already `swiftshader`** — which
comes from one place: `lxc.py`'s fallback when gralloc detection fails. One
`gbinder` call then settled it: the host publishes the allocator over AIDL, and
waydroid 1.5.1 only probes HIDL.

Backporting upstream's `find_aidl` — with every earlier hack reverted — flipped
the device onto the hardware driver, exactly as predicted.

## Positions held and abandoned

| Held | Why it was wrong |
| --- | --- |
| `angle` is a bug in init | It is the intended generic path; its drivers ship in the vendor image |
| The EGL bind mount is the bug | It is correct and load-bearing — it is how Halium devices get hardware GL |
| The composer threadpool abort must be fixed | It never occurs on the clean path; it was an artifact of my own hack force-loading the Mali driver |
| Booting needs an Android 14 system image | It does not |
| A VNDK 33/34 ABI mismatch is the cause | The container is coherently Android 13; a real split exists but only on the hardware path |
| The two prebuilt module names were unused | AIDL module names are generated; the tree already defines V2/V4 as its unfrozen `current` versions |

## Things that cost the most time

- **Chasing symptoms instead of reading the project's own patches.** The
  `angle` substitution sat in a named patch file the entire time.
- **Trusting negatives.** Every "not found" in this investigation was wrong at
  least once — from unreadable files, wrong search patterns, or names that are
  generated rather than written.
- **Trusting a green build.** Twice a build reported success and produced a
  correctly-sized image that did not contain the libraries I had added.
- **Fighting the build machine** rather than the problem: two `systemd-oomd`
  kills and a power-cycle before working out that Ubuntu kills on memory
  *pressure*, per cgroup, and that a build must live outside the user slice.
- **Fixing one blocker mostly revealed the next**, and it was tempting to read
  that as progress. Twice the new failure was caused by the fix itself.

## What survived from those notes

The operational lessons are consolidated into CONCLUSIONS.md §8 (traps). The
build procedure is in the repository README. The only thing lost is a set of
intermediate conclusions that were superseded, which is the point.
