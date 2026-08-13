# Open items

Grouped by who is best placed to do them. Technical background for every item is
in [CONCLUSIONS.md](CONCLUSIONS.md).

Reference device: Volla Phone Plinius (ansuz), Ubuntu Touch 24.04.4, SoC mt6878
(MediaTek, Mali), host `ro.vndk.version=34`, waydroid 1.5.1.

---

## For UBports / Ubuntu Touch packaging

### 1. Ship a Waydroid with `find_aidl` — highest impact, lowest effort

Ubuntu Touch 24.04.4 ships **waydroid 1.5.1**, whose `lxc.py` probes for the
graphics allocator over HIDL only. Halium 14 devices publish it over **AIDL**,
so the probe always fails and the device is pushed onto a broken software path.
Upstream added the AIDL probe:

```python
elif find_aidl("android.hardware.graphics.allocator.IAllocator/default"):
    gralloc = "android"
```

**This single change is the fix.** Verified on device: with it, the container
selects the host's hardware EGL driver instead of falling back.

*Needs:* a Waydroid package bump and retest on any Halium 14 device.

---

## For Waydroid upstream

### 2. Publish a `HALIUM_14` vendor channel, or map vndk 34 to an existing one

`get_vendor_type()` computes `HALIUM_14` from `ro.vndk.version=34`, but
`https://ota.waydro.id/vendor/waydroid_arm64/HALIUM_14.json` is a **404**.
`waydroid init` therefore dies at a URL fetch before touching any hardware —
which is the whole origin of "Waydroid does not support Halium 14".

Either publish the channel, map 34 to a published one, or at minimum fail with a
message that says the channel does not exist yet rather than a bare fetch error.

### 3. Backport the composer threadpool fix to `lineage-20`

`hwc_binder_thread` calls `configureRpcThreadpool(1, …)` after
`composer@2.1-service` has already configured and started a 4-thread hwbinder
pool, which is fatal. Fixed on `dev/lineage-23.2`, never backported to
`lineage-20` — the branch the published images are built from.

Patch ready: [`patches/0001-hwcomposer-don-t-shrink-the-binder-threadpool-from-h.patch`](patches/)

### 4. Decide how HALIUM images should carry VNDK 34 graphics libs

Halium 14 vendor blobs link against `android.hardware.graphics.allocator-V2-ndk.so`
and `common-V4-ndk.so`; an Android 13 container has only V1 and V3. They must
land in `/vendor/lib64` — the `sphal` namespace does not search `/system`.

**But shipping them alone is actively harmful** (see item 6). Whatever satisfies
MediaTek's mapper has to land with them.

---

## For Volla / MediaTek

Item 5 is **answered** — recovered from the shipped binary, no vendor
documentation required. An earlier version of this file claimed that no amount
of reverse engineering could substitute for a vendor answer. That was wrong,
and it took about ten minutes to disprove. Item 6 is still open and is where
BSP knowledge would help most.

### 5. ✅ ANSWERED — the mapper reads the directory `/vendor/etc/gralloc`

Original symptom:

```
Abort message: 'Unable to retrieve GPU capabilities. XML file either not found
                or contains syntax errors. Aborting.'
  #03 .../mt6878/android.hardware.graphics.mapper@4.0-impl-mediatek.so
        (ip_support_feature(unsigned int, unsigned int, feature_t)+1168)
  #05   mali_gralloc_select_format(...)
```

Recovered from the binary itself:

```sh
readelf -d mapper.so    # libxml2 is STATICALLY linked -- the parser is not the problem
strings -a mapper.so
  /vendor/etc/gralloc                          <- the only path literal in the file
  Failed to open capability directory:         <- a DIRECTORY, not a single file
  Read capability file from
  Failed to stat file for capability reading:
```

A leaked build path names the component:
`vendor/mediatek/proprietary/hardware/gpu_mali/mali_avalon/r44p1/.../capabilities`.

On the host that directory holds five files — `cam.xml`, `dpu.xml`,
`dpu_aeu.xml`, `gpu.xml`, `vpu.xml`, each `<capabilities version="0.2">`.

**The files are already inside the container, at the wrong path.** The host
vendor partition is rbind-mounted at `/vendor_extra`, so they appear as
`/vendor_extra/etc/gralloc/`. Meanwhile `/vendor` is Waydroid's own vendor
image, which has no `etc/gralloc` at all — verified with
`debugfs -R "ls -l /etc" vendor.img`.

**Fix:** make that directory visible at `/vendor/etc/gralloc` inside the
container. `scripts/add_gralloc_capabilities.py` does it through Waydroid's
vendor overlay.

For upstream the natural home is the bind-mount loop in
`images.py: mount_rootfs()` that already handles `/vendor/lib*/egl`. One
wrinkle: `helpers.mount.bind()` does `mkdir -p` its destination, but the
container's `/vendor` is read-only and — unlike `/vendor/lib64/egl` — the
`gralloc` directory does not already exist in the vendor image to mount onto.
So either the HALIUM vendor image ships an empty `/vendor/etc/gralloc`, or
Waydroid creates it in the overlay upper dir first.

*Status: established statically and cross-checked against host and image
contents; still needs an on-device boot to confirm the abort is gone.*

### 6. Why does `libGLES_mali.so` abort inside `eglInitialize`?

With the VNDK 34 libraries supplied, the Mali DDK loads and executes, then
`surfaceflinger` aborts inside the driver itself:

```
#05 libGLES_mali.so (eglInitialize+1276)
#06 libEGL.so (android::egl_display_t::initialize(int*, int*)+292)
#08 surfaceflinger (SkiaGLRenderEngine::create+72)
```

Already ruled out on my side: `/dev/mali0` **is** bind-mounted into the
container, the AIDL allocator **is** reachable from inside, and the
`android.hardware.graphics.allocator-V2-ndk` / `common-V4-ndk` dependencies are
satisfied (the earlier `dlopen` failure is gone).

**Retest after item 5 first.** `ip_support_feature` is the capability path, and
`libGLES_mali.so` consumes the same feature data, so item 6 may simply be item 5
in a different process. Confirm the mapper stops aborting before building
instrumentation for this.

**Concrete lead, from `readelf -d` on the mapper**: it hard-links
**`libged.so`** (MediaTek Graphics Execution Delegator), **`libgpud.so`** (GPU
daemon) and **`libdmabufheap.so`**. If `libGLES_mali.so` wants the same, the
candidates inside the container are `/dev/ged` and its sysfs/proc interfaces,
and the dma-buf heaps (`/dev/dma_heap/mtk_mm`, `mtk_mm-uncached`, `system`) —
note Android 14 dropped ION in favour of dma-heap. Waydroid also runs its own
property service, so `vendor.mali.*` / `debug.mali.*` / `ro.board.platform` do
not exist inside unless injected.

**How to settle it:** compare the syscall trace of the same library on the host
against inside the container, and look for the first `ENOENT` that differs:

```sh
strace -f -e trace=openat,access,stat,statx,readlink,ioctl <egl program>
```

On Ubuntu Touch there is no SurfaceFlinger on the host side — gralloc is reached
through libhybris from Lomiri, so trace that or the Halium container's allocator
service, not stock Android. For init-started Android services use Android's own
`setprop wrap.<service> "strace -f -o /data/local/tmp/x.txt"` rather than
`LD_PRELOAD`. `ltrace` is useless against Bionic; Frida is the better tool for
hooking `openat` / `__system_property_get` / `ioctl` on aarch64.

**Do not simply patch out the abort.** If the capability bits never load,
`mali_gralloc_select_format` picks AFBC/compression flags from uninitialised
state — silent buffer corruption or a harder fault later. Patch it only as a
probe to see how much further it gets, never as a fix.

**What would still resolve it fastest:** what else the Mali DDK on mt6878
requires at `eglInitialize` when running inside a container rather than as the
host's own compositor.

### 7. Related, and a fair ask

Ubuntu Touch is shipped on Volla hardware, and working Android app support is
one of the most requested features for that platform. Item 5 turned out to be
recoverable from the shipped binaries in minutes, so the remaining ask is
narrower than it was: confirmation of the GED / dma-heap interfaces the Mali
driver expects at initialisation, or a pointer to the right section of the
MediaTek documentation, would likely finish item 6.

---

## For anyone with a capable build machine

My build hardware was inadequate for anything larger than a vendor image, so
these were never attempted.

### 8. Build and test an Android 14 based Waydroid system image

The proper base for a HALIUM_14 image. Note the real obstacle is **not**
compute: **Waydroid has no `lineage-21` branch at all.** Its trees jump from
`lineage-20` (Android 13) to `dev/lineage-23.2` (Android 16); Android 14 and 15
were skipped. An Android 14 base means porting `android_device_waydroid_waydroid`,
`android_vendor_waydroid`, `android_hardware_waydroid`,
`android_frameworks_waydroid` and `android_vendor_waydroid_init` to a version
nobody maintains.

**Probably better:** test `dev/lineage-23.2` (Android 16) instead. It is actively
maintained and already carries `android_prebuilts_vndk_v34`, which exists
precisely to serve VNDK 34 vendor partitions like Halium 14's.

### 9. Retest the whole chain on current Waydroid master

Everything here was measured against 1.5.1 with `find_aidl` hand-backported.
A clean run on current master — ideally on more than one Halium 14 device —
would confirm the finding generalises beyond one handset.

### 10. Test on non-MediaTek Halium 14 hardware

Items 5 and 6 are MediaTek-specific. A Halium 14 device with a Qualcomm or
different Mali stack may well reach hardware rendering with only item 1 applied.
That would be a strong result and would narrow the remaining problem to MediaTek.
