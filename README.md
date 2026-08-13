# Waydroid on Halium 14

**Waydroid now boots to the Android launcher on a Volla Phone Plinius running
Ubuntu Touch 24.04.4** — a device combination the community had written off as
unsupported.

The *fix* turned out to need no new images, no new Android base, and no patch of
mine. The blocker was a **single capability probe on the wrong bus**, and
upstream Waydroid had already fixed it. Ubuntu Touch simply ships an older
Waydroid.

(The reference phone does currently run a local stopgap, because that upstream
fix has not reached it yet — see [Status](#status).)

---

## The finding, in short

Halium 14 publishes the graphics allocator over **AIDL**. Waydroid 1.5.1 probes
for it over **HIDL** only, finds nothing, and falls back to
`egl=swiftshader` — throwing away the hardware driver name it had already read
from the host. Waydroid's own init patch then rewrites `swiftshader` to `angle`,
whose drivers have meanwhile been hidden by a bind mount that is itself
perfectly correct. The result is the error everyone reports:

```
couldn't find an OpenGL ES implementation, make sure you set
ro.hardware.egl or ro.board.platform
```

Upstream master added `find_aidl` and closed this. **Shipping a current Waydroid
to Ubuntu Touch is the fix.**

I verified this end to end: backporting `find_aidl` alone, with every hack
reverted and stock published images, flipped the device onto the *hardware*
driver.

## What was done here

| | |
| --- | --- |
| **Diagnosed** | the full causal chain, six links, each measured on the device |
| **Verified** | `find_aidl` backported → `ro.hardware.egl=meow`, hardware driver loads |
| **Built** | a HALIUM_14 vendor image carrying the VNDK 34 graphics AIDL libraries and a composer fix |
| **Located** | the remaining hardware-rendering blockers, precisely, in MediaTek's driver stack |
| **Corrected** | six of my own conclusions that turned out to be wrong |

## Where to start

| File | What it is |
| --- | --- |
| **[CONCLUSIONS.md](CONCLUSIONS.md)** | **The authoritative technical account.** Root cause, the tested chain, verification, and the traps. Start here. |
| **[TODO.md](TODO.md)** | What is still open, and who is best placed to do it — including items only Volla or MediaTek can realistically answer. |
| [HISTORY.md](HISTORY.md) | How the investigation actually went, including the wrong turns. Kept because the dead ends are instructive. |

## Repository contents

```
CONCLUSIONS.md      authoritative findings
TODO.md             open items, by who can do them
patches/            composer threadpool backport for lineage-20
prebuilts/          VNDK 34 graphics AIDL libs used in the vendor image
scripts/            backport_find_aidl.py  reproduces the key verification
                    patch_egl.py           REQUIRED on the reference device today (see Status)
artifacts/          the built HALIUM_14 vendor image + checksum
HISTORY.md          the route, including the wrong turns
```

The built image is ~90 MB; `artifacts/` is better suited to a release
attachment than to git history.

### Reproducing the key test

On an affected device running waydroid 1.5.1:

```sh
sudo python3 scripts/backport_find_aidl.py     # adds find_aidl, reverts old hacks
waydroid session stop && sudo systemctl restart waydroid-container
waydroid session start
sudo grep hardware /var/lib/waydroid/waydroid_base.prop
```

Expected: `ro.hardware.gralloc=android`, `ro.hardware.egl=meow` (or your host's
value), `ro.hardware.vulkan=mali` — instead of `default` / `swiftshader` /
`pastel`.

## Status

### What the reference device actually runs

Waydroid works on the reference phone today — but **not on stock software.** It
needs `scripts/patch_egl.py` applied, which stops the host EGL bind mount hiding
the vendor image's ANGLE drivers:

```
waydroid 1.5.1 (stock, unmodified)
published lineage-20.0 VANILLA system + HALIUM_13 vendor images (stock)
+ scripts/patch_egl.py                 <- required, or it does not boot
```

That patch is a **workaround, not the fix.** The fix is [TODO](TODO.md) item 1 —
a Waydroid new enough to have `find_aidl`, which makes the bind mount correct
again and selects the hardware driver instead of ANGLE.

⚠ `images.py` is package-owned, so **`apt upgrade waydroid` reverts the patch**
and Waydroid stops booting with `couldn't find an OpenGL ES implementation`. The
original is saved beside it as `images.py.orig`. If that upgrade brings a
Waydroid with `find_aidl`, do *not* re-apply the patch — retest instead, because
the whole picture changes.

### Rendering

**Software rendering works today** — the device boots and runs Android apps.
**Hardware rendering does not yet**: with `find_aidl` the Mali driver is
selected and loads, but MediaTek's gralloc mapper aborts on a missing
GPU-capabilities XML, and `libGLES_mali.so` aborts inside `eglInitialize`.
Those two are the frontier, and they need MediaTek/Mali knowledge rather than
more compute. See [TODO.md](TODO.md).

⚠ **Do not install the vendor image in `artifacts/` expecting an improvement.**
It supplies libraries that make MediaTek's mapper *loadable*, which then aborts
and takes down `surfaceflinger` — worse than leaving them out. It is published
as a build result and a starting point, not a fix. See CONCLUSIONS.md §4.

## Acknowledgements

**Hugh Manns**, for the suggestion to attack the proprietary binaries directly
on open items #5 and #6 rather than waiting on vendor documentation. That
overturned a position stated in this repository — that reverse engineering could
not substitute for a vendor answer — and item 5 then fell to `readelf -d` and
`strings` in about ten minutes. It also produced the table of eliminated
hypotheses under item 6, which is the more useful half of the result even though
that item remains open.

Two refinements raised while the approach was being weighed are worth recording,
because they were checked first and checking them was cheap: look for **format
strings** as well as literals, since MediaTek builds paths from properties and a
path built from an unset property collapses with no `openat` to trace; and treat
the abort's *"not found **or** syntax errors"* as two distinct branches. Neither
applied in the end — the path was a plain literal and libxml2 turned out to be
statically linked — but ruling them out took seconds and would have saved hours
had either held.

## Licence and provenance

Everything here was measured on hardware; nothing is quoted from documentation
or forums. Corrections welcome — several of my own are recorded in
CONCLUSIONS.md §7.
