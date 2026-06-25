#!/usr/bin/env python3
"""
wl_inventory.py - interactive inventory editor for the Wasteland (C64) party.

Shows each ranger's current items, lets you remove and add items from a menu,
then re-seals the disk image (recomputes the checksum / encryption seed exactly
like wl_patch). Reuses wl_patch.py for all the crypto.

Item IDs: the inventory stores each item as a (id, ammo) byte pair, where
    id = (Wasteland-1 string-table index) - 36
See ITEMS.txt for the full list, or run:  python3 wl_inventory.py --items

Usage:
    python3 wl_inventory.py "<disk.d64>"
    python3 wl_inventory.py --items
"""
import sys, os, shutil
import wl_patch as wl

# --- item table: WL1 string-table index -> name (items are index 36..130) -----
NAMES_BY_INDEX = {
    37:"Ax", 38:"Club", 39:"Chainsaw", 40:"Knife", 41:"Proton ax",
    42:"Grenade", 43:"Plastic explosive", 44:"TNT", 45:"Mangler",
    46:"Sabot rocket", 47:"LAW rocket", 48:"RPG-7", 49:"M1911A1 45 pistol",
    50:"Spear", 51:"Throwing knife", 52:"VP91Z 9mm pistol", 53:"Flamethrower",
    54:"M17 carbine", 55:"M19 rifle", 56:"Red Ryder", 57:"Mac 17 SMG",
    58:"Uzi SMG Mark 27", 59:"AK 97 assault rifle", 60:"M1989A1 Nato assault rifle",
    61:"Laser pistol", 62:"Ion beamer", 63:"Laser carbine", 64:"Laser rifle",
    65:"Meson cannon", 66:"45 clip", 67:"7.62mm clip", 68:"9mm clip",
    69:"Howitzer shell", 70:"Power pack", 71:"Power armor", 72:"Bullet proof shirt",
    73:"Kevlar vest", 74:"Leather jacket", 75:"Kevlar suit", 76:"Pseudo-chitin armor",
    77:"Rad suit", 78:"Robe", 79:"Book", 80:"Canteen", 81:"Crowbar", 82:"Engine",
    83:"Gas mask", 84:"Geiger counter", 85:"Hand mirror", 86:"Jug", 87:"Map",
    88:"Match", 89:"Pick ax", 90:"Rope", 91:"Shovel", 92:"Sledge hammer",
    93:"Snake squeezins", 94:"Android head", 95:"Antitoxin", 96:"Finster's head",
    97:"Blackstar key", 98:"Bloodstaff", 99:"Bloodstaff (real)", 100:"Broken toaster",
    101:"Chemical", 102:"Clone fluid", 103:"Visa card", 104:"Fusion cell",
    105:"Grazer bat fetish", 109:"Nova key", 110:"Onyx ring", 111:"Passkey",
    112:"Plasma coupler", 113:"Power converter", 114:"Pulsar key", 115:"Quasar key",
    116:"Rom board", 117:"Room key #18", 118:"Ruby ring", 119:"Secpass 1",
    120:"Secpass 3", 121:"Secpass 7", 122:"Secpass A", 123:"Secpass B",
    124:"Servo motor", 125:"Sonic key", 126:"Toaster", 127:"Clay pot",
    128:"Fruit", 129:"Jewelry", 130:"Cash",
}
ITEMS = {idx - 36: name for idx, name in NAMES_BY_INDEX.items()}   # id -> name

def category(i):
    if 0x01 <= i <= 0x18: return "Weapons"
    if 0x19 <= i <= 0x1d: return "Energy weapons"
    if 0x1e <= i <= 0x22: return "Ammunition"
    if 0x23 <= i <= 0x2a: return "Armor"
    if 0x2b <= i <= 0x45: return "General / tools"
    return "Quest / keys / valuables"

CAT_ORDER = ["Weapons","Energy weapons","Ammunition","Armor",
             "General / tools","Quest / keys / valuables"]

INV_OFF   = 0xBD     # inventory starts here in the record
MAX_ITEMS = 30       # keep the list comfortably short of the 0xFF seed byte

def item_name(i):
    return ITEMS.get(i, "unknown(0x%02x)" % i)

# --- inventory get/set on a decrypted 256-byte record -------------------------
def get_inv(pg):
    out = []; o = INV_OFF
    while o < 0xFE and pg[o] != 0:
        out.append([pg[o], pg[o+1]]); o += 2
    return out

def set_inv(pg, items):
    o = INV_OFF
    for iid, ammo in items:
        pg[o] = iid & 0xff; pg[o+1] = ammo & 0xff; o += 2
    for k in range(o, 0xFF):     # terminator + scrub leftovers (never touch 0xFF seed)
        pg[k] = 0

# --- re-seal the disk (checksum -> seed -> encrypt), verifying the result -----
def reseal(disk, pages):
    new_seed = wl.checksum(pages)
    pages[wl.SEED_SLOT][wl.SEED_OFF] = new_seed
    for off, pg in zip(wl.SECTORS, pages):
        disk[off:off+256] = wl.xcrypt(pg, new_seed)
    s2 = wl.read_seed(disk)
    if not (s2 == new_seed == wl.recover_seed(disk)
            and wl.checksum(wl.read_pages(disk, s2)) == new_seed):
        raise RuntimeError("post-write verification FAILED -- not written")
    return new_seed

def backup(path):
    b = path + ".bak"; n = 1
    while os.path.exists(b):
        n += 1; b = "%s.bak%d" % (path, n)
    shutil.copyfile(path, b); return b

# --- console helpers ----------------------------------------------------------
def ask(prompt, default=""):
    try:
        s = input(prompt).strip()
    except EOFError:
        return None
    return s if s else default

def ask_int(prompt, default):
    s = ask(prompt, str(default))
    if s is None: return None
    try: return max(0, min(255, int(s)))
    except ValueError: return default

def print_items():
    print("\n  ===== ITEM LIST  (id = string-index - 36) =====")
    by_cat = {}
    for i, n in ITEMS.items():
        by_cat.setdefault(category(i), []).append((i, n))
    for cat in CAT_ORDER:
        print("\n  -- %s --" % cat)
        for i, n in sorted(by_cat.get(cat, [])):
            print("     0x%02x (%3d)  %s" % (i, i, n))
    print()

def show_inventory(pg):
    inv = get_inv(pg)
    print("  Current inventory (%d/%d):" % (len(inv), MAX_ITEMS))
    if not inv:
        print("     (empty)")
    for n, (iid, ammo) in enumerate(inv, 1):
        extra = "  ammo/qty=%d" % ammo if ammo else ""
        print("     %2d. 0x%02x  %-26s%s" % (n, iid, item_name(iid), extra))

def choose_item():
    print_items()
    while True:
        s = ask("Add which item? (hex id like 1d, or name search; blank=cancel): ")
        if s is None or s == "":
            return None
        iid = None
        try:
            v = int(s, 16)
            if v in ITEMS: iid = v
        except ValueError:
            pass
        if iid is not None:
            return iid
        matches = sorted((i, n) for i, n in ITEMS.items() if s.lower() in n.lower())
        if not matches:
            print("   no item matches %r" % s); continue
        if len(matches) == 1:
            i, n = matches[0]; print("   -> 0x%02x  %s" % (i, n)); return i
        print("   matches:")
        for i, n in matches:
            print("     0x%02x  %s" % (i, n))
        print("   (type the hex id to pick one)")

# --- per-ranger editing -------------------------------------------------------
def edit_ranger(pg):
    changed = False
    while True:
        print("\n=== %s ===" % wl.name_of(pg))
        show_inventory(pg)
        cmd = ask("\n[a]dd  [r]emove N  [b]ack : ")
        if cmd is None or cmd in ("b", ""):
            return changed
        if cmd == "a":
            inv = get_inv(pg)
            if len(inv) >= MAX_ITEMS:
                print("   inventory full (%d)" % MAX_ITEMS); continue
            iid = choose_item()
            if iid is None: continue
            qty  = ask_int("Quantity (default 1): ", 1)
            ammo = ask_int("Loaded ammo / 2nd byte (default 0): ", 0)
            for _ in range(max(1, qty)):
                if len(inv) >= MAX_ITEMS:
                    print("   inventory full -- stopped early"); break
                inv.append([iid, ammo])
            set_inv(pg, inv); changed = True
            print("   added %dx %s" % (qty, item_name(iid)))
        elif cmd.startswith("r"):
            inv = get_inv(pg)
            arg = cmd[1:].strip()
            num = arg if arg else ask("Remove which #: ", "")
            try:
                k = int(num)
                if 1 <= k <= len(inv):
                    gone = inv.pop(k-1)
                    set_inv(pg, inv); changed = True
                    print("   removed %s" % item_name(gone[0]))
                else:
                    print("   no item #%d" % k)
            except (ValueError, TypeError):
                print("   give an item number")
        else:
            print("   unknown command")

# --- main ---------------------------------------------------------------------
def main():
    if len(sys.argv) == 2 and sys.argv[1] in ("--items", "-i"):
        print_items(); return
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    path = sys.argv[1]
    disk = bytearray(open(path, "rb").read())

    seed = wl.read_seed(disk)
    if not (wl.checksum(wl.read_pages(disk, seed)) == seed == wl.recover_seed(disk)):
        sys.exit("ABORT: this disk doesn't match the model (seed/checksum mismatch).")
    pages = [bytearray(p) for p in wl.read_pages(disk, seed)]
    dirty = False

    while True:
        print("\n================ PARTY ================  (disk seed 0x%02x)" % seed)
        for n, s in enumerate(wl.CHAR_SLOTS, 1):
            print("  %d. %-13s  %d items" % (n, wl.name_of(pages[s]), len(get_inv(pages[s]))))
        cmd = ask("\nPick ranger 1-4,  [w]rite & quit,  [q]uit without saving: ")
        if cmd is None or cmd == "q":
            print("Quit -- no changes written."); return
        if cmd == "w":
            break
        if cmd in ("1", "2", "3", "4"):
            if edit_ranger(pages[wl.CHAR_SLOTS[int(cmd)-1]]):
                dirty = True
        else:
            print("   pick 1-4, w, or q")

    if not dirty:
        print("No changes -- nothing written."); return
    b = backup(path)
    new_seed = reseal(disk, pages)
    open(path, "wb").write(disk)
    print("\nbackup: %s" % b)
    print("written: %s  (new seed/checksum 0x%02x, verified)" % (path, new_seed))
    print("** test in an emulator before trusting it **")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted -- no changes written.")
