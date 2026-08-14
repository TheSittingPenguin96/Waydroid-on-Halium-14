# Waydroid on Halium 14 — corrected conclusions

**This file supersedes the rest of this repo.** Everything else in this repo is a historical record of how I
got here, and contains conclusions I later disproved. Where they disagree with
this file, this file wins.

Reference device: **Volla Phone Plinius (ansuz)**, Ubuntu Touch 24.04.4,
channel `24.04-1.x/arm64/android9plus/stable`, kernel 6.1.129, SoC mt6878
(MediaTek, Mali), host `ro.vndk.version=34`, host `ro.hardware.egl=meow`,
**waydroid 1.5.1**. Everything below was measured on that device.

---

## 1. Root cause, in one paragraph

Halium 14 publishes the graphics allocator over **AIDL only**. Waydroid 1.5.1
probes for it over **HIDL**, finds nothing, and falls back to
`gralloc=default, egl=swiftshader` — discarding the host's real
`ro.hardware.egl=meow` that it had already read. Waydroid's own init patch then
rewrites `swiftshader` to `angle`, and Waydroid's own (correct) mount logic has
meanwhile bind-mounted the host's `/vendor/lib64/egl` over the container's,
hiding the ANGLE drivers the vendor image ships. Result:
`couldn't find an OpenGL ES implementation`.

**Upstream already fixed this**, in
[`9bd8db0` "Detect AIDL gralloc5"](https://github.com/waydroid/waydroid/commit/9bd8db09d5d317e58d423ff7448399883d071b91)
by Jami Kettunen, so the first step is a Waydroid new enough to include it rather
than patching anything. That clears the boot failure onto the hardware path —
where three further blockers wait, ending in one that may not be fixable on this
base at all (§4a).

### What the symptom does and does not mean

Each verdict below was measured on this device.

| Claim | Verdict | Evidence |
| --- | --- | --- |
| Waydroid cannot initialise on Halium 14 | **false** | Both images download, validate and extract cleanly once one URL resolves |
| The container cannot run | **false** | `Container: RUNNING` |
| Android's init cannot run | **false** | `vold`, `keystore2`, `zygote`, `surfaceflinger` all start |
| It fails on a VNDK 33 vs 34 ABI mismatch | **incomplete** | The container is coherently Android 13. A real version split exists, but only on the hardware-rendering path |
| It fails in the EGL loader | **true** | but downstream of a gralloc probe failure, not in the loader's own logic — see §2 |

The chain starts at a **404** — `HALIUM_14.json` was never published — so
`waydroid init` fails before any hardware is touched. Everything below is what
happens once that first fetch is worked around, measured on this device.

Every correction above is about *how far it gets*, not *whether it works*.
"Waydroid does not support Halium 14" remains true in effect.

## 2. The chain, link by link

1. Host publishes `android.hardware.graphics.allocator.IAllocator/default` on
   `/dev/binder`. `/dev/hwbinder` carries **no** allocator.
2. `lxc.py: make_base_props()` tries `find_hal("gralloc")` (no passthrough `.so`
   on modern devices), then `find_hidl(...allocator@4.0...)` on `/dev/hwbinder`.
   Both fail. **1.5.1 has no `find_aidl`.**
3. Falls through to `gralloc="default", egl="swiftshader"`.
4. `waydroid-patches/base-patches-33/system/core/0013-init-Substitute-swiftshader-with-angle-pastel-on-ven.patch`
   fires — **only because the value is `swiftshader`**:
   ```c
   if (vendor >= 33 && properties["ro.hardware.egl"] == "swiftshader") {
       properties["ro.hardware.egl"] = "angle";
       properties["ro.hardware.vulkan"] = "pastel";
   }
   ```
   (`0015-init-Import-waydroid.prop-last.patch` is why `waydroid.prop` cannot
   win a first-write race against this — it is loaded immediately before.)
5. `images.py: mount_rootfs()` bind-mounts the host's read-only EROFS
   `/vendor/lib64/egl` **over** the container's, hiding `libEGL_angle.so`.
6. Loader asks for `libEGL_angle.so` (gone), falls back to
   `ro.board.platform=waydroid` (never existed). zygote and surfaceflinger abort.

## 3. Verification (tested 2026-08-11)

`find_aidl` backported into the device's 1.5.1, **all earlier hacks reverted**,
stock published images:

| Property | Before | With `find_aidl` |
| --- | --- | --- |
| `ro.hardware.gralloc` | `default` | `android` |
| `ro.hardware.egl` | `swiftshader` → `angle` | **`meow`** |
| `ro.hardware.vulkan` | `pastel` | `mali` |

```
D libEGL : loaded /vendor/lib64/egl/libGLES_meow.so     <- hardware driver
```

Then the next gap, cleanly isolated:

```
E libMEOW: load_driver(.../mt6878/libGLES_mali.so): dlopen failed:
           library "android.hardware.graphics.allocator-V2-ndk.so" not found
           ... in namespace sphal
```

Adding `allocator-V2-ndk` + `common-V4-ndk` to `/vendor/lib64` removed that,
the Mali DDK began executing and `system_server` came up — then
`surfaceflinger` aborted **inside the driver**:

```
#05 libGLES_mali.so (eglInitialize+1276)
#06 libEGL.so (egl_display_t::initialize)
#08 surfaceflinger (SkiaGLRenderEngine::create)
```

`/dev/mali0` **is** bind-mounted into the container and the allocator is
reachable, so this is not a missing-node problem. **This is where the hardware
path currently stops.**

## 4. ⚠ Do not ship the VNDK 34 libraries alone

Supplying `allocator-V2`/`common-V4` makes MediaTek's gralloc mapper
**loadable** — and once loadable it runs and aborts:

```
Abort message: 'Unable to retrieve GPU capabilities. XML file either not found
                or contains syntax errors. Aborting.'
  #03 .../mt6878/android.hardware.graphics.mapper@4.0-impl-mediatek.so
        (ip_support_feature)
```

This killed `surfaceflinger` **even on the otherwise-working ANGLE path**,
turning a graceful degradation into a hard failure.

**Cause identified 2026-08-13 by reverse engineering the mapper.** It reads GPU
capability XML from the *directory* `/vendor/etc/gralloc`, recovered from the
binary itself — `strings -a` yields `/vendor/etc/gralloc` and `Failed to open
capability directory:`, and `readelf -d` shows libxml2 is statically linked, so
a missing parser was never the issue. The host has five capability files there;
Waydroid's vendor image has no `etc/gralloc` at all, and the host copy lands at
`/vendor_extra/etc/gralloc` in the container. The mapper looks in a directory
that does not exist.

The libraries therefore belong in a HALIUM_14 image **together with** something
that makes `/vendor/etc/gralloc` visible. Recovery method in TODO item 5; fix in
`scripts/expose_mtk_gpu_configs.py`.

**The warning above is unconditional.** Do not install the published
`artifacts/` image, with or without the exposure script. It is a build result and
a starting point for someone assembling a correct image — not something to
flash.

## 4a. The real ceiling: a Treble version inversion

Three separate aborts were eliminated in sequence, each confirmed on device:

| Fix | Abort removed |
| --- | --- |
| `/vendor/etc/gralloc` capability XMLs | `Unable to retrieve GPU capabilities` |
| VNDK 34 graphics AIDL libraries | `dlopen ... allocator-V2-ndk.so not found` |
| 42 x `ro.vendor.arm.egl.configs.*` properties | `failed to allocate winsys_configs` |
| all three together | EGL initialises; `system_server` and both zygotes stable, no crash loop |

The next failure is different in kind:

```
SurfaceFlinger requests : usage 0x300  (GPU texture + render target)
MediaTek mapper decodes : usage 0x7f00200000    <- reserved bits set
                          "Invalid descriptorInfo sizes"
                          "Invalid attributes to create descriptor for Mapper 4.0"
GraphicBufferAllocator  : Failed to allocate (128x128) format 1 usage 300: -22
surfaceflinger          : abort "output buffer not gpu writeable"
                          RenderEngine::validateOutputBufferUsage
```

The client and the mapper disagree about the **shape of the buffer descriptor**.
The obvious explanation was checked and **disproved**: `BufferUsage` is
byte-identical between AIDL V3 and V4 in this tree, so the enum did not change.
What remains is an encode/decode mismatch between the Android 13 client
(`Gralloc4` in the container) and MediaTek's mapper, which is built against
`graphics.common-V4`.

**An inference, flagged as such -- this is NOT proven.** The leading explanation
is a **Treble version inversion**: Treble permits a system image *newer* than the
vendor partition and not the reverse, and this pairs an Android 13 system image
with an Android 14 vendor partition. If that is right, no host-side change helps
and it needs a system image of Android 14 or newer.

**I have not tested it.** Doing so needs a newer system image, which I could not
build. And one measurement cuts against the simple version story: `BufferUsage`
is byte-identical between AIDL V3 and V4 in this tree, so the obvious ABI break
is absent.

**A second explanation was not ruled out:** a descriptor mis-packing introduced
by Waydroid's own gralloc client path or by `hwcomposer.waydroid.so`, rather than
by the version pairing. That would be fixable *without* any new image, and it
matters which is true. Anyone able to trace the mapper call could separate the
two quickly -- log the `BufferDescriptorInfo` as encoded by the client against
what the mapper decodes.

Note also that I have previously held, and disproved, a claim that booting needs
an Android 14 system image (see section 7). That history is a reason to treat
this one as a hypothesis until someone tests it.

## 5. What actually needs doing

| # | Item | Where | Status |
| --- | --- | --- | --- |
| 1 | A Waydroid new enough to include `find_aidl` | UBports packaging | open — UT 24.04.4 ships 1.5.1 |
| 2 | A `HALIUM_14` vendor channel, or a vndk-34 mapping | Waydroid OTA / `get_vendor_type()` | open — `HALIUM_14.json` is a 404 |
| 3 | VNDK 34 graphics AIDL libs in HALIUM images — with the mapper's XML **and** the EGL config properties | vendor image + `lxc.py` | partially built here; see §4 |
| 4 | Backport the composer threadpool fix to `lineage-20` | `android_hardware_waydroid` | patch ready, not submitted |
| 5 | MediaTek mapper GPU-capabilities XML | solved — `/vendor/etc/gralloc` | confirmed on device; did not unblock rendering |
| 6 | `libGLES_mali.so` abort in `eglInitialize` | solved — missing `ro.vendor.arm.egl.configs.*` | confirmed on device; did not unblock rendering |
| 7 | **Test a system image of Android 14 or newer** (ideally `dev/lineage-23.2`) | Waydroid trees | **not started — nothing exists, and §4a turns on it** |

Item 5 was answered by reverse engineering the shipped binary — no vendor
documentation, about ten minutes with `readelf` and `strings`. An earlier
version of this file said reverse engineering could not substitute for a vendor
answer; that was too pessimistic. Item 6 then fell the same way, to disassembly.
Neither needed better build hardware — but the item that replaced them does: a
full Android 14+ system image build is the only way to test §4a.

## 6. Artifacts in this repo

```
artifacts/HALIUM_14-waydroid_arm64-vendor.img    93,339,648 bytes
artifacts/HALIUM_14-waydroid_arm64-vendor.img.sha256
    78817bc7ed0c229c37d27921a3ea0cab8188294a30947bb076c91dd5ebd80599
patches/0001-hwcomposer-don-t-shrink-the-binder-threadpool-*.patch
scripts/backport_find_aidl.py    reproduces the §3 test on a 1.5.1 device
scripts/patch_egl.py             egl-mount workaround; REQUIRED on the reference
                                 device today, pending TODO item 1
scripts/expose_mtk_gpu_configs.py
                                 exposes /vendor/etc/gralloc etc. (TODO item 5)
scripts/forward_arm_egl_configs.py
                                 forwards the 42 EGL config properties (item 6)
```

Built from LineageOS 20 + Waydroid manifests, `TARGET_USE_MESA=false`, in about
an hour and three quarters, on a laptop below AOSP's stated minimum RAM. Verified *inside the image*: both libraries present with matching
checksums, and the composer patch confirmed by symbol diff
(`configureRpcThreadpool` import gone versus the official image).

A vendor image is well within reach of modest hardware — nobody should be put
off contributing one for want of a workstation. Note though that **building one
does not lift the §4a ceiling**: no vendor image changes what the Android 13
system encodes. A full Android 14 *system*
image was not attempted here, but note the real obstacle there is not compute:
Waydroid has **no `lineage-21` branch at all**, its trees jumping from
`lineage-20` (Android 13) to `dev/lineage-23.2` (Android 16).

## 7. Conclusions I reached and later disproved

Recorded because each looked convincing and each cost hours.

| I concluded | Actually |
| --- | --- |
| `angle` is a bug in Waydroid's init | It is the intended generic path, and its drivers ship in the vendor image |
| The EGL bind mount is the bug | It is correct and load-bearing — it is how Halium devices get hardware GL |
| The composer threadpool abort must be fixed | Does not occur on the clean path; it was an artifact of my own hack force-loading the Mali driver |
| Booting needs an Android 14 system image | It does not — but hardware rendering may well, see §4a |
| Nothing in the tree sets `angle` | I searched for `egl=angle`; Android also writes `egl?=angle` and `setprop x y` |
| The two module names were free to use | AIDL module names are *generated*; the tree already defines V2/V4 as its unfrozen `current` versions |

## 8. Traps

**Waydroid / Ubuntu Touch**
- `lxc-attach` hangs when the container is `FROZEN` (`suspend_action=freeze`) — check `lxc-info -sH` first, it is not a crash.
- **Never start the Waydroid session over SSH** if the app grid should own it; the
  icon then silently does nothing and the switcher reports no running apps.
  Recover with `waydroid session stop`, then relaunch from the grid.
  I did this twice — the second time *while verifying the fix for the first* — so
  treat it as a procedure, not a warning. To inspect a running Waydroid, attach to
  the session the user started rather than creating one:
  ```sh
  waydroid status                                            # read-only
  adb -s <waydroid-ip>:5555 shell getprop sys.boot_completed
  adb -s <waydroid-ip>:5555 shell dumpsys window | grep mCurrentFocus
  ```
  The IP appears in `waydroid status` and in `/var/lib/waydroid/waydroid.log`
  ("Established ADB connection to Waydroid device at …"). Properties, logcat,
  process list and focused window are all reachable that way without starting
  anything.
- `waydroid-container.service` only manages the container; the LXC container starts with a **session**.
- Load average is meaningless on mt6878: 14 kernel threads sit permanently in D state, so the device idles at load ≈ 13 with Waydroid stopped. Use CPU idle.
- Editing `waydroid_base.prop` does nothing — `make_base_props()` regenerates it every start. The real hook is `waydroid.cfg`'s `[properties]`.
- The UT rootfs is read-only: `sudo mount -o remount,rw /`. Package files are reverted by `apt upgrade`.

**Evidence**
- A negative from a root-only file read as `phablet` is worthless. Always run a control that must succeed.
- Generated names cannot be grepped — check `aidl_api/` version directories instead.
- A canary property distinguishes "override lost" from "file never read".
- Read the project's own patch series early; `vendor/extra/waydroid-patches/` answered in minutes what symptom-chasing had not in hours.

**Building on a small machine**
- `systemd-oomd` kills on *pressure*, not exhaustion, and kills whole cgroups — `nohup` is no defence. Ubuntu sets `ManagedOOMMemoryPressure=kill` at 50% on `user@1000.service`. Run builds as a `system.slice` unit with `IgnoreOnIsolate=yes`.
- `all-makefiles-under` is exactly one level deep (`$(wildcard $(1)/*/Android.mk)`).
- ELF shared libraries cannot ship via `PRODUCT_COPY_FILES`; use a prebuilt module, and `LOCAL_MODULE_STEM` if the name collides.
- **`objdump` silently disassembles nothing if it lacks the target architecture.** It prints a file header and stops, which looks like an empty range. Check with `objdump -i | grep aarch64`; use `aarch64-linux-gnu-objdump` or AOSP's `llvm-objdump`. Stripped libraries also need addresses taken relative to the nearest exported symbol.
- **`MAKE_EXIT=0` says nothing about whether your change is in the image.** Twice I produced a green build and a correctly-sized image missing the payload. Verify with `debugfs -R "ls -l /lib64" vendor.img` and compare checksums.
