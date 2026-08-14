# Waydroid on Halium 14 — investigation report

**There is nothing here to install.** This is a device-level measurement of where
the current stack breaks on one phone, offered to the people working the problem
upstream.

Hardware-accelerated Waydroid on Halium 14 **does not work**, and nothing in this
repository makes it work. What runs on my own phone is software rendering only,
via a local patch to a package-owned file that reverts on the next
`apt upgrade`. Do not expect to reproduce it, and please do not try on a device
you depend on.

Halium 14 support is an open, actively worked problem upstream — see the
[UBports tracking issue](https://gitlab.com/ubports/porting/reference-device-ports/halium-14/volla-phone-plinius/volla-ansuz/-/work_items/1).

Reference device: Volla Phone Plinius (ansuz), Ubuntu Touch 24.04.4, SoC mt6878
(MediaTek, Mali), host `ro.vndk.version=34`, waydroid 1.5.1.

---

## What actually goes wrong

Halium 14 publishes the graphics allocator over **AIDL**. Waydroid 1.5.1 probes
for it over **HIDL** only, finds nothing, and falls back to `egl=swiftshader`.
Waydroid's own init patch rewrites that to `angle`, whose drivers have meanwhile
been hidden by a bind mount that is itself correct. The error most reports end
at:

```
couldn't find an OpenGL ES implementation, make sure you set
ro.hardware.egl or ro.board.platform
```

**This is already fixed upstream**, by
[`9bd8db0` "Detect AIDL gralloc5"](https://github.com/waydroid/waydroid/commit/9bd8db09d5d317e58d423ff7448399883d071b91)
from Jami Kettunen. Ubuntu Touch 24.04.4 simply ships an older Waydroid (1.5.1)
that predates it. This repo verifies on hardware that the change is sufficient
to select the host's real EGL driver.

Clearing that exposed four further blockers. Three were solved here. The fourth
is where the investigation stops.

## Where it stops

With `find_aidl` applied, plus three fixes established here, EGL initialises and
`system_server` comes up. Rendering still fails:

```
SurfaceFlinger requests : usage 0x300
MediaTek mapper decodes : usage 0x7f00200000   <- reserved bits set
                          "Invalid descriptorInfo sizes"
surfaceflinger          : abort "output buffer not gpu writeable"
```

The client and the mapper disagree about the buffer descriptor's shape. **The
leading explanation is a Treble version inversion** — an Android 13 system image
against an Android 14 vendor partition, which is the direction Treble does not
support. **I have not tested that**, and it needs a newer system image I could
not build. An alternative I could not rule out is a descriptor mis-packing in
Waydroid's own gralloc client path or `hwcomposer.waydroid.so`, which would be
fixable without any new image. Anyone with a mapper trace could separate the two
quickly. See [CONCLUSIONS.md](CONCLUSIONS.md) §4a.

## What is in here

A device-level trace of the boot failure, each link measured on the Plinius; a
verification that upstream's `find_aidl` alone selects the hardware driver; three
further blockers found by reverse-engineering the shipped MediaTek binaries and
confirmed fixed on device; and a HALIUM_14 vendor image built with the VNDK 34
graphics AIDL libraries — **which must not be installed on its own**, see below.

Six conclusions I reached along the way turned out to be wrong. They are recorded
in [CONCLUSIONS.md](CONCLUSIONS.md) §7, and the route including the dead ends is
in [HISTORY.md](HISTORY.md).

The two findings most likely to be useful to someone else:

- **`/vendor/etc/gralloc`** — MediaTek's mapper reads GPU capability XML from
  that directory. Waydroid's vendor image has no such directory, and the host's
  copy lands at `/vendor_extra`.
- **42 × `ro.vendor.arm.egl.configs.*`** — Arm's EGL winsys builds its EGLConfig
  table from these properties. The container has none, and `lxc.py` forwards
  several other host property families but not this one.

## Where to start

| File | What it is |
| --- | --- |
| **[CONCLUSIONS.md](CONCLUSIONS.md)** | Current findings, and what has actually been tested. Start here. |
| **[TODO.md](TODO.md)** | What is still open, grouped by where the change would have to land. |
| [HISTORY.md](HISTORY.md) | How the investigation went, including the wrong turns. |

## Repository contents

```
CONCLUSIONS.md   findings, and what was tested versus inferred
TODO.md          open items, grouped by where a change would land
HISTORY.md       the route taken, including six abandoned positions
patches/         composer threadpool backport for lineage-20
prebuilts/       VNDK 34 graphics AIDL libs used in the vendor image
scripts/         backport_find_aidl.py       verifies the upstream fix
                 expose_mtk_gpu_configs.py   exposes /vendor/etc/gralloc etc.
                 forward_arm_egl_configs.py  forwards the 42 EGL properties
                 patch_egl.py                software-rendering stopgap
artifacts/       the built HALIUM_14 vendor image + checksum
```

Each script removes exactly one blocker and leaves you no closer to usable
Waydroid. Read the docstring in each before running it; two of them can stop
Waydroid booting on a device where it currently does.

## The reference device, and why not to copy it

My phone boots Waydroid with **software rendering only**, and only because
`scripts/patch_egl.py` patches a package-owned file:

```
waydroid 1.5.1 (stock, unmodified)
published lineage-20.0 VANILLA system + HALIUM_13 vendor images (stock)
+ scripts/patch_egl.py            <- required, or it does not boot
```

It is slow, it reverts on `apt upgrade`, and Waydroid then stops booting with
`couldn't find an OpenGL ES implementation`. The original is saved as
`images.py.orig`. If a future Waydroid package includes `find_aidl`, do **not**
re-apply this patch — retest instead, because the whole picture changes.

⚠ **Do not install the vendor image in `artifacts/`.** On its own it makes
MediaTek's gralloc mapper loadable, which then aborts and takes down
`surfaceflinger` — worse than leaving it out. It is a build result and a
starting point for someone assembling a correct image, not something to flash.

## Acknowledgements

**Jami Kettunen**, for
[`9bd8db0`](https://github.com/waydroid/waydroid/commit/9bd8db09d5d317e58d423ff7448399883d071b91),
the upstream fix that this repository does no more than verify on hardware, and
for maintaining the Halium 14 tracking issue. **NotKit**, who has been developing
against that issue. This repo is one device-level datapoint for their work, not a
parallel effort.

**Hugh Manns**, for the suggestion to attack the proprietary binaries directly
rather than wait on vendor documentation. That overturned a position stated here
— that reverse engineering could not substitute for a vendor answer — and both
MediaTek-specific blockers then fell to `readelf`, `strings` and `objdump`.

## Provenance and licence

Everything here was measured on this device; nothing is repeated secondhand.
Where I have inferred rather than measured, it is flagged as such — §4a is the
important one. Corrections welcome; several of my own are in CONCLUSIONS.md §7.

`prebuilts/vndk34-arm64/*.so` are unmodified AOSP VNDK 34 binaries taken from
[`waydroid/android_prebuilts_vndk_v34`](https://github.com/waydroid/android_prebuilts_vndk_v34)
(branch `dev/lineage-23.2`), `arm64/arch-arm64-armv8-a/shared/vndk-sp/`, and are
Apache-2.0. The prose, scripts and patches in this repository are
GPL-3.0-or-later. Documentation was drafted with AI assistance; every
measurement in it was taken on the hardware described and is reproducible from
the commands given.
