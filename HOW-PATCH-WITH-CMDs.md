# Cracking the Wasteland (C64) Ranger Data — The Commands

This is the **command-by-command walkthrough** of how we located the party, beat the
anti-tamper checksum, and built a self-verifying patcher — the **exact commands** (Python
probes and VICE monitor sessions) so you can reproduce every step yourself.

| File | What it is |
|------|------------|
| `disk1-orig.d64`    | a Wasteland disk-1 **user disk** (generated from the master), party at starting stats |
| `disk1-cracked.d64` | the finished result (all four rangers maxed, valid checksum) |

Both are 35-track D64s, **175,531 bytes** (174,848 bytes of sector data + a 683-byte
error table). Every Python block below is self-contained — paste it into a
`python3 - <<'PY' … PY` heredoc, or drop it in a file. VICE monitor blocks assume
`x64sc` with the monitor open (`Alt+M`, or launch with `-moncommands`).

Throughout, the four rangers are **Hell Razor, Snake Vargas, Angela Deth, Thrasher**.

> **Quick reproduction.** If you only want to confirm the result, jump to
> [Part 6](#part-6--the-self-verifying-patcher) and run `wl_patch.py inspect`.
> The parts below retrace how we *got* there.

---

## Part 0 — Setup

At the start of the investigation we have exactly **one** file: `disk1-orig.d64`, a
pristine Wasteland disk-1 **user disk** — the playable copy the game generates from the
write-protected master, and where it actually stores the party. (`disk1-cracked.d64` is
the *end product* — the maxed disk we'll eventually produce — so it doesn't exist yet and
plays no part until [Part 6](#part-6--the-self-verifying-patcher).)
Establish the basic facts of the disk we're attacking:

```bash
cd /path/to/Wasteland_c64_patching
ls -l disk1-orig.d64
# 175531 bytes
```

```bash
python3 - <<'PY'
disk = open("disk1-orig.d64","rb").read()
# 35-track 1541 geometry: 21 sectors/track on 1-17, 19 on 18-24, 18 on 25-30, 17 on 31-35
sectors = 17*21 + 7*19 + 6*18 + 5*17        # = 683 sectors
print("size        :", len(disk), "bytes")
print("sectors     :", sectors)
print("sector data :", sectors*256, "bytes")
print("error table :", len(disk) - sectors*256, "bytes (1 code per sector)")
PY
```

```
size        : 175531 bytes
sectors     : 683
sector data : 174848 bytes
error table : 683 bytes (1 code per sector)
```

A `.d64` is a **fixed-size container**: a 35-track 1541 image is *always* 174,848 bytes of
sector data plus a 683-byte error table = **175,531 bytes**, no matter what's stored on it.
The format has a fixed number of tracks and sectors, so there's no "make the file
bigger/smaller" operation — every edit later in this document **overwrites bytes in place**
and the file length never changes.

That's all we know going in: one 175,531-byte image, a custom on-disk format, and four
rangers hidden somewhere inside it. Everything else we have to dig out.

---

## Part 1 — Where are the characters?

### 1a. The naive ASCII search fails

```bash
python3 -c "d=open('disk1-orig.d64','rb').read(); print('found' if b'RAZOR' in d else 'NOT in plain ASCII')"
```

```
NOT in plain ASCII
```

Nothing. Not in plain ASCII, not with the high bit set, not at a constant offset. The
roster is stored some other way.

### 1b. …but *some* text on the disk is plaintext

Scan for printable runs and you find the **enemy** name table sitting in the clear:

```bash
python3 - <<'PY'
import re
disk = open("disk1-orig.d64","rb").read()
for m in re.finditer(rb"[ -~]{5,}", disk):
    s = m.group().decode("latin1")
    if any(w in s for w in ["Drool","Gecko","Skink","Cougar","Scav","Glowviper"]):
        print("0x%06X: %r" % (m.start(), s))
PY
```

```
0x00D119: 'Desert Scav'
0x00DB2E: 'Drool'
0x00DB38: 'Gecko'
0x00DB42: 'Skink'
0x00DB4C: 'Shell Cougar'
0x00DB66: 'Glowviper'
```

So the game *does* store readable strings — just not the player characters. Strong hint
the roster is stored differently (encrypted) from the string tables.

### 1c. The directory is a dead end

A standard CBM-DOS directory lives on track 18 (sector data starts at byte
`(18-1)*21*256`… but the layout is non-linear; the practical point is that a normal D64
directory parse returns nothing useful here). Wasteland uses its own on-disk format, so
the usual BAM/directory machinery doesn't apply. Don't waste time here — move to entropy.

### 1d. Entropy map points at the encrypted data

A spike only means something *relative to the baseline*, so map the **whole** disk, not
just the peaks. Shannon entropy in 4 KB chunks, every chunk printed with a bar:

```bash
python3 - <<'PY'
import math
from collections import Counter
disk = open("disk1-orig.d64","rb").read()
def H(b):
    if not b: return 0.0
    c = Counter(b); n = len(b)
    return -sum((v/n)*math.log2(v/n) for v in c.values())
for off in range(0, len(disk), 4096):
    h = H(disk[off:off+4096])
    mark = " <-- PACKED/ENCRYPTED ISLAND" if h > 7.5 else ""
    print("0x%06X |%-32s| %.2f%s" % (off, "#"*int(round(h*4)), h, mark))
PY
```

```
0x000000 |#####                           | 1.15
0x001000 |                                | 0.04   <-- empty / padding
0x002000 |                                | 0.04
0x003000 |##                              | 0.60
0x004000 |#########################       | 6.17
0x005000 |#########################       | 6.17
0x006000 |####################            | 4.89
0x007000 |                                | 0.04
0x008000 |                                | 0.04
0x009000 |###################             | 4.77
0x00A000 |######################          | 5.46
0x00B000 |##################              | 4.57
   …  (typical game data: tables, text, code — mostly 4.5–7.0)  …
0x011000 |###########################     | 6.84
0x014000 |########################        | 5.96
0x016000 |                                | -0.00  <-- all-zero region
0x019000 |#######################         | 5.87
0x01A000 |############################### | 7.64   <-- PACKED/ENCRYPTED ISLAND
0x01B000 |############################### | 7.86   <-- PACKED/ENCRYPTED ISLAND
0x01C000 |################################| 7.88   <-- PACKED/ENCRYPTED ISLAND
0x01D000 |############################### | 7.86   <-- PACKED/ENCRYPTED ISLAND
0x01E000 |#############################   | 7.15
   …  (rest of disk: 6.3–7.1)  …
0x029000 |#######################         | 5.84
0x02A000 |#######################         | 5.68
```

Now the spike *means* something. Quantify the contrast across all 43 chunks:

```
chunks=43  min=0.00  median=6.17  mean=5.15  max=7.88

entropy distribution (0.5-bit buckets):
  0.0-0.5 :  5 chunks  #####     <- empty / sparse padding
  0.5-2.5 :  4 chunks  ####
  4.5-7.0 : 27 chunks  ...........................   <- the "normal disk" baseline
  7.0-7.5 :  3 chunks  ###
  7.5-8.0 :  4 chunks  ####      <- the island at 0x1A000-0x1D000
```

**Baseline vs. spike:** the bulk of the disk (game tables, text, 6502 code) sits at a
**median 6.17 bits/byte**, never breaking ~7.1. Four contiguous 4 KB chunks at
`0x1A000–0x1D000` jump to **7.64–7.88** — `1.5–1.7 bits/byte above the median`, right up
against the 8.0 ceiling. That's the signature of compressed/encrypted data: no byte value
dominates, so no chunk of plain code or text ever looks like this. (The near-zero chunks
at `0x1000`, `0x7000`, `0x16000` are the opposite extreme — empty/padding sectors.)

#### The catch: that 4 KB spike is *not* the party

The big island is the **packed main binary**. The party records are only **eight
256-byte sectors**, and at 4 KB resolution they're averaged together with the near-empty
padding around them — which is why `0x29000`/`0x2A000` read a tame **5.8**, *below* the
median. To see the party you have to drop to **one-sector (256-byte)** resolution:

```bash
python3 - <<'PY'
import math
from collections import Counter
disk = open("disk1-orig.d64","rb").read()
def H(b):
    if not b: return 0.0
    c = Counter(b); n = len(b)
    return -sum((v/n)*math.log2(v/n) for v in c.values())
party = {0x29a00,0x29b00,0x29c00,0x2a000,0x2a100,0x2a200,0x2a600,0x2a700}
for off in range(0x29800, 0x2a800, 0x100):
    h = H(disk[off:off+256])
    print("  0x%06X  H=%.2f%s" % (off, h, "  <-- PARTY SECTOR" if off in party else ""))
PY
```

```
  0x029800  H=5.29
  0x029900  H=3.01
  0x029A00  H=7.00  <-- PARTY SECTOR
  0x029B00  H=7.06  <-- PARTY SECTOR
  0x029C00  H=7.13  <-- PARTY SECTOR
  0x029D00  H=0.34                       <- near-empty padding between records
  0x029E00  H=0.50
  0x029F00  H=0.41
  0x02A000  H=7.00  <-- PARTY SECTOR
  0x02A100  H=7.07  <-- PARTY SECTOR
  0x02A200  H=7.01  <-- PARTY SECTOR
  0x02A300  H=2.48
  0x02A400  H=1.59
  0x02A500  H=6.01
  0x02A600  H=7.00  <-- PARTY SECTOR
  0x02A700  H=7.10  <-- PARTY SECTOR
```

At sector resolution the eight encrypted records pop out cleanly: **each ~7.0–7.13,
sitting next to padding sectors at 0.3–0.5**. Averaged over the whole disk the contrast is
stark — `mean 256-byte entropy of the 8 party sectors = 7.05` vs. `4.47 for the rest of
the disk`. The party is a cluster of tiny high-entropy islands in a low-entropy sea, which
is exactly what the known-plaintext slide lands on next.

### 1e. The known-plaintext XOR slide — this is the crack

We *know* the plaintext (the names). That's a textbook **known-plaintext attack**. Model
the keystream as `key[j] = K XOR ((j*slope) & 0xFF)` and brute-force `K` and `slope` over
the whole disk, looking for a position where the recovered key is self-consistent across
every byte of a name:

```bash
python3 - <<'PY'
disk = open("disk1-orig.d64","rb").read()

def slide(name, slope):
    nb = name.encode()
    for p in range(len(disk) - len(nb)):
        k = None
        for j, ch in enumerate(nb):
            t = (disk[p+j] ^ ch ^ ((j*slope) & 0xFF)) & 0xFF
            if k is None: k = t
            elif t != k: break          # inconsistent -> not here
        else:
            yield p, k                   # all bytes agreed -> hit

# brute force the slope for one name, then list every name at the winning slope
import itertools
for slope in range(256):
    hits = list(slide("HELL RAZOR", slope))
    if hits:
        print("slope 0x%02X -> %d hit(s)" % (slope, len(hits)))
print("---")
for nm in ["THRASHER","HELL RAZOR","ANGELA DETH","SNAKE VARGAS"]:
    p, k = next(slide(nm, 0x02))
    print("  %-13s offset=0x%05X  seed=0x%02X" % (nm, p, k))
PY
```

```
slope 0x02 -> 1 hit(s)
---
  THRASHER      offset=0x29B00  seed=0xE8
  HELL RAZOR    offset=0x29C00  seed=0xE8
  ANGELA DETH   offset=0x2A100  seed=0xE8
  SNAKE VARGAS  offset=0x2A700  seed=0xE8
```

The winning slope is **`0x02`**, every name decrypts with the **same seed `0xE8`**, and
the records sit on 256-byte (sector) boundaries. So the cipher is just:

```
plain[i] = cipher[i] XOR seed XOR ((2*i) & 0xFF)
```

> **What we know now, and what we don't.** The slide handed us the seed's *value* —
> `0xE8` — and nothing else. We do **not** yet know **how that number is generated**
> (it turns out to be the party's checksum — Part 4) or **where on the disk it's
> stored** (a plaintext byte at slot-0 offset `0xFF` — Part 5). For everything up to
> Part 5 the seed is just a magic constant we extracted by attacking known plaintext.
> Treat it that way: in the snippets below we hard-code `seed = 0xE8` *because the slide
> told us so*, not because we know its origin.

### 1f. Decrypt one record and confirm the layout

```bash
python3 - <<'PY'
disk = open("disk1-orig.d64","rb").read()
seed = 0xE8
off  = 0x29C00          # HELL RAZOR
enc  = disk[off:off+16]
dec  = bytes((enc[i] ^ (seed ^ ((2*i) & 0xFF))) & 0xFF for i in range(16))
print("encrypted:", enc.hex(" "))
print("decrypted:", dec.hex(" "), "->", dec.split(b'\x00')[0].decode('latin1'))
PY
```

```
encrypted: a0 af a0 a2 c0 b0 a5 bc b7 a8 fc fe f0 f2 e4 e7
decrypted: 48 45 4c 4c 20 52 41 5a 4f 52 00 00 00 00 10 11 -> HELL RAZOR
```

The trailing `10 11` is the start of the attribute block (STR=`0x10`=16, IQ=`0x11`=17).
Cross-referencing the Wasteland data-format docs, each 256-byte record decrypts to this
layout:

| Offset      | Field |
|-------------|-------|
| `0x00–0x0D` | Name (ASCIIz) |
| `0x0E`      | Strength |
| `0x0F`      | IQ |
| `0x10`      | Luck |
| `0x11`      | Speed |
| `0x12`      | Agility |
| `0x13`      | Dexterity |
| `0x14`      | Charisma |
| `0x15–0x17` | Money |
| `0x1B–0x1C` | Max Constitution (little-endian) |
| `0x1D–0x1E` | Current Constitution |
| `0x20`      | Skill points |
| `0x21–0x23` | Experience |
| `0x24`      | Level |
| `0x32–0x4A` | Rank string (ASCIIz) |
| `0x80–0xBB` | Skills (id/level pairs) |
| `0xBD–0xF8` | Carried items (id/ammo pairs) |

Visually, the 256-byte record looks like this (the fields we patched are marked `◀`):

```
 Character record — 256 bytes ($00–$FF)
 ┌──────────────────────────────────────────────────────────────────────────┐
 $00 │ N a m e   ( A S C I I z ,  up to 14 bytes )                            │
 $0E │ STR │ IQ  │ LCK │ SPD │ AGI │ DEX │ CHA │   ◀ the 7 attributes  (→ 99) │
 $15 │ Money (3 bytes)   │ Sex │ Nat │ AC  │                                  │
 $1B │ MAX CON (2, LE) ◀ (→999) │ CUR CON (2, LE) ◀ (→999) │ Wpn ptr │        │
 $20 │ Skill pts ◀ (→255) │ Experience (3) │ Lvl │ Armor ptr │   …            │
 $32 │ Rank string  "Private\0…"                                              │
 $4B │ … misc flags / NPC fields …                                           │
 $80 │ Skills:   id,lvl  id,lvl  id,lvl  …            (2 bytes each)          │
 $BD │ Items:    id,ammo id,ammo …                    (2 bytes each)          │
 $FF │ (byte $FF is NOT summed — see the checksum below)                      │
 └──────────────────────────────────────────────────────────────────────────┘
   encryption applies to the whole record:  cipher[i] = plain[i] XOR (2·i) XOR seed
```

Now dump all four:

```bash
python3 - <<'PY'
disk = open("disk1-orig.d64","rb").read()
SECTORS = [0x2a200,0x29c00,0x2a700,0x2a100,0x29b00,0x29a00,0x2a000,0x2a600]
def xcrypt(block, seed):
    out = bytearray(block)
    for i in range(0xff): out[i] ^= (seed ^ ((2*i)&0xff)) & 0xff
    return bytes(out)
seed = 0xE8                     # the seed we just recovered from the name slide
ATTR = ["STR","IQ","LCK","SPD","AGI","DEX","CHA"]
for s in (1,2,3,4):
    pg = xcrypt(disk[SECTORS[s]:SECTORS[s]+256], seed)
    nm = pg[:14].split(b"\x00")[0].decode("latin1")
    a  = " ".join("%s=%d"%(ATTR[i],pg[0x0e+i]) for i in range(7))
    print("%-13s %s MAXCON=%d CON=%d skill=%d" %
          (nm, a, pg[0x1b]|pg[0x1c]<<8, pg[0x1d]|pg[0x1e]<<8, pg[0x20]))
PY
```

```
HELL RAZOR    STR=16 IQ=17 LCK=16 SPD=13 AGI=15 DEX=13 CHA=12 MAXCON=24 CON=24 skill=1
SNAKE VARGAS  STR=11 IQ=16 LCK=8 SPD=7 AGI=17 DEX=13 CHA=6 MAXCON=34 CON=34 skill=0
ANGELA DETH   STR=14 IQ=16 LCK=7 SPD=10 AGI=10 DEX=11 CHA=4 MAXCON=33 CON=33 skill=0
THRASHER      STR=13 IQ=16 LCK=10 SPD=6 AGI=17 DEX=16 CHA=10 MAXCON=26 CON=22 skill=0
```

We have the characters. (Note Hell Razor's stat fingerprint `10 11 10 0d 0f 0d 0c` —
that's the `hunt` signature we'll use in Part 3.)

---

## Part 2 — The edit that fought back

Maxing looks trivial: decrypt, set attributes to `99` (`0x63`), CON to `999`, skill to
`255`, **re-encrypt with the same seed**, write back.

```bash
python3 - <<'PY'
disk = bytearray(open("disk1-orig.d64","rb").read())
SECTORS = [0x2a200,0x29c00,0x2a700,0x2a100,0x29b00,0x29a00,0x2a000,0x2a600]
def xcrypt(block, seed):
    out = bytearray(block)
    for i in range(0xff): out[i] ^= (seed ^ ((2*i)&0xff)) & 0xff
    return bytes(out)
seed = 0xE8                                  # the slide gave us this value; we don't yet
                                             # know how it's derived or where it's stored
for s in (1,2,3,4):
    pg = bytearray(xcrypt(disk[SECTORS[s]:SECTORS[s]+256], seed))
    for i in range(7): pg[0x0e+i] = 0x63     # attrs = 99
    disk[SECTORS[s]:SECTORS[s]+256] = xcrypt(pg, seed)   # re-encrypt SAME seed
open("test_naive.d64","wb").write(disk)
print("wrote test_naive.d64 (re-encrypted with the OLD seed)")
PY
```

Boot `test_naive.d64` in VICE and the game **refuses**: it loads disk 1, asks for disk 3,
and throws an **I/O error**. Restore the pristine image and it works again — so the edit
is the cause.

**Isolate it:** make the *smallest possible* change — Hell Razor's Strength `16 → 17`,
one byte — and nothing else. **Same failure.** So *any* change to the party block is
detected. There's a checksum, and "ask for disk 3 / I/O error" is the anti-tamper
response. *Why* re-encrypting with the same seed doesn't satisfy it is something we don't
understand yet — that comes later, once we've reversed the checksum.

---

## Part 3 — The reliable workaround: let the game do the math

Before cracking anything: the game itself computes a correct checksum every time it
saves. So poke RAM and trigger a save. **This is one way to edit a character.**

Boot the game in `x64sc` so the party is decrypted into RAM, open the monitor (`Alt+M`),
and find a character by their **stat fingerprint** (Hell Razor's seven stats from 1f):

```
bank ram
hunt 0000 ffff 10 11 10 0d 0f 0d 0c     ; Hell Razor STR..CHA
```

```
  $f50e            <- record found at $F500 (stats begin at $F50E)
```

The in-RAM record is byte-for-byte the on-disk layout. Poke the new values straight in:

```
> f50e 63 63 63 63 63 63 63    ; attributes = 99
> f51b e7 03 e7 03             ; MAXCON + CON = 999  (0x03E7, little-endian)
> f520 ff                      ; skill points = 255
```

Then resume (`x`) and trigger an in-game save by entering/leaving a location. The game
runs **its own** save pipeline — `checksum → seed := checksum → encrypt → write` — so the
bytes that land on disk carry a freshly computed, valid checksum. No tamper trap. You
never touch the crypto yourself.

---

## Part 4 — Reverse-engineering the checksum

The workaround is pragmatic (and boring), but we want the actual routine. The catch: the main game
binary is stored **compressed** on disk, so the checksum code only exists in plaintext
once it's unpacked into RAM. Specifically, the track-35 sectors carry a chunk of 6502 code
(sector 11 maps to `$C800` in memory) that turns out to be a **Huffman-style bit-stream
decompressor** — it pulls bits from a buffer at `$5A00`, walks a code table at `$C8EC`, and
emits the inflated bytes. Read the disk directly and you get packed garbage; the real game
code (and our checksum routine) only exists after the decompressor runs at boot. That means
**dynamic** analysis — catch it while it runs.

### 4a. Catch the routine with a load-watchpoint on an unused byte

Offsets `0xF9–0xFE` of a record are unused by gameplay, so **only** a routine that scans
the whole record would ever read them. Arm a load watchpoint on one of those bytes, then
trigger a save:

```
bank ram
watch load $f5fe
x                       ; resume, then save in-game
```

The monitor stops inside a tight loop around `$1928`. Dump and disassemble it:

```
d 1900 1990
```

The heart of the routine:

```
; --- per-record inner loop ---
1925: LDA #imm        ; A = running checksum  (imm self-modified at $1934)
1927: CLC
1928: ADC ($66),Y     ; A += record[Y]
192A: STY $192E       ; self-modify the operand of the NEXT instruction...
192D: ADC #imm        ; ...so this is effectively  A += Y  (+ carry)
192F: INY
1930: CPY #$FF
1932: BNE $1927       ; loop Y = 0x00 .. 0xFE   (byte 0xFF skipped!)
1934: STA $1926       ; persist running checksum (feeds back into $1925)
; --- outer loop: repeat for 8 record slots, counter compared to #$08 ---
```

Two pieces of self-modifying code: `STY $192E` rewrites the `ADC #imm` operand so each
byte contributes **`record[Y] + Y`** (position-weighted, carry chained); `STA $1926`
persists the running sum across iterations.

### 4b. What region does it cover?

The pointer is set up by a helper at `$1201`, called with the slot counter `0..7` in A:

```
1201: LDY #$00 ; STY $66          ; low byte = 0
1206: CLC ; ADC #$F4 ; STA $67    ; high byte = counter + 0xF4
```

So `$66/$67` points at pages `$F400, $F500, … $FB00`: **8 record slots, `$F400–$FBFF`**,
bytes `0x00–0xFE` of each. (Slot 0 = party metadata, slots 1–4 = the characters, slots
5–7 empty, reserved for the NPCs you meet in the game.)

### 4c. Simulate the algorithm and confirm it against the disk

```bash
python3 - <<'PY'
disk = open("disk1-orig.d64","rb").read()
SECTORS = [0x2a200,0x29c00,0x2a700,0x2a100,0x29b00,0x29a00,0x2a000,0x2a600]
def xcrypt(block, seed):
    out = bytearray(block)
    for i in range(0xff): out[i] ^= (seed ^ ((2*i)&0xff)) & 0xff
    return bytes(out)
def checksum(pages):
    A = 0
    for pg in pages:                       # slots 0..7
        for Y in range(0x00, 0xFF):        # bytes 0x00..0xFE
            s = A + pg[Y]; A = s & 0xFF; c = s >> 8
            A = (A + Y + c) & 0xFF         ; # self-modified ADC #Y, carry chained
    return A
seed  = 0xE8                               # from the name slide (Part 1)
pages = [xcrypt(disk[o:o+256], seed) for o in SECTORS]
print("seed (from slide) : 0x%02X" % seed)
print("our checksum      : 0x%02X" % checksum(pages))
print("match             :", checksum(pages) == seed)
PY
```

```
seed (from slide) : 0xE8
our checksum      : 0xE8
match             : True
```

### 4d. The twist: the checksum *is* the encryption seed

Something had been nagging at us the whole time. Every time the game saved, the encryption
seed was **different**. The first dump gave `0xE8`. Save again — `0x89`. Again — `0xB1`,
then `0x38`, then `0xF3`. It looked random, and a random seed should have been impossible
to attack… yet the name-slide cracked every single save. It was being computed from
something. But what?

Then we set a breakpoint at the very end of the checksum routine (`$1940`) and read the
value it had just produced out of `$1926`:

```
(C:$1940)  > $1926
  $1926:  F3
```

`0xF3`. We let the save finish, dumped the freshly written disk, and recovered the seed it
had encrypted with:

```
encryption seed this save: 0xF3
```

The **same number.** Not close — *identical*. The thing we'd been chasing as the
"encryption seed" and the thing the routine computes as the "integrity checksum" are **one
and the same byte.** The seed was never random; it was the checksum of the party, staring
at us the entire time. The save scheme, in full:

```
checksum = wasteland_checksum(8 plaintext record pages, bytes 0x00..0xFE)
for each byte i:  cipher[i] = plain[i] XOR ((2*i) & 0xFF) XOR checksum
```

One value does double duty: integrity check *and* cipher key. **This is the answer to the
question Part 2 left open** — why re-encrypting with the same seed never satisfies the
game. Changing one attribute changes the checksum, which changes the key for the *entire*
block, so a naive edit fails twice over: the block decrypts to garbage (wrong key) *and*
the recomputed checksum no longer matches. A static "decrypt, edit, re-encrypt with the
old seed" patch can never be valid.

> **Progress check.** As of Part 4 we finally know **how** the seed is *generated*: it's
> the party checksum. But there's still a hole — on *load*, the game must decrypt the
> block *before* it has any plaintext to checksum, so it can't be re-deriving the seed at
> load time. It must read it from somewhere. We still don't know **where the seed is
> stored**. That's the last piece, and it's what Part 5 nails down.

---

## Part 5 — How does the game *load* the seed?

The paradox: on load the game must **decrypt** the block (needs the seed), but the seed
**is** the checksum of the *plaintext* (which it doesn't have until it decrypts).
Chicken, meet egg. So the seed must be **stored** somewhere and read *before* decryption.

### 5a. Watchpoint #1 — the data arrives encrypted

```
bank ram
watch store f400 f400
x                       ; (re)boot so the party loads
```

Breaks at:

```
.C:ff34  9D 00 F4    STA $F400,X    - A:E8 X:00 ...
```

`$FF00` is a **raster-timed serial fast-loader** (bit-bangs the 1541 using `$D011`/`$D012`
for timing and CIA2 `$DD00` for the lines; `JSR $FD9E` receives one byte). The bytes land
at `$F400–$FBFF` **still encrypted** — dump `$F500` here and you get
`a0 af a0 a2 c0 b0 a5 bc…`, which only spells `HELL RAZOR` after decrypting with `0xE8`.
Decryption happens *after* the load.

### 5b. Watchpoint #2 — catch the decrypt reading the seed

The loader only ever *writes* `$F400`, so the first *read* of `$F400` is the decryptor:

```
del
watch load f400 f400
x
```

Breaks inside a tight loop at `$1953`, right next to the checksum:

```
$1944  STA $1956     ; self-modify: write the SEED into the EOR operand below
$1947  LDA #$00
$1949  STA $195F     ; reset slot counter
$194C  JSR $1201     ; point $66/$67 at current record ($F400 + slot*256)
$194F  LDY #$00
$1951  TYA           ; A = i
$1952  ASL A         ; A = 2*i
$1953  EOR ($66),Y   ; A = 2i XOR cipher[i]
$1955  EOR #$E8      ; A = 2i XOR cipher[i] XOR seed   <- seed is a self-modified immediate
$1957  STA ($66),Y   ; plaintext written back in place
$1959  INY / CPY #$FF / BNE $1951    ; bytes 0x00..0xFE  (0xFF skipped!)
$1965  BCC $1949                     ; loop 8 slots
```

The seed (`0xE8`) is already baked into `EOR #$E8` *before* anything read `$F400` — so it
came from somewhere else, not byte 0 of the block.

### 5c. Follow it home — save side stores it, load side reads it

Hunt for callers of `$1944` (`JSR $1944` = bytes `20 44 19`). The **save** side:

```
$18F7  JSR $1918     ; compute CHECKSUM of plaintext -> A
$18FA  STA $F4FF     ; *** store checksum at slot0 offset 0xFF ***
$18FD  PHA
$18FE  JSR $1944     ; ENCRYPT block, seed = that checksum
 ...   (write 8 sectors)
$1912  PLA
$1913  JSR $1944     ; decrypt back in RAM so play can continue
```

`STA $F4FF` — the checksum is written to **offset `0xFF` of slot 0**, the one byte both
the checksum loop *and* the crypt loop skip (`CPY #$FF`), so it rides on disk **in the
clear**. The **load** side just reads it back:

```
$830E  ...                ; loop: pull 8 encrypted sectors into $F400-$FBFF
$8313  JSR $02CF          ;   (one sector per pass, via the $FF00 fast-loader)
$831F  BCC $8310
$8321  LDA $F4FF          ; *** read the plaintext seed ***
$8324  JSR $04E7          ; bank-switch thunk -> $1944: decrypt with seed = A
```

Confirm the on-disk byte directly — `$F4FF` maps to `SECTORS[0] + 0xFF = 0x2A2FF`:

```bash
python3 -c "d=open('disk1-orig.d64','rb').read(); print('disk1-orig 0x2A2FF = 0x%02X (== seed E8)' % d[0x2A2FF])"
```

```
disk1-orig 0x2A2FF = 0xE8 (== seed E8)
```

The paradox is solved: the seed isn't *derived* at load, it's **read** — one plaintext
byte deliberately carved out of both the cipher and the checksum so it can carry itself
across a save.

---

## Part 6 — The self-verifying patcher

With the checksum, the seed-coupling, and the layout all understood, the whole thing
collapses into a small **direct disk editor** — no emulator required. The 8 party sectors
in RAM-slot order:

```
slot 0  $F400  party metadata   -> disk 0x2A200   (carries the seed at +0xFF)
slot 1  $F500  HELL RAZOR        -> disk 0x29C00
slot 2  $F600  SNAKE VARGAS      -> disk 0x2A700
slot 3  $F700  ANGELA DETH       -> disk 0x2A100
slot 4  $F800  THRASHER          -> disk 0x29B00
slot 5  $F900  (empty)           -> disk 0x29A00
slot 6  $FA00  (empty)           -> disk 0x2A000
slot 7  $FB00  (empty)           -> disk 0x2A600
```

### 6a. Inspect, then patch (`wl_patch.py`)

The tool reads the seed from slot0[`0xFF`], **independently re-derives it** with a
name-slide, decrypts, and refuses to write unless all three agree (`seed == slide ==
checksum`). It re-verifies after writing. (Full source: [`wl_patch.py`](wl_patch.py).)

```bash
# read-only: print stats and prove the model matches the disk
python3 wl_patch.py inspect disk1-orig.d64
```

```
seed @ slot0 byte 0xFF : 0xe8   (the byte the game reads at load)
seed via name slide    : 0xe8   agrees
recomputed checksum    : 0xe8   OK (model matches disk)

  HELL RAZOR    STR=16 IQ=17 LCK=16 SPD=13 AGI=15 DEX=13 CHA=12  MAXCON=24 CON=24 skill=1
  SNAKE VARGAS  STR=11 IQ=16 LCK=8 SPD=7 AGI=17 DEX=13 CHA=6  MAXCON=34 CON=34 skill=0
  ANGELA DETH   STR=14 IQ=16 LCK=7 SPD=10 AGI=10 DEX=11 CHA=4  MAXCON=33 CON=33 skill=0
  THRASHER      STR=13 IQ=16 LCK=10 SPD=6 AGI=17 DEX=16 CHA=10  MAXCON=26 CON=22 skill=0
```

```bash
# write a maxed copy (re-derives the new seed/checksum and re-encrypts the 8 sectors)
python3 wl_patch.py max disk1-orig.d64 --out my-cracked.d64
python3 wl_patch.py inspect my-cracked.d64        # all 99 / 999 / 255, seed/slide/checksum agree
```

The patch routine, end to end: read+cross-check the seed → decrypt the 8 sectors →
**verify** (seed == slide == checksum, else ABORT) → edit attributes → `new_seed =
checksum(edited block)` → write `new_seed` as plaintext into slot0[`0xFF`] → re-encrypt
bytes `0x00–0xFE` of all 8 sectors → **verify again**. Steps marked *verify* are the
safety rail: three independent values must agree before and after writing.

### 6b. Verify the cracked disk's invariant holds

```bash
python3 wl_patch.py inspect disk1-cracked.d64
```

```
seed @ slot0 byte 0xFF : 0x88   (the byte the game reads at load)
seed via name slide    : 0x88   agrees
recomputed checksum    : 0x88   OK (model matches disk)

  HELL RAZOR    STR=99 IQ=99 LCK=99 SPD=99 AGI=99 DEX=99 CHA=99  MAXCON=999 CON=999 skill=255
  SNAKE VARGAS  STR=99 IQ=99 LCK=99 SPD=99 AGI=99 DEX=99 CHA=99  MAXCON=999 CON=999 skill=255
  ANGELA DETH   STR=99 IQ=99 LCK=99 SPD=99 AGI=99 DEX=99 CHA=99  MAXCON=999 CON=999 skill=255
  THRASHER      STR=99 IQ=99 LCK=99 SPD=99 AGI=99 DEX=99 CHA=99  MAXCON=999 CON=999 skill=255
```

Seed `0x88`, and `seed == slide == checksum == 0x88` — the cracked disk satisfies the
exact invariant we reverse-engineered. All four rangers maxed, valid checksum, no tamper
trap. **The crack holds.**

---
