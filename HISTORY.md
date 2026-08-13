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

**Fourth position: "the MediaTek questions need vendor documentation."** With
the hardware path selected, two blockers remained: the gralloc mapper aborting
on a missing GPU-capabilities XML, and `libGLES_mali.so` aborting inside
`eglInitialize`. I wrote them up as items only Volla or MediaTek could answer,
and put this in TODO.md:

> no amount of build hardware or reverse engineering on my side substitutes for
> the answer

That was wrong, and it was wrong in a way I should have caught. This project's
own first working principle is *attempt the thing nobody has tried; do not
answer "the community says this is impossible"*. I had written a blocker off
without spending ten minutes testing whether it was one.

The correction came from outside — a suggestion to attack the proprietary
binaries directly, with `strings`, `strace`, an `LD_PRELOAD` shim and a
disassembler. Two of the specific tips mattered: look for **format strings** as
well as literals, because MediaTek builds paths from properties and a path built
from an unset property collapses to garbage with no `openat` to trace; and treat
the abort's *"not found **or** syntax errors"* as two branches, because the XML
parser being unresolvable in the `sphal` namespace was as plausible as the file
being absent.

In the event neither subtlety was needed, and no disassembler was opened:

```sh
readelf -d mapper.so     # libxml2 is STATICALLY linked -> parser hypothesis dead
strings -a mapper.so
  /vendor/etc/gralloc                    # the only path literal in the binary
  Failed to open capability directory:   # a DIRECTORY, not a single file
```

The host had `/vendor/etc/gralloc/{cam,dpu,dpu_aeu,gpu,vpu}.xml`; Waydroid's
vendor image had no `etc/gralloc` at all; and the host copy was already inside
the container at `/vendor_extra/etc/gralloc`, because the host vendor partition
is rbind-mounted there. The mapper was scanning a directory that did not exist.
Elapsed: about ten minutes, entirely static, on a binary that had been sitting
on the device the whole time.

The same `readelf` output produced the first real lead for the remaining
blocker: the mapper hard-links `libged.so`, `libgpud.so` and `libdmabufheap.so`,
pointing at MediaTek's GED interfaces and dma-buf heaps rather than ION.

**Fifth position: "item 6 is the same kind of missing file."** It was a
reasonable bet — the technique had just worked, and a second pass over
`libGLES_meow.so`, the `libMEOW_*` plugins and the 46 MB Mali DDK turned up two
more configs absent from Waydroid's vendor image: `/vendor/etc/mali_platform.config`
(with real content, including a dma-buf heap name) and `/vendor/etc/meow.cfg`.

Supplying both changed nothing. `libGLES_mali.so` aborted at the identical
address. Worse for the theory, `libMEOW` went on logging `cfg path: na` with the
file plainly present, which means that message was never about the file at all —
a reminder that a log line naming a thing is not evidence about that thing.

Checking the environment finished the idea off: `/dev/ged*` does not exist on
the **host** either, the dma-buf heap lists are identical on both sides, the
heap named in `mali_platform.config` is absent from both, and `/dev/mali0` is
present in the container with the same major/minor as the host. The container's
visible environment matches the host's in every respect inspected.

So item 6 is not a missing file, and file inspection cannot answer it. Six
hypotheses died in that round and the eliminations are recorded in TODO.md,
which is the more useful output than the one confirmation would have been.

**Sixth step: disassemble rather than guess.** Having run out of files to blame,
the remaining move was to read the code at the address the crash reports. Two
things nearly stopped that, both silent:

- The system `objdump` has **no aarch64 support** on this machine. It did not
  error — it printed a file header and no instructions, which reads exactly like
  "nothing here". `objdump -i | grep aarch64` returns zero;
  `aarch64-linux-gnu-objdump` was already installed.
- The library is stripped, so addresses must be worked out relative to the
  nearest exported symbol (here `egl_winsys_get_implementation`).

Past that, the abort path is four instructions and its assert formatter loads
its arguments as string pointers, which can simply be read out of the file:

```
function : void get_configs(egl_winsys_display *, const egl_config_attribute **,
                            EGLint *, const egl_winsys_config **, EGLint *)
message  : "failed to allocate winsys_configs"
```

That turned "aborts somewhere in `eglInitialize`" into "fails enumerating EGL
configs from the window system", and tied it to the `output buffer not gpu
writeable` symptom seen from the other direction on the software path. Both are
the same format negotiation between MediaTek's gralloc and Waydroid's window
system, failing from opposite ends.

No disassembler UI, no Frida, no strace — just `objdump` with the right target
and a hexdump of four string pointers.

Following the one `CBZ` that reaches that abort narrowed it further, and
overturned the obvious reading of the message: the failure is a plain
`malloc(count * 56)` returning NULL, **not** "no configs found". With no
cgroup memory limit on the container and gigabytes free on the host, the
count is almost certainly garbage — meaning the two list-population calls
leave their lists inconsistent rather than empty, since an empty list would
give `malloc(0)`, which does not return NULL on Bionic.

That is where static analysis stops. It can say which instruction fails and
what that implies; it cannot supply the runtime value that would settle it.


**Seventh position, and the last one: "it's another missing input."** It was —
twice more. Disassembling the config-population functions showed they are a
table of thunks, each passing a *property name* to a getter, with symbols like
`vendor::arm::egl::properties::r8_g8_b8_a8_32bit_fixed_hal_format()`. The host
defines 42 `ro.vendor.arm.egl.configs.*` properties; the container had none, and
`lxc.py` never forwards them. Forwarding all 42 through `waydroid.cfg` killed
the abort. EGL initialised, `system_server` and both zygotes stayed up, and the
crash loop stopped.

Then the failure changed character, and that is where the investigation ends.
SurfaceFlinger asks gralloc for `usage 0x300`; MediaTek's mapper decodes
`0x7f00200000` and reports `Invalid descriptorInfo sizes`. The tempting
explanation — that `BufferUsage` changed between AIDL V3 and V4 — was checked
and is **false**: the enum is byte-identical in this tree. What is left is a
client/mapper disagreement about the descriptor itself, between an Android 13
system and a mapper built against `graphics.common-V4`.

That is a **Treble version inversion**: system older than vendor, which Treble
does not support in that direction. Copied libraries let the vendor blobs load;
they cannot make Android 13's own code encode V4. So the last blocker is not a
missing file, a missing property or a missing node — it is the pairing itself,
and it needs a system image of Android 14 or newer.

Six positions were held and abandoned along the way. The one that cost most was
not any of the wrong diagnoses; it was declaring two items out of reach without
testing them. Both fell to tools that had been installed the whole time.

## Positions held and abandoned

| Held | Why it was wrong |
| --- | --- |
| `angle` is a bug in init | It is the intended generic path; its drivers ship in the vendor image |
| The EGL bind mount is the bug | It is correct and load-bearing — it is how Halium devices get hardware GL |
| The composer threadpool abort must be fixed | It never occurs on the clean path; it was an artifact of my own hack force-loading the Mali driver |
| Booting needs an Android 14 system image | It does not |
| A VNDK 33/34 ABI mismatch is the cause | The container is coherently Android 13; a real split exists but only on the hardware path |
| The two prebuilt module names were unused | AIDL module names are generated; the tree already defines V2/V4 as its unfrozen `current` versions |
| The MediaTek blockers need vendor documentation | Item 5 fell to `readelf -d` and `strings` in about ten minutes, on a binary already on the device |
| Item 6 is another missing config file | Both candidate configs supplied; abort unchanged. Environment matches the host in every respect inspected |
| The last blocker is something host-side | It is a Treble version inversion: Android 13 system against an Android 14 vendor. Needs a newer system image |

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
- **Declaring a blocker out of reach without testing it.** The gralloc XML
  question was written up as needing vendor documentation and published that
  way. It needed one `strings` invocation. The cost was not large in hours, but
  had nobody pushed back it would have shipped as a permanent "someone else's
  problem" — the single worst failure mode in this whole log, because it stops
  the investigation rather than misdirecting it.

## What survived from those notes

The operational lessons are consolidated into CONCLUSIONS.md §8 (traps). The
build procedure is in the repository README. The only thing lost is a set of
intermediate conclusions that were superseded, which is the point.
