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

## For Volla / MediaTek — I cannot do these

These two need vendor documentation or source access that is not public. They
are the only things standing between this device and **hardware-accelerated**
Android, and no amount of build hardware or reverse engineering on my side
substitutes for the answer.

### 5. Which GPU-capabilities XML does the gralloc mapper require, and where?

`android.hardware.graphics.mapper@4.0-impl-mediatek.so` aborts during buffer
format selection:

```
Abort message: 'Unable to retrieve GPU capabilities. XML file either not found
                or contains syntax errors. Aborting.'
  #03 .../mt6878/android.hardware.graphics.mapper@4.0-impl-mediatek.so
        (ip_support_feature(unsigned int, unsigned int, feature_t)+1168)
  #05   mali_gralloc_select_format(...)
  #07   arm::mapper::hidl::is_supported(...)
```

The mapper loads and runs correctly on the host, so the file exists somewhere on
the device — but inside the Waydroid container the real vendor partition is
mounted at `/vendor_extra`, not `/vendor`, and the mapper evidently does not find
it there.

**What would resolve it:** the path (or search order) this MediaTek build expects
for its GPU capabilities XML, and whether that path is configurable. A one-line
answer from someone with the vendor source closes this immediately.

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

**What would resolve it:** what else the Mali DDK on mt6878 requires at
`eglInitialize` — additional device nodes, MediaTek `ged`/`ion` interfaces,
properties, or a sysfs path — when running inside a container rather than as the
host's own SurfaceFlinger.

### 7. Related, and a fair ask

Ubuntu Touch is shipped on Volla hardware. Working Android app support is one of
the most requested features for that platform, and it is currently blocked on
two questions that are trivial for whoever holds the BSP and intractable for
everyone else. Even partial answers to items 5 and 6 — or pointing at the right
section of the MediaTek documentation — would unblock the community.

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
