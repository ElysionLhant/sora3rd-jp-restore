from pathlib import Path
import argparse
import capstone
import hashlib
import json
import re
import struct


def load_pe(path):
    data = path.read_bytes()
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    count = struct.unpack_from("<H", data, pe + 6)[0]
    optional = struct.unpack_from("<H", data, pe + 20)[0]
    image_base = struct.unpack_from("<I", data, pe + 52)[0]
    section_table = pe + 24 + optional
    sections = []
    for index in range(count):
        pos = section_table + index * 40
        name = data[pos:pos + 8].rstrip(b"\0").decode("ascii")
        virtual_size, rva, raw_size, raw = struct.unpack_from("<IIII", data, pos + 8)
        sections.append({"name": name, "rva": rva, "virtual_size": virtual_size,
                         "raw": raw, "raw_size": raw_size, "data": data[raw:raw + raw_size]})
    return data, image_base, sections


def instruction(instruction):
    return {"address": instruction.address, "mnemonic": instruction.mnemonic, "op_str": instruction.op_str}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("file", type=Path)
    parser.add_argument("--disasm", type=lambda value: int(value, 0))
    parser.add_argument("--end", type=lambda value: int(value, 0))
    parser.add_argument("--strings", action="store_true")
    parser.add_argument("--scan", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    data, base, sections = load_pe(args.file)
    report = {"path": str(args.file), "sha256": hashlib.sha256(data).hexdigest(),
              "image_base": base, "sections": [{k: v for k, v in sec.items() if k != "data"} for sec in sections]}
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    md.skipdata = True
    if args.strings:
        for match in re.finditer(rb"[\x20-\x7e]{4,}", data):
            text = match.group().decode("ascii")
            if re.search(r"(?:\._SN|scenario|scena|10000|ffff|64k|65536)", text, re.I):
                report.setdefault("strings", []).append({"file_offset": match.start(), "text": text})
    if args.scan:
        targets = {0xff00, 0xfffe, 0xffff, 0x10000, 0x10001, 0x1ff00, 0x20000}
        hits = []
        word_loads = []
        for sec in sections:
            if sec["name"] != ".text":
                continue
            va = base + sec["rva"]
            previous = None
            context = []
            for insn in md.disasm(sec["data"], va):
                if insn.address != previous:
                    context = []
                context.append(insn)
                context = context[-9:]
                previous = insn.address + insn.size
                if insn.id == 0:
                    continue
                for op in insn.operands:
                    if op.type == capstone.x86.X86_OP_IMM and op.imm in targets:
                        hits.append({"immediate": op.imm, "context": [instruction(i) for i in context]})
                if insn.mnemonic in ("movzx", "movsx") and "word ptr" in insn.op_str:
                    for op in insn.operands[1:]:
                        if op.type == capstone.x86.X86_OP_MEM and op.mem.scale == 2 and op.mem.index != 0:
                            word_loads.append({"context": [instruction(i) for i in context]})
        report["immediate_count"] = len(hits)
        report["immediate_counts"] = {hex(target): sum(h["immediate"] == target for h in hits) for target in sorted(targets)}
        report["immediate_hits"] = hits
        report["indexed_word_load_count"] = len(word_loads)
        report["indexed_word_loads"] = word_loads
    if args.disasm is not None:
        for sec in sections:
            va = base + sec["rva"]
            if va <= args.disasm < va + len(sec["data"]):
                start = args.disasm - va
                end = (args.end or args.disasm + 256) - va
                report["disassembly"] = [instruction(i) for i in md.disasm(sec["data"][start:end], args.disasm)]
                break
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
        print(json.dumps({key: value for key, value in report.items() if key not in ("immediate_hits", "indexed_word_loads", "disassembly")}, indent=2))
    else:
        print(text)


if __name__ == "__main__":
    main()
