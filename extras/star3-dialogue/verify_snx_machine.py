from pathlib import Path
import json
import capstone
from capstone.x86 import *

ROOT = Path.cwd()
MANIFEST = json.loads((ROOT / ".analysis/snx-lift/manifest.json").read_text())
CODE = (ROOT / ".analysis/snx-lift/code.bin").read_bytes()
SCRIPT = (ROOT / ".analysis/snx-lift/T4206   ._SN").read_bytes()
CODE_BASE = 0x400000 + MANIFEST["section_rva"]
SCRIPT_BASE = 0x1000000
STATE_DATA = CODE_BASE + 0x4000
SLOT = STATE_DATA + 0x40
TASK_ID = 0x2ED48A4

R32 = {X86_REG_EAX: 0, X86_REG_ECX: 1, X86_REG_EDX: 2, X86_REG_EBX: 3,
       X86_REG_ESP: 4, X86_REG_EBP: 5, X86_REG_ESI: 6, X86_REG_EDI: 7}
R16 = {X86_REG_AX: 0, X86_REG_CX: 1, X86_REG_DX: 2, X86_REG_BX: 3,
       X86_REG_SP: 4, X86_REG_BP: 5, X86_REG_SI: 6, X86_REG_DI: 7}
R8 = {X86_REG_AL: (0, 0), X86_REG_CL: (1, 0), X86_REG_DL: (2, 0), X86_REG_BL: (3, 0),
      X86_REG_AH: (0, 8), X86_REG_CH: (1, 8), X86_REG_DH: (2, 8), X86_REG_BH: (3, 8)}
CONDS = {
    "je": lambda f: f["z"], "jne": lambda f: not f["z"],
    "jb": lambda f: f["c"], "jae": lambda f: not f["c"],
    "jbe": lambda f: f["c"] or f["z"], "ja": lambda f: not f["c"] and not f["z"],
    "js": lambda f: f["s"], "jns": lambda f: not f["s"],
    "jl": lambda f: f["s"] != f["o"], "jge": lambda f: f["s"] == f["o"],
    "jle": lambda f: f["z"] or f["s"] != f["o"],
    "jg": lambda f: not f["z"] and f["s"] == f["o"],
}


class Machine:
    def __init__(self):
        self.mem = {}
        self.r = [0] * 8
        self.f = {name: False for name in "czso"}
        self.steps = 0
        self.md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        self.md.detail = True
        self.insns = {i.address: i for i in self.md.disasm(CODE, CODE_BASE)}
        self.load(CODE_BASE, CODE)
        self.load(SCRIPT_BASE, SCRIPT)
        self.w32(CODE_BASE + 0x3000, STATE_DATA)
        self.w32(SLOT, SCRIPT_BASE)
        self.w32(SLOT + 8, 0x40000)
        self.r[4] = 0x800000
        self.w32(self.r[4], 0xDEADBEEF)

    def load(self, address, data):
        for index, value in enumerate(data):
            self.mem[address + index] = value

    def read(self, address, size):
        return sum(self.mem.get((address + index) & 0xFFFFFFFF, 0) << (8 * index)
                   for index in range(size))

    def write(self, address, value, size):
        for index in range(size):
            self.mem[(address + index) & 0xFFFFFFFF] = (value >> (8 * index)) & 0xFF

    def w32(self, address, value):
        self.write(address, value & 0xFFFFFFFF, 4)

    def rr(self, register):
        if register in R32:
            return self.r[R32[register]]
        if register in R16:
            return self.r[R16[register]] & 0xFFFF
        if register in R8:
            index, shift = R8[register]
            return (self.r[index] >> shift) & 0xFF
        raise ValueError(("register", register))

    def rw(self, register, value):
        if register in R32:
            self.r[R32[register]] = value & 0xFFFFFFFF
            return
        if register in R16:
            index = R16[register]
            self.r[index] = (self.r[index] & 0xFFFF0000) | (value & 0xFFFF)
            return
        if register in R8:
            index, shift = R8[register]
            self.r[index] = (self.r[index] & ~(0xFF << shift)) | ((value & 0xFF) << shift)
            return
        raise ValueError(("register", register))

    def addr(self, operand):
        address = operand.disp
        if operand.base:
            address += self.rr(operand.base)
        if operand.index:
            address += self.rr(operand.index) * operand.scale
        return address & 0xFFFFFFFF

    def readop(self, operand):
        if operand.type == X86_OP_IMM:
            return operand.imm & 0xFFFFFFFF
        if operand.type == X86_OP_REG:
            return self.rr(operand.reg)
        if operand.type == X86_OP_MEM:
            return self.read(self.addr(operand.mem), operand.size)
        raise ValueError(("operand", operand.type))

    def writeop(self, operand, value):
        if operand.type == X86_OP_REG:
            self.rw(operand.reg, value)
            return
        if operand.type == X86_OP_MEM:
            self.write(self.addr(operand.mem), value, operand.size)
            return
        raise ValueError(("write", operand.type))

    def logic(self, value, size):
        self.f["c"] = self.f["o"] = False
        self.f["z"] = (value & ((1 << (8 * size)) - 1)) == 0
        self.f["s"] = bool(value & (1 << (8 * size - 1)))

    def math(self, left, right, result, size, subtract):
        mask = (1 << (8 * size)) - 1
        sign = 1 << (8 * size - 1)
        left &= mask
        right &= mask
        result &= mask
        self.f["z"] = result == 0
        self.f["s"] = bool(result & sign)
        self.f["c"] = left < right if subtract else result < left
        self.f["o"] = bool(((left ^ right) & (left ^ result) & sign) if subtract
                           else (~(left ^ right)) & (left ^ result) & sign)

    def run(self, start, stops, max_steps=20000):
        ip = start
        while ip not in stops:
            self.steps += 1
            if self.steps > max_steps:
                raise RuntimeError("step limit")
            insn = self.insns[ip]
            operands = insn.operands
            mnemonic = insn.mnemonic
            next_ip = insn.address + insn.size
            if mnemonic == "mov":
                self.writeop(operands[0], self.readop(operands[1]))
            elif mnemonic == "movzx":
                self.writeop(operands[0], self.readop(operands[1]))
            elif mnemonic == "lea":
                self.writeop(operands[0], self.addr(operands[1].mem))
            elif mnemonic in ("pushad", "pushal"):
                original_esp = self.r[4]
                for index in range(8):
                    self.r[4] = (self.r[4] - 4) & 0xFFFFFFFF
                    self.w32(self.r[4], original_esp if index == 4 else self.r[index])
            elif mnemonic in ("popad", "popal"):
                for index in reversed(range(8)):
                    value = self.read(self.r[4], 4)
                    self.r[4] = (self.r[4] + 4) & 0xFFFFFFFF
                    if index != 4:
                        self.r[index] = value
            elif mnemonic == "push":
                self.r[4] = (self.r[4] - 4) & 0xFFFFFFFF
                self.w32(self.r[4], self.readop(operands[0]))
            elif mnemonic == "pop":
                self.writeop(operands[0], self.read(self.r[4], 4))
                self.r[4] = (self.r[4] + 4) & 0xFFFFFFFF
            elif mnemonic == "call":
                self.r[4] = (self.r[4] - 4) & 0xFFFFFFFF
                self.w32(self.r[4], next_ip)
                next_ip = self.readop(operands[0])
            elif mnemonic == "ret":
                next_ip = self.read(self.r[4], 4)
                self.r[4] = (self.r[4] + 4) & 0xFFFFFFFF
                if operands:
                    self.r[4] = (self.r[4] + self.readop(operands[0])) & 0xFFFFFFFF
            elif mnemonic == "jmp":
                next_ip = self.readop(operands[0])
            elif mnemonic in CONDS:
                if CONDS[mnemonic](self.f):
                    next_ip = self.readop(operands[0])
            elif mnemonic in ("cmp", "sub", "add"):
                left = self.readop(operands[0])
                right = self.readop(operands[1])
                result = (left - right if mnemonic != "add" else left + right) & 0xFFFFFFFF
                self.math(left, right, result, operands[0].size, mnemonic in ("cmp", "sub"))
                if mnemonic != "cmp":
                    self.writeop(operands[0], result)
            elif mnemonic in ("test", "xor", "and"):
                left = self.readop(operands[0])
                right = self.readop(operands[1])
                result = left & right if mnemonic in ("test", "and") else left ^ right
                self.logic(result, operands[0].size)
                if mnemonic != "test":
                    self.writeop(operands[0], result)
            elif mnemonic == "neg":
                value = self.readop(operands[0])
                result = (-value) & 0xFFFFFFFF
                self.math(0, value, result, operands[0].size, True)
                self.writeop(operands[0], result)
            elif mnemonic == "inc":
                value = self.readop(operands[0])
                carry = self.f["c"]
                result = (value + 1) & 0xFFFFFFFF
                self.math(value, 1, result, operands[0].size, False)
                self.f["c"] = carry
                self.writeop(operands[0], result)
            elif mnemonic in ("shl", "shr"):
                value = self.readop(operands[0])
                count = self.readop(operands[1]) & 31
                bits = 8 * operands[0].size
                mask = (1 << bits) - 1
                if count:
                    self.f["c"] = bool((value >> (bits - count)) & 1) if mnemonic == "shl" else bool((value >> (count - 1)) & 1)
                    result = ((value << count) if mnemonic == "shl" else value >> count) & mask
                    self.writeop(operands[0], result)
                    self.f["z"] = result == 0
                    self.f["s"] = bool(result & (1 << (bits - 1)))
            elif mnemonic != "nop":
                raise RuntimeError(f"unsupported {ip:08X} {mnemonic} {insn.op_str}")
            ip = next_ip & 0xFFFFFFFF
        return ip


def main():
    record = STATE_DATA + 0x400
    machine = Machine()
    manager = 0x2000000
    machine.w32(SLOT, 0)
    machine.w32(SLOT + 4, 0)
    machine.w32(SLOT + 8, 0)
    machine.w32(record, 0xFFFFFFFF)
    memset = 0x5B2420
    stub = b"\xC3"
    machine.load(memset, stub)
    for insn in machine.md.disasm(stub, memset):
        machine.insns[insn.address] = insn
    machine.rw(X86_REG_EBP, manager)
    machine.rw(X86_REG_ECX, manager)
    stop = machine.run(MANIFEST["functions"]["loader_hook"], {0x538DD7})
    assert stop == 0x538DD7 and machine.read(CODE_BASE + 0x3000, 4) == STATE_DATA
    for index in range(8):
        expected_buffer = CODE_BASE + 0x5000 + index * 0x40000
        assert machine.read(manager + 0x2C + index * 4, 4) == expected_buffer
        assert machine.read(SLOT + index * 16, 4) == expected_buffer
        assert machine.read(SLOT + index * 16 + 8, 4) == 0x40000
    assert machine.read(STATE_DATA + 0xC00, 4) == 0
    print("loader buffers: PASS 8", "steps", machine.steps)

    buffer = CODE_BASE + 0x5000
    machine.load(buffer, SCRIPT)
    machine.rw(X86_REG_ESP, 0x800000)
    machine.w32(machine.rr(X86_REG_ESP), 0xDEADBEEF)
    machine.rw(X86_REG_EAX, buffer)
    machine.rw(X86_REG_EDX, len(SCRIPT))
    stop = machine.run(MANIFEST["functions"]["register_script"], {0xDEADBEEF}, max_steps=3000000)
    assert stop == 0xDEADBEEF and machine.rr(X86_REG_EAX) == buffer + 0x10912
    assert machine.read(SLOT + 4, 4) == buffer + 0x10912
    assert machine.read(STATE_DATA + 0x30, 4) == 0x10912
    print("register full script: PASS", "steps", machine.steps)

    machine = Machine()
    machine.rw(X86_REG_EBP, manager)
    machine.w32(manager + 0x2C, SCRIPT_BASE)
    machine.rw(X86_REG_ESI, len(SCRIPT))
    stop = machine.run(MANIFEST["functions"]["size_hook"], {0x538E5F, 0x53900F}, max_steps=3000000)
    assert stop == 0x538E5F and machine.read(SLOT + 4, 4) == SCRIPT_BASE + 0x10912
    print("extended size: PASS", "steps", machine.steps)

    machine = Machine()
    machine.rw(X86_REG_EAX, SCRIPT_BASE)
    machine.w32(machine.rr(X86_REG_ESP) + 0x10, manager)
    stop = machine.run(MANIFEST["functions"]["string_hook"], {0x5385B9})
    assert stop == 0x5385B9 and machine.rr(X86_REG_ECX) == 0x10566
    assert machine.rr(X86_REG_EAX) == manager
    print("string table: PASS", "steps", machine.steps)

    source_size = len(SCRIPT) - 24 - 88 * 4
    offsets = [int.from_bytes(SCRIPT[source_size + 4 * index:source_size + 4 * index + 4], "little")
               for index in range(88)]
    for index, expected in enumerate(offsets):
        machine = Machine()
        machine.rw(X86_REG_ECX, SCRIPT_BASE)
        machine.rw(X86_REG_ESI, index * 2)
        machine.rw(X86_REG_EDI, TASK_ID)
        stop = machine.run(MANIFEST["functions"]["init_hook"], {0x53A188})
        relative = machine.rr(X86_REG_EAX)
        assert stop == 0x53A188 and relative == 0x104B6 + index * 2
        assert machine.read(SCRIPT_BASE + relative, 2) == expected & 0xFFFF
        assert machine.read(record, 4) == TASK_ID and machine.read(record + 4, 4) == expected
        assert machine.read(SLOT + 4, 4) == SCRIPT_BASE + 0x10912
        if index in (71, 79, 80, 87):
            print("init", index, hex(relative), hex(expected), "steps", machine.steps)
    print("all init entries: PASS", len(offsets))

    for index in (71, 80):
        expected = offsets[index]
        machine = Machine()
        machine.rw(X86_REG_ECX, SCRIPT_BASE)
        machine.rw(X86_REG_EBP, index)
        machine.rw(X86_REG_ESI, TASK_ID)
        stop = machine.run(MANIFEST["functions"]["call_hook"], {0x53C0AC})
        values = (machine.read(record + 4, 4), machine.read(TASK_ID + 6, 2))
        print("call", index, hex(stop), tuple(hex(value) for value in values), "steps", machine.steps)
        assert stop == 0x53C0AC and values == (expected, expected & 0xFFFF)

    for index in (71, 79, 80, 87):
        expected = offsets[index]
        manager = 0x2000000
        machine = Machine()
        machine.w32(SLOT + 4, SCRIPT_BASE + 0x10912)
        machine.w32(manager + 0x2C, SCRIPT_BASE)
        machine.w32(record, TASK_ID)
        machine.w32(record + 4, expected)
        machine.write(TASK_ID + 2, 0, 1)
        machine.write(TASK_ID + 6, expected & 0xFFFF, 2)
        machine.write(TASK_ID + 10, 1, 1)
        machine.rw(X86_REG_ESI, TASK_ID)
        machine.rw(X86_REG_EDI, manager)
        stop = machine.run(MANIFEST["functions"]["prepare"], {0xDEADBEEF})
        active = STATE_DATA + 0xC00
        actual_base = machine.read(manager + 0x2C, 4)
        actual_opcode = machine.read(active + 24, 4)
        print("prepare", index, hex(actual_base), hex(actual_opcode), "steps", machine.steps)
        assert stop == 0xDEADBEEF and machine.read(active, 4) == 1
        assert actual_base == SCRIPT_BASE + (expected & 0xFFFF0000)
        assert actual_opcode == SCRIPT[expected]

    def dispatch_case(name, previous, new_low, expected, old_depth=1, new_depth=1,
                      call_index=None, return_page=None):
        machine = Machine()
        manager = 0x2000000
        machine.w32(SLOT + 4, SCRIPT_BASE + 0x10912)
        machine.w32(manager + 0x2C, SCRIPT_BASE)
        machine.w32(record, TASK_ID)
        machine.w32(record + 4, previous)
        machine.write(TASK_ID + 2, 0, 1)
        machine.write(TASK_ID + 6, previous & 0xFFFF, 2)
        machine.write(TASK_ID + 10, old_depth, 1)
        if return_page is not None:
            machine.w32(record + 8 + 4 * new_depth, return_page)
        machine.rw(X86_REG_ESI, TASK_ID)
        machine.rw(X86_REG_EDI, manager)
        machine.run(MANIFEST["functions"]["prepare"], {0xDEADBEEF})
        if call_index is not None:
            machine.rw(X86_REG_ECX, SCRIPT_BASE)
            machine.rw(X86_REG_EBP, call_index)
            machine.rw(X86_REG_ESI, TASK_ID)
            machine.run(MANIFEST["functions"]["call_hook"], {0x53C0AC})
        machine.write(TASK_ID + 6, new_low, 2)
        machine.write(TASK_ID + 10, new_depth, 1)
        handler = 0x4000000
        stub = b"\xC2\x04\x00"
        machine.load(handler, stub)
        for insn in machine.md.disasm(stub, handler):
            machine.insns[insn.address] = insn
        machine.w32(machine.rr(X86_REG_ESP), 0x53A016)
        machine.rw(X86_REG_EAX, handler)
        machine.rw(X86_REG_ESI, TASK_ID)
        machine.rw(X86_REG_EDI, manager)
        stop = machine.run(MANIFEST["functions"]["dispatch_hook"], {0x53A016})
        actual = machine.read(record + 4, 4)
        print("dispatch", name, hex(actual), "steps", machine.steps)
        assert stop == 0x53A016 and actual == expected
        assert machine.read(manager + 0x2C, 4) == SCRIPT_BASE
        assert machine.read(STATE_DATA + 0xC00, 4) == 0
        if call_index is not None:
            assert machine.read(record + 8 + 4 * old_depth, 4) == previous & 0xFFFF0000

    dispatch_case("normal", 0xF54D, 0xF550, 0xF550)
    dispatch_case("cross-page-jump", 0xFFD3, 0x81, 0x10081)
    dispatch_case("high-page", 0x10085, 0x88, 0x10088)
    dispatch_case("call", 0x9E4, offsets[9] & 0xFFFF, offsets[9],
                  old_depth=1, new_depth=2, call_index=9)
    dispatch_case("return", 0x1018C, 0xF550, 0xF550,
                  old_depth=2, new_depth=1, return_page=0)

    cases = [(0xFFD3, 0x81, 0x10081), (0xFFFF, 0, 0x10000),
             (0xFFD3, 0xFF59, 0xFF59), (0x10070, 0x85, 0x10085),
             (0xF54D, 0xF8B4, 0xF8B4)]
    for previous, low, expected in cases:
        machine = Machine()
        machine.w32(SLOT + 4, SCRIPT_BASE + 0x10912)
        machine.rw(X86_REG_ECX, SLOT)
        machine.rw(X86_REG_EAX, (previous & 0xFFFF0000) | low)
        machine.rw(X86_REG_EDX, previous)
        stop = machine.run(MANIFEST["functions"]["resolve_local"], {0xDEADBEEF})
        actual = machine.rr(X86_REG_EAX)
        print("resolve", hex(previous), hex(low), "->", hex(actual), "steps", machine.steps)
        assert stop == 0xDEADBEEF and actual == expected
    print("all emitted-code checks: PASS")


if __name__ == "__main__":
    main()
