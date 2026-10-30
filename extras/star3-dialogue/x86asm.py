import struct

class Register(int):
    pass


EAX, ECX, EDX, EBX, ESP, EBP, ESI, EDI = (Register(value) for value in range(8))
REG8 = {"al": EAX, "cl": ECX, "dl": EDX, "bl": EBX, "ah": 4, "ch": 5, "dh": 6, "bh": 7}
JCC = {"jo": 0, "jno": 1, "jb": 2, "jae": 3, "je": 4, "jne": 5, "jbe": 6, "ja": 7,
       "js": 8, "jns": 9, "jp": 10, "jnp": 11, "jl": 12, "jge": 13, "jle": 14, "jg": 15}


class Assembler:
    def __init__(self, base):
        self.base = base
        self.code = bytearray()
        self.labels = {}
        self.fixups = []

    def tell(self):
        return self.base + len(self.code)

    def label(self, name):
        self.labels[name] = self.tell()

    def db(self, *values):
        self.code.extend(values)

    def dd(self, value):
        self.code.extend(struct.pack("<I", value & 0xFFFFFFFF))

    def _target(self, name, relative):
        if isinstance(name, str):
            self.fixups.append((len(self.code), name, relative))
            self.dd(0)
        else:
            self.dd(name - (self.tell() + 4) if relative else name)

    def call(self, target):
        if isinstance(target, int) and 0 <= target < 8:
            self.db(0xFF)
            self._rm(target, 2)
        else:
            self.db(0xE8)
            self._target(target, True)

    def jmp(self, target):
        self.db(0xE9)
        self._target(target, True)

    def jcc(self, condition, target):
        self.db(0x0F, 0x80 + JCC[condition])
        self._target(target, True)

    def push(self, value):
        if isinstance(value, int) and 0 <= value < 8:
            self.db(0x50 + value)
        else:
            self.db(0x68)
            self.dd(value)

    def pushi(self, value):
        self.db(0x68)
        self.dd(value)

    def pop(self, reg):
        self.db(0x58 + reg)

    def pushad(self):
        self.db(0x60)

    def popad(self):
        self.db(0x61)

    def pushfd(self):
        self.db(0x9C)

    def popfd(self):
        self.db(0x9D)

    def ret(self):
        self.db(0xC3)

    def nop(self, count=1):
        self.code.extend(b"\x90" * count)

    def _rm(self, operand, reg):
        if isinstance(operand, int) and not 0 <= operand < 8:
            self.db((reg << 3) | 5)
            self.dd(operand)
            return
        if isinstance(operand, int):
            self.db(0xC0 | (reg << 3) | operand)
            return
        base = operand[0]
        if len(operand) == 2:
            if isinstance(operand[1], Register):
                index, scale, disp = operand[1], 1, 0
            else:
                index, scale, disp = None, 1, operand[1]
        else:
            index, scale, disp = operand[1:]
        if disp == 0 and base != EBP:
            mod = 0
        elif -128 <= disp <= 127:
            mod = 1
        else:
            mod = 2
        if index is None and base != ESP:
            self.db((mod << 6) | (reg << 3) | base)
        else:
            self.db((mod << 6) | (reg << 3) | 4)
            self.db((scale.bit_length() - 1) << 6 | ((4 if index is None else index) << 3) | base)
        if mod == 1:
            self.db(disp & 0xFF)
        elif mod == 2:
            self.dd(disp)

    def movi(self, dst, value):
        if isinstance(value, (tuple, Register)):
            self.mov(dst, value)
        elif isinstance(dst, tuple):
            self.db(0xC7)
            self._rm(dst, 0)
            self.dd(value)
        else:
            self.db(0xB8 + dst)
            self.dd(value)

    def mov(self, dst, src):
        if isinstance(dst, int) and 0 <= dst < 8 and isinstance(src, int) and src >= 8:
            self.db(0xB8 + dst)
            self.dd(src)
        elif isinstance(dst, int) and 0 <= dst < 8:
            self.db(0x8B)
            self._rm(src, dst)
        else:
            self.db(0x89)
            self._rm(dst, src)

    def load(self, dst, address):
        self.db(0x8B)
        self._rm(address, dst)

    def mov8(self, dst, src):
        if isinstance(dst, str):
            dst = REG8[dst]
        if isinstance(src, str):
            src = REG8[src]
        if isinstance(dst, int):
            self.db(0x8A)
            self._rm(src, dst)
        else:
            self.db(0x88)
            self._rm(dst, src)

    def movzx8(self, dst, src):
        self.db(0x0F, 0xB6)
        self._rm(src, dst)

    def movzx16(self, dst, src):
        self.db(0x0F, 0xB7)
        self._rm(src, dst)

    def mov16(self, dst, src):
        self.db(0x66, 0x89)
        self._rm(dst, src)

    def lea(self, dst, src):
        self.db(0x8D)
        self._rm(src, dst)

    def alu(self, operation, dst, src=None):
        directions = {"add": (0x01, 0x03), "or": (0x09, 0x0B), "and": (0x21, 0x23),
                      "sub": (0x29, 0x2B), "xor": (0x31, 0x33), "cmp": (0x39, 0x3B)}
        if operation == "neg":
            self.db(0xF7)
            self._rm(dst, 3)
        elif operation == "test":
            self.db(0x85)
            self._rm(dst, src)
        elif isinstance(dst, int) and 0 <= dst < 8:
            self.db(directions[operation][1])
            self._rm(src, dst)
        else:
            self.db(directions[operation][0])
            self._rm(dst, src)

    def imm(self, operation, dst, value):
        if isinstance(value, (tuple, Register)):
            self.alu(operation, dst, value)
            return
        group = {"add": 0, "or": 1, "and": 4, "sub": 5, "xor": 6, "cmp": 7}[operation]
        if -128 <= value <= 127:
            self.db(0x83)
            self._rm(dst, group)
            self.db(value & 0xFF)
        else:
            self.db(0x81)
            self._rm(dst, group)
            self.dd(value)

    def shift(self, operation, dst, count):
        self.db(0xC1)
        self._rm(dst, {"shl": 4, "shr": 5}[operation])
        self.db(count)

    def inc(self, dst):
        self.db(0xFF)
        self._rm(dst, 0)

    def finish(self):
        for position, name, relative in self.fixups:
            target = self.labels[name] if isinstance(name, str) else name
            value = target - (self.base + position + 4) if relative else target
            struct.pack_into("<i", self.code, position, value)
        return bytes(self.code)
