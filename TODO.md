# Open items

The project is blocked on item 8. Items 1-7 are prerequisites; none of them
produces working hardware-accelerated Waydroid on its own.

Grouped by who is best placed to do them. Technical background for every item is
in [CONCLUSIONS.md](CONCLUSIONS.md).

Reference device: Volla Phone Plinius (ansuz), Ubuntu Touch 24.04.4, SoC mt6878
(MediaTek, Mali), host `ro.vndk.version=34`, waydroid 1.5.1.

---

## For UBports / Ubuntu Touch packaging

### 1. A Waydroid package new enough to include `find_aidl` — highest impact

Ubuntu Touch 24.04.4 ships **waydroid 1.5.1**, whose `lxc.py` probes for the
graphics allocator over HIDL only. Halium 14 devices publish it over **AIDL**,
so the probe always fails and the device is pushed onto a broken software path.
Upstream added the AIDL probe:

```python
elif find_aidl("android.hardware.graphics.allocator.IAllocator/default"):
    gralloc = "android"
```

**This single change fixes the EGL-selection failure** — the one producing
`couldn't find an OpenGL ES implementation`. Verified on device: the container
then selects the host's real EGL driver instead of falling back. It does **not**
deliver working hardware rendering; three further blockers follow, and the last
may need a newer system image (item 8). This is a prerequisite, not the fix.

The change is [`9bd8db0` "Detect AIDL gralloc5"](https://github.com/waydroid/waydroid/commit/9bd8db09d5d317e58d423ff7448399883d071b91)
by Jami Kettunen, already in Waydroid upstream.

*Needs:* a package bump and retest on Halium 14 hardware. I have no view on how
much work that is on the UBports side; the device-side evidence that it is
sufficient for EGL selection is in CONCLUSIONS.md §3.

---

## For Waydroid upstream

### 2. Publish a `HALIUM_14` vendor channel, or map vndk 34 to an existing one

`get_vendor_type()` computes `HALIUM_14` from `ro.vndk.version=34`, but
`https://ota.waydro.id/vendor/waydroid_arm64/HALIUM_14.json` is a **404**.
`waydroid init` therefore dies at a URL fetch before touching any hardware —
which is where most reports of Halium 14 failure start.

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

Both items below turned out to be answerable from the shipped binaries. An
earlier version of this file said reverse engineering could not substitute for a
vendor answer; that was wrong, and the record of it is left in place.

**Solving them did not unblock hardware rendering.** They were real and they are
fixed on device, and the failure simply moved to the blocker in
[CONCLUSIONS.md](CONCLUSIONS.md) §4a — which is not a missing file or property.
A BSP answer would still be valuable for whoever tackles that, but neither item
below is on the critical path any more.

### 5. Solved (did not unblock) — the mapper reads `/vendor/etc/gralloc`

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
container. `scripts/expose_mtk_gpu_configs.py` does it through Waydroid's
vendor overlay.

For upstream the natural home is the bind-mount loop in
`images.py: mount_rootfs()` that already handles `/vendor/lib*/egl`. One
wrinkle: `helpers.mount.bind()` does `mkdir -p` its destination, but the
container's `/vendor` is read-only and — unlike `/vendor/lib64/egl` — the
`gralloc` directory does not already exist in the vendor image to mount onto.
So either the HALIUM vendor image ships an empty `/vendor/etc/gralloc`, or
Waydroid creates it in the overlay upper dir first.

*Status: **confirmed on device.** With the directory exposed, the
`Unable to retrieve GPU capabilities` abort drops to zero occurrences.*

### 6. Solved (did not unblock) — the Mali EGL winsys reads its config table from properties

Arm's Mali EGL winsys builds its EGLConfig list from Android system properties.
Recovered from `libGLES_mali.so`: a table of thunks, each loading a property
name and calling a shared getter, with symbols like
`vendor::arm::egl::properties::r8_g8_b8_a8_32bit_fixed_hal_format()` and strings
like `ro.vendor.arm.egl.configs.nv12.recordable`.

This host defines **42** such properties. The container had **none** -- they are
absent from Waydroid's vendor image and `lxc.py` never forwards them. With no
properties the config lists come out inconsistent, `malloc(count * 56)` fails,
and the DDK aborts with `failed to allocate winsys_configs`.

Forwarding all 42 via `waydroid.cfg`'s `[properties]` section
(`scripts/forward_arm_egl_configs.py`) **eliminates this particular abort**.
Confirmed on device: EGL initialises and the crash loop stops. **This is not
working hardware rendering** — the failure moves to the buffer-descriptor
mismatch of §4a.

The blocker after this one is not a missing anything -- see
[CONCLUSIONS.md](CONCLUSIONS.md) §4a.

### 6a. Historical — how item 6 presented, and the dead ends

**Everything in this subsection is superseded.** Item 6 was solved by forwarding
the EGL config properties, above. It is kept only so nobody repeats the
eliminated hypotheses; the Frida probes and syscall traces described below are no
longer worth doing.

Why does `libGLES_mali.so` abort inside `eglInitialize`?

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

**Item 5 is fixed and this still happens — they are separate.** Tested on device
with the capability XMLs present: the `Unable to retrieve GPU capabilities`
abort is gone (0 occurrences) and `libGLES_mali.so` still aborts inside
`eglInitialize`. The call site did move, from `SkiaGLRenderEngine::create` to
`hwcomposer.waydroid.so`'s `egl_loop`, so it gets further than before.

### Hypotheses tested and eliminated

Each of these was tried on device. **All are dead.** Recorded so nobody repeats
them — the negatives are the main product of this round.

| Hypothesis | How it died |
| --- | --- |
| Item 6 is item 5 in another process | Item 5 fixed and confirmed; item 6 aborts at the identical address |
| Missing `/vendor/etc/mali_platform.config` | Supplied to the container; abort unchanged at `eglInitialize+1276` |
| Missing `/vendor/etc/meow.cfg` | Supplied; MEOW *still* logs `cfg path: na`, so that message was never about the file |
| `libMEOW : plugin: [failed]` is fatal | Those plugins are game-optimisation extras (GIFT, AIVRS, trace, qt) reading `/data/performance/*.ini` |
| Missing GED device nodes | `/dev/ged*` does not exist **on the host either**; only `/proc/ged` |
| Missing / different dma-buf heaps | Heap lists are identical host vs container, all 12 of them |
| `OSU_PROTECTED_MEMORY_HEAP_NAME` unsatisfiable | `mtk_svp_page-uncached` is absent on **both** sides, and the host works regardless |
| `/dev/mali0` unreachable in the container | Present, mode 666, same major/minor as the host |

**What that leaves.** The container's *visible* environment matches the host's:
same device node, same heaps, same configs, same driver binary. Whatever differs
is therefore **not observable by listing files**.

### Where it actually aborts — recovered by disassembly

The crash gives `pc 0x9aa1d4` inside `libGLES_mali.so`. Disassembling around it
(the binary is stripped, so work from the nearest exported symbol,
`egl_winsys_get_implementation`):

```
9aa1b4:  bl  <local>              variadic call: the assert formatter
9aa1b8:  bl  9aa1d0               noreturn wrapper
9aa1bc:  udf #0                   unreachable
9aa1d0:  str x30, [sp,#-16]!
9aa1d4:  bl  abort@plt            <- the abort
```

The formatter loads its arguments as string pointers via `adrp/add`; reading
them out of the file gives the assert:

```
function : void get_configs(egl_winsys_display *, const egl_config_attribute **,
                            EGLint *, const egl_winsys_config **, EGLint *)
message  : "failed to allocate winsys_configs"
```

**So the DDK is enumerating EGL configs from the window system and ending up
with a config list it cannot allocate** — consistent with the window system
offering zero usable configs. That is a much narrower target than
"`eglInitialize` aborts".

It also joins up with the other symptom seen on the software path,
`output buffer not gpu writeable`: both are the same negotiation failing, from
opposite ends. MediaTek's gralloc decides which formats/usages each IP block
supports (per the capability XML), and Waydroid's window system —
`hwcomposer.waydroid.so` plus the gbm/gralloc path — is asking for something
outside that set, or advertising nothing the Mali winsys accepts.

### The failing instruction, and what it implies

Following the single `CBZ` that reaches the abort stub gives the exact failure:

```
9a8fc0:  stp   xzr, xzr, [sp,#112]   zero-init config list A
9a8fc8:  bl    a18d30                populate list A   (32-byte elements)
9a8fdc:  sub   x10, x9, x8           countA = (end-begin)/32
9a8fd4:  stp   xzr, xzr, [sp,#88]    zero-init config list B
9a8ff4:  bl    a19310                populate list B   (40-byte elements)
                                     countB = (end-begin)/40
9a9020:  mov   w8, #0x38             56 = sizeof(winsys_config)
9a9024:  umull x0, w9, w8            (countA + countB) * 56
9a902c:  bl    malloc@plt
9a9034:  cbz   x0, <abort>           malloc returned NULL
```

**It is a `malloc()` failure, not "no configs found".** That distinction
matters, and it rules out the obvious reading of the message.

An inference, flagged as such: the container has **no memory cgroup limit**
(checked) and the host had ~9 GB free at the time, so a genuine out-of-memory
for a config array is implausible. Android's allocator returns NULL for absurd
sizes rather than attempting them. That points at **`count` being garbage** —
i.e. the two list-population calls at `0xa18d30` and `0xa19310` leave the lists
*inconsistent* (end < begin, or uninitialised), rather than merely empty. An
empty-but-valid list would give `count = 0`, and `malloc(0)` does not return
NULL on Bionic.

So the defect is upstream of the allocation: whatever enumerates configs from
the window system is failing without reporting it, and `get_configs` then trips
over the wreckage.

**Next step is dynamic and now very targeted.** Static analysis cannot supply
runtime values; a Frida hook can, in three probes:

1. Hook `malloc` inside `surfaceflinger` and log the size at the call from
   `libGLES_mali.so+0x9a902c` — if it is absurd, the inference above is
   confirmed outright.
2. Hook the two population functions, `libGLES_mali.so+0xa18d30` and
   `+0xa19310`, and log the list pointers before and after.
3. Compare all three against the host, where the same DDK builds a working list.

`strace` will not show this. Nothing is missing from the filesystem — the
failure is in values returned across an in-process call.

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

### 7. Related

Items 5 and 6 were both recoverable from the shipped binaries, so there is no
longer a MediaTek question on the critical path. If MediaTek or Volla can confirm
how `BufferDescriptorInfo` is expected to be encoded for this mapper build, that
would settle §4a directly — and would say whether a newer system image is
actually required or whether the mis-packing is on Waydroid's side.

---

## For anyone with a capable build machine

My build hardware was inadequate for anything larger than a vendor image, so
these were never attempted.

### 8. Test a system image of Android 14 or newer — the leading hypothesis

This is now the **critical path**, though the reasoning behind it is a
hypothesis rather than a proof — see [CONCLUSIONS.md](CONCLUSIONS.md) §4a. What
was measured is that an Android 13 client and MediaTek's `graphics.common-V4`
mapper disagree on the buffer descriptor's shape, so `GraphicBufferAllocator`
fails and SurfaceFlinger aborts. The leading explanation is a **Treble version
inversion** — Treble supports a system image newer than the vendor partition,
not the reverse. Testing it needs the image; nobody has built one.

Note the alternative that was not ruled out: the mis-packing may originate in
Waydroid's own gralloc client path rather than in the version pairing, in which
case no new image is needed. Whoever tests this should check that first — it is
much cheaper.

**Test `dev/lineage-23.2` (Android 16) first**, not Android 14:

- it is actively maintained upstream, whereas **Waydroid has no `lineage-21`
  branch at all** -- its trees jump from `lineage-20` to `dev/lineage-23.2`, so
  an Android 14 base means porting five trees to a version nobody maintains;
- it already carries `android_prebuilts_vndk_v34`, which exists precisely to
  serve VNDK 34 vendor partitions like Halium 14's;
- and it puts the system *newer* than the vendor, which is the direction Treble
  actually supports.

Everything else in this repository -- the `find_aidl` fix, the gralloc
capability directory, the 42 EGL config properties, the composer backport -- is
a prerequisite such an image would still need. None of it is wasted; all of it
was verified on device.

### 9. Retest the whole chain on current Waydroid master

Everything here was measured against 1.5.1 with `find_aidl` hand-backported.
A clean run on current master — ideally on more than one Halium 14 device —
would confirm the finding generalises beyond one handset.

### 10. Test on non-MediaTek Halium 14 hardware

Items 5 and 6 are MediaTek-specific, but the §4a blocker is very likely not —
any Android 13 system image on any Android 14 vendor partition should hit the
same descriptor mismatch. A Qualcomm Halium 14 device would clear items 5 and 6
for free and then, on this reasoning, stop in the same place. Testing one is
still worth doing precisely because it would confirm or refute that; do not
expect hardware rendering from it.
