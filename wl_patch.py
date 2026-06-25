#!/usr/bin/env python3
"""
wl_patch.py - Wasteland (C64) party editor for the disk image in this directory.

Edits character attributes directly on the .d64, correctly recomputing the
game's integrity checksum and re-encrypting the party block. See
HOW-PATCH-WITH-CMDs.md for how this all works.

Seed model (traced on the load side in VICE): the encryption seed is stored in
PLAINTEXT at offset 0xFF of slot 0 (the party-metadata record) -- RAM $F4FF,
disk SECTORS[0]+0xFF. Both the cipher loop and the checksum loop deliberately
skip byte 0xFF, so it survives in the clear. On load the game reads that byte
($8321 LDA $F4FF) and uses it to decrypt; on save it writes the freshly computed
checksum there. We do exactly the same.

Safety model: this is SELF-VERIFYING. Before editing it reads the stored seed,
independently re-derives it with a known-plaintext name slide, decrypts, and
checks the recomputed checksum equals both. If those three don't agree, the
script ABORTS rather than risk corrupting the disk. It re-verifies after writing.

Usage:
    python3 wl_patch.py inspect "<disk.d64>"
    python3 wl_patch.py max     "<disk.d64>" [--out OUT.d64] [--value N] [--con N] [--skill N]
"""
import sys, shutil, argparse

# --- party block layout (this disk image) -------------------------------------
# The checksum sums 8 record slots that live at $F400-$FBFF in RAM. On disk they
# map to these track-35 sectors, listed in RAM-slot order (order matters: the
# checksum chains a carry across slots).
SECTORS = [0x2a200,   # slot0  party metadata
           0x29c00,   # slot1  HELL RAZOR
           0x2a700,   # slot2  SNAKE VARGAS
           0x2a100,   # slot3  ANGELA DETH
           0x29b00,   # slot4  THRASHER
           0x29a00,   # slot5  empty
           0x2a000,   # slot6  empty
           0x2a600]   # slot7  empty
CHAR_SLOTS = [1, 2, 3, 4]            # slots holding editable characters

SEED_SLOT = 0       # the seed lives in slot 0 (party metadata)...
SEED_OFF  = 0xff    # ...at offset 0xFF, stored in PLAINTEXT (never ciphered)

# --- character record field offsets ------------------------------------------
OFF_NAME   = 0x00
OFF_ATTR   = 0x0e   # STR,IQ,LCK,SPD,AGI,DEX,CHA (7 bytes)
OFF_MAXCON = 0x1b   # 2 bytes LE
OFF_CON    = 0x1d   # 2 bytes LE
OFF_SKILL  = 0x20
ATTR_NAMES = ["STR","IQ","LCK","SPD","AGI","DEX","CHA"]

# --- crypto + checksum --------------------------------------------------------
def keybyte(i, seed):
    return (seed ^ ((2 * i) & 0xff)) & 0xff

def xcrypt(block, seed):
    """Encrypt/decrypt bytes 0x00-0xFE; byte 0xFF is left untouched.

    The game's crypt loop runs Y=0x00..0xFE and stops at CPY #$FF, so offset
    0xFF is never ciphered: in slot 0 it carries the plaintext seed, elsewhere
    it's untouched padding. XOR is its own inverse, so this both encrypts and
    decrypts."""
    out = bytearray(block)
    for i in range(0xff):            # 0x00 .. 0xFE
        out[i] ^= keybyte(i, seed)
    return bytes(out)

def read_seed(disk):
    """The seed exactly as the game loads it: the plaintext byte at offset 0xFF
    of the slot-0 (metadata) sector. The game reads this at load time
    ($8321 LDA $F4FF) before decrypting the party block."""
    return disk[SECTORS[SEED_SLOT] + SEED_OFF]

def recover_seed(disk, name=b"HELL RAZOR"):
    """Independent cross-check: known-plaintext slide on a character name."""
    for p in range(len(disk) - len(name)):
        k = None
        for j, ch in enumerate(name):
            t = (disk[p+j] ^ ch ^ ((2*j) & 0xff)) & 0xff
            if k is None: k = t
            elif t != k: break
        else:
            return k
    raise RuntimeError("could not locate %r to recover seed" % name)

def checksum(pages):
    """A=0; for each slot, for Y in 0..0xFE: A+=rec[Y] (carry c); A+=Y+c."""
    A = 0
    for pg in pages:
        for Y in range(0x00, 0xff):
            s = A + pg[Y]; A = s & 0xff; c = s >> 8
            A = (A + Y + c) & 0xff
    return A

# --- read / verify ------------------------------------------------------------
def read_pages(disk, seed):
    return [xcrypt(disk[off:off+256], seed) for off in SECTORS]

def load_and_verify(disk):
    seed  = read_seed(disk)            # how the game does it (slot0 byte 0xFF)
    slide = recover_seed(disk)         # independent cross-check (name slide)
    pages = read_pages(disk, seed)
    got   = checksum(pages)
    ok    = (got == seed == slide)
    return seed, slide, pages, got, ok

def name_of(page):
    return page[OFF_NAME:OFF_NAME+14].split(b"\x00")[0].decode("latin1", "replace")

# --- commands -----------------------------------------------------------------
def cmd_inspect(path):
    disk = bytearray(open(path, "rb").read())
    seed, slide, pages, got, ok = load_and_verify(disk)
    print("seed @ slot0 byte 0xFF : 0x%02x   (the byte the game reads at load)" % seed)
    print("seed via name slide    : 0x%02x   %s" %
          (slide, "agrees" if slide == seed else "DISAGREES -- do NOT patch"))
    print("recomputed checksum    : 0x%02x   %s" %
          (got, "OK (model matches disk)" if ok else "MISMATCH -- model is wrong, do NOT patch"))
    print()
    for s in CHAR_SLOTS:
        pg = pages[s]
        attrs = " ".join("%s=%d" % (ATTR_NAMES[i], pg[OFF_ATTR+i]) for i in range(7))
        maxcon = pg[OFF_MAXCON] | pg[OFF_MAXCON+1] << 8
        con    = pg[OFF_CON]    | pg[OFF_CON+1]    << 8
        print("  %-13s %s  MAXCON=%d CON=%d skill=%d" %
              (name_of(pg), attrs, maxcon, con, pg[OFF_SKILL]))
    return ok

def cmd_max(path, out, value, con, skill):
    disk = bytearray(open(path, "rb").read())
    seed, slide, pages, got, ok = load_and_verify(disk)
    if not ok:
        sys.exit("ABORT: pre-edit verify failed (seed@0xFF=0x%02x  slide=0x%02x  "
                 "checksum=0x%02x). The model does not match this disk; refusing "
                 "to write." % (seed, slide, got))
    print("pre-edit verify OK (seed == slide == checksum == 0x%02x)" % seed)

    # edit the four characters in place (plaintext)
    pages = [bytearray(p) for p in pages]
    for s in CHAR_SLOTS:
        pg = pages[s]
        for i in range(7):
            pg[OFF_ATTR+i] = value
        pg[OFF_MAXCON] = con & 0xff; pg[OFF_MAXCON+1] = (con >> 8) & 0xff
        pg[OFF_CON]    = con & 0xff; pg[OFF_CON+1]    = (con >> 8) & 0xff
        pg[OFF_SKILL]  = skill
        print("  maxed %-13s -> attrs=%d CON=%d skill=%d" % (name_of(pg), value, con, skill))

    # recompute checksum -> this becomes the new encryption seed
    new_seed = checksum(pages)
    print("new checksum / seed   : 0x%02x" % new_seed)

    # store the seed in PLAINTEXT at slot0 offset 0xFF, exactly like the game does
    pages[SEED_SLOT][SEED_OFF] = new_seed

    # re-encrypt bytes 0x00-0xFE of each sector (byte 0xFF passes through untouched)
    for off, pg in zip(SECTORS, pages):
        disk[off:off+256] = xcrypt(pg, new_seed)

    # self-check: re-read what we just wrote and verify the invariant holds
    chk_seed, chk_slide, chk_pages, chk_got, chk_ok = load_and_verify(disk)
    if not (chk_ok and chk_seed == new_seed):
        sys.exit("ABORT: post-write verification failed (internal error); output not trusted")
    print("post-write verify OK (seed == slide == checksum == 0x%02x)" % new_seed)

    if out is None:
        shutil.copyfile(path, path + ".bak")
        out = path
        print("backup written: %s.bak" % path)
    open(out, "wb").write(disk)
    print("written: %s" % out)
    print("** test in an emulator before trusting it **")

# --- cli ----------------------------------------------------------------------
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("inspect"); pi.add_argument("disk")
    pm = sub.add_parser("max"); pm.add_argument("disk")
    pm.add_argument("--out", default=None)
    pm.add_argument("--value", type=int, default=99)
    pm.add_argument("--con", type=int, default=999)
    pm.add_argument("--skill", type=int, default=255)
    a = ap.parse_args()
    if a.cmd == "inspect":
        sys.exit(0 if cmd_inspect(a.disk) else 1)
    else:
        cmd_max(a.disk, a.out, a.value, a.con, a.skill)
