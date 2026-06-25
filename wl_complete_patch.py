#!/usr/bin/env python3
"""
wl_complete_patch.py - full character editor for the Wasteland (C64) party.

Edit each ranger's:
  - Attributes (STR, IQ, LCK, SPD, AGI, DEX, CHA)
  - Max Constitution / Current Constitution
  - Skill points
  - Skills (add / remove / set level)
  - Inventory (add / remove items)        <- reuses wl_inventory.py

then re-seals the disk image (recomputes checksum/seed) exactly like wl_patch.

Encodings (see ITEMS.txt):
  - skill pair  @ 0x80.. : (string-index, level)        -- raw index 1..35
  - item  pair  @ 0xBD.. : (string-index - 36, ammo)    -- offset by 36
Both lists are null-terminated.

Usage:
    python3 wl_complete_patch.py "<disk.d64>"
"""
import sys
import wl_patch as wl
import wl_inventory as winv

# --- skills: raw string-table index 1..35 -> name -----------------------------
SKILLS = {
    1:"Brawling", 2:"Climb", 3:"Clip pistol", 4:"Knife fight", 5:"Pugilism",
    6:"Rifle", 7:"Swim", 8:"Knife throw", 9:"Perception", 10:"Assault rifle",
    11:"AT weapon", 12:"SMG", 13:"Acrobat", 14:"Gamble", 15:"Picklock",
    16:"Silent move", 17:"Combat shooting", 18:"Confidence", 19:"Sleight of hand",
    20:"Demolitions", 21:"Forgery", 22:"Alarm disarm", 23:"Bureaucracy",
    24:"Bomb disarm", 25:"Medic", 26:"Safecrack", 27:"Cryptology", 28:"Metallurgy",
    29:"Helicopter pilot", 30:"Electronics", 31:"Toaster repair", 32:"Doctor",
    33:"Clone tech", 34:"Energy weapon", 35:"Cyborg tech",
}
SKILLS_OFF = 0x80
SKILLS_END = 0xBD     # exclusive; the item list begins here
MAX_SKILLS = 30

ask = winv.ask   # reuse console helper

def ask_int(prompt, default, hi=255):
    s = ask(prompt, str(default))
    if s is None: return default
    try: return max(0, min(hi, int(s)))
    except ValueError: return default

# --- low-level field access ---------------------------------------------------
def rd16(pg, off):  return pg[off] | (pg[off+1] << 8)
def wr16(pg, off, v):
    v &= 0xffff; pg[off] = v & 0xff; pg[off+1] = (v >> 8) & 0xff

def get_skills(pg):
    out = []; o = SKILLS_OFF
    while o < SKILLS_END-1 and pg[o] != 0:
        out.append([pg[o], pg[o+1]]); o += 2
    return out

def set_skills(pg, sk):
    o = SKILLS_OFF
    for sid, lvl in sk:
        pg[o] = sid & 0xff; pg[o+1] = lvl & 0xff; o += 2
    for k in range(o, SKILLS_END):     # terminator + scrub (never touch items)
        pg[k] = 0

def skill_name(i): return SKILLS.get(i, "unknown(%d)" % i)

# --- FULLMAX preset -----------------------------------------------------------
FM_ATTR      = 99    # every attribute
FM_CON       = 999   # max & current constitution
FM_POINTS    = 255   # skill points
FM_SKILL_LVL = 99    # level for every granted skill
# 30 skills = all that fit before the item list; weapon skills first so they're
# guaranteed in (incl. Energy weapon=34 for the Meson, Assault rifle=10 for the M1989A1)
FM_SKILLS = [34,10,17,12,11,6,3,8,1,4,5,
             9,25,15,26,16,2,7,13,14,18,19,20,21,22,24,27,28,30,32]
# god loadout: (item_id, loaded_ammo, count)
FM_ITEMS = [(0x1d, 10,  1),   # Meson cannon (10 shots loaded)
            (0x22,  0, 10),   # 10x Power pack
            (0x23,  0,  1),   # Power armor
            (0x2c,  0,  1),   # Canteen
            (0x36,  0,  1),   # Rope
            (0x2d,  0,  1),   # Crowbar
            (0x18, 30,  1),   # M1989A1 Nato assault rifle (30 loaded)
            (0x1f,  0, 10)]   # 10x 7.62mm clip

def fullmax(pg):
    for i in range(7):
        pg[wl.OFF_ATTR+i] = FM_ATTR
    wr16(pg, wl.OFF_MAXCON, FM_CON); wr16(pg, wl.OFF_CON, FM_CON)
    pg[wl.OFF_SKILL] = FM_POINTS
    set_skills(pg, [[sid, FM_SKILL_LVL] for sid in FM_SKILLS])
    inv = []
    for iid, ammo, cnt in FM_ITEMS:
        inv += [[iid, ammo] for _ in range(cnt)]
    winv.set_inv(pg, inv)

# --- summary ------------------------------------------------------------------
def summary(pg):
    print("\n=== %s ===" % wl.name_of(pg))
    print("  Attributes:  " + "  ".join(
        "%s=%d" % (wl.ATTR_NAMES[i], pg[wl.OFF_ATTR+i]) for i in range(7)))
    print("  MAX CON=%d   CUR CON=%d   Skill points=%d" %
          (rd16(pg, wl.OFF_MAXCON), rd16(pg, wl.OFF_CON), pg[wl.OFF_SKILL]))
    sk = get_skills(pg)
    print("  Skills (%d): %s" % (len(sk),
          ", ".join("%s/%d" % (skill_name(a), b) for a, b in sk) or "(none)"))
    print("  Inventory:  %d items" % len(winv.get_inv(pg)))

# --- editors ------------------------------------------------------------------
def edit_attrs(pg):
    changed = False
    while True:
        line = "  " + "  ".join("%d)%s=%d" % (i+1, wl.ATTR_NAMES[i], pg[wl.OFF_ATTR+i])
                                 for i in range(7))
        print("\n Attributes:\n" + line)
        s = ask(" set #1-7 (or 'all'), [b]ack: ")
        if s is None or s in ("b", ""): return changed
        if s != "all":
            try:
                k = int(s); assert 1 <= k <= 7
            except (ValueError, AssertionError):
                print("   pick 1-7 or 'all'"); continue
        v = ask_int(" value (0-255, 99=max): ", 99)
        if s == "all":
            for i in range(7): pg[wl.OFF_ATTR+i] = v
            print("   all attributes = %d" % v)
        else:
            pg[wl.OFF_ATTR+int(s)-1] = v
            print("   %s = %d" % (wl.ATTR_NAMES[int(s)-1], v))
        changed = True

def edit_con(pg):
    changed = False
    while True:
        print("\n MAX CON=%d   CUR CON=%d" % (rd16(pg, wl.OFF_MAXCON), rd16(pg, wl.OFF_CON)))
        s = ask(" set [m]ax, [c]urrent, [t]both, [b]ack: ")
        if s is None or s in ("b", ""): return changed
        if s not in ("m", "c", "t"): print("   m / c / t / b"); continue
        v = ask_int(" value (0-65535, e.g. 999): ", 999, hi=65535)
        if s in ("m", "t"): wr16(pg, wl.OFF_MAXCON, v)
        if s in ("c", "t"): wr16(pg, wl.OFF_CON, v)
        changed = True; print("   set.")

def edit_skill_points(pg):
    print("\n Skill points = %d" % pg[wl.OFF_SKILL])
    v = ask_int(" new value (0-255, blank=keep): ", pg[wl.OFF_SKILL])
    if v != pg[wl.OFF_SKILL]:
        pg[wl.OFF_SKILL] = v; print("   skill points = %d" % v); return True
    return False

def choose_skill():
    print("\n  ===== SKILLS =====")
    for i, n in sorted(SKILLS.items()):
        print("     %2d  %s" % (i, n))
    while True:
        s = ask(" skill number or name search, blank=cancel: ")
        if s is None or s == "": return None
        try:
            v = int(s)
            if v in SKILLS: return v
        except ValueError:
            pass
        m = sorted((i, n) for i, n in SKILLS.items() if s.lower() in n.lower())
        if not m: print("   no match"); continue
        if len(m) == 1: print("   -> %d %s" % m[0]); return m[0][0]
        for i, n in m: print("     %2d  %s" % (i, n))

def edit_skills(pg):
    changed = False
    while True:
        sk = get_skills(pg)
        print("\n Skills (%d/%d):" % (len(sk), MAX_SKILLS))
        for n, (sid, lvl) in enumerate(sk, 1):
            print("   %2d. %-18s lvl %d" % (n, skill_name(sid), lvl))
        s = ask(" [a]dd/set  [r]emove N  [b]ack: ")
        if s is None or s in ("b", ""): return changed
        if s == "a":
            sid = choose_skill()
            if sid is None: continue
            lvl = ask_int(" level (1-255): ", 1)
            for pair in sk:
                if pair[0] == sid:           # already known -> update level
                    pair[1] = lvl; break
            else:
                if len(sk) >= MAX_SKILLS:
                    print("   skill list full"); continue
                sk.append([sid, lvl])
            set_skills(pg, sk); changed = True
            print("   %s -> lvl %d" % (skill_name(sid), lvl))
        elif s.startswith("r"):
            arg = s[1:].strip() or ask(" remove which #: ", "")
            try:
                k = int(arg)
                if 1 <= k <= len(sk):
                    gone = sk.pop(k-1); set_skills(pg, sk); changed = True
                    print("   removed %s" % skill_name(gone[0]))
                else: print("   no #%d" % k)
            except (ValueError, TypeError): print("   give a number")
        else:
            print("   a / rN / b")

def edit_ranger(pg):
    changed = False
    while True:
        summary(pg)
        s = ask("\n [a]ttributes  [c]onstitution  [p]oints  [s]kills  [i]nventory  [b]ack: ")
        if s is None or s in ("b", ""): return changed
        if   s == "a": changed |= edit_attrs(pg)
        elif s == "c": changed |= edit_con(pg)
        elif s == "p": changed |= edit_skill_points(pg)
        elif s == "s": changed |= edit_skills(pg)
        elif s == "i": changed |= winv.edit_ranger(pg)   # reuse inventory editor
        else: print("   a / c / p / s / i / b")

# --- main ---------------------------------------------------------------------
def main():
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
        for n, sl in enumerate(wl.CHAR_SLOTS, 1):
            pg = pages[sl]
            print("  %d. %-13s  STR=%d MAXCON=%d skills=%d items=%d" %
                  (n, wl.name_of(pg), pg[wl.OFF_ATTR], rd16(pg, wl.OFF_MAXCON),
                   len(get_skills(pg)), len(winv.get_inv(pg))))
        s = ask("\n Pick ranger 1-4,  [f]ull-max ALL,  [w]rite & quit,  [q]uit: ")
        if s is None or s == "q":
            print("Quit -- no changes written."); return
        if s == "w": break
        if s == "f":
            print("\n FULLMAX OVERWRITES all four rangers:")
            print("   attrs=%d, MAX/CUR CON=%d, skill points=%d, %d skills @ lvl %d" %
                  (FM_ATTR, FM_CON, FM_POINTS, len(FM_SKILLS), FM_SKILL_LVL))
            print("   inventory -> Meson cannon, 10x Power pack, Power armor, Canteen,")
            print("                Rope, Crowbar, M1989A1 Nato assault rifle, 5x 7.62mm clip")
            c = ask(" proceed? [y/N]: ")
            if c and c.lower().startswith("y"):
                for sl in wl.CHAR_SLOTS:
                    fullmax(pages[sl])
                dirty = True
                print(" FULLMAX applied to all four rangers.")
            else:
                print(" cancelled.")
            continue
        if s in ("1", "2", "3", "4"):
            dirty |= edit_ranger(pages[wl.CHAR_SLOTS[int(s)-1]])
        else:
            print("   pick 1-4, f, w, or q")

    if not dirty:
        print("No changes -- nothing written."); return
    b = winv.backup(path)
    new_seed = winv.reseal(disk, pages)
    open(path, "wb").write(disk)
    print("\nbackup: %s" % b)
    print("written: %s  (new seed/checksum 0x%02x, verified)" % (path, new_seed))
    print("** test in an emulator before trusting it **")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted -- no changes written.")
