#!/usr/bin/env python3
"""Restore conditional PPC branches misclassified by ReXGlue v0.10.0.

The generator can emit an ``Unresolved branch`` fatal even though its target
label is already in the same C++ function. Unconditional branches to that label
are emitted correctly. Repair only conditional branches whose instruction,
condition register, and function-local label all agree; other traps stay intact.
This also works on reused port-src artifacts without re-running codegen.
"""
import argparse
import re
from dataclasses import dataclass
from pathlib import Path


FUNCTION = re.compile(r"^DEFINE_REX_FUNC\((\w+)\)\s*\{")
LABEL = re.compile(r"^[ \t]*loc_([0-9A-Fa-f]{8}):[ \t]*$")
TRAP = re.compile(
    r"(?P<indent>[ \t]*)if \((?P<condition>!?ctx\.cr[0-7]\.(?:eq|lt|gt|so))\) "
    r'REX_FATAL\("Unresolved branch from 0x(?P<source>[0-9A-Fa-f]{8}) '
    r'to 0x(?P<target>[0-9A-Fa-f]{8})"\);[ \t]*'
)
INSTRUCTION = re.compile(
    r"[ \t]*// (?P<opcode>b(?:eq|ne|lt|ge|gt|le|so|ns)) "
    r"(?:(?P<cr>cr[0-7]),)?0x(?P<target>[0-9A-Fa-f]{8})[ \t]*"
)
DIAGNOSTIC = re.compile(
    r"[ \t]*// ERROR: conditional branch to unknown address "
    r"0x(?P<target>[0-9A-Fa-f]{8})[ \t]*"
)
CONDITIONS = {
    "beq": "eq", "bne": "!eq", "blt": "lt", "bge": "!lt",
    "bgt": "gt", "ble": "!gt", "bso": "so", "bns": "!so",
}


@dataclass(frozen=True)
class Fix:
    function: str
    source: int
    target: int


def _line_ending(line):
    return line[len(line.rstrip("\r\n")):]


def repair_text(contents):
    """Return repaired source and verified sites, keeping unrelated bytes intact."""
    lines = contents.splitlines(keepends=True)
    functions = [(i, m.group(1)) for i, line in enumerate(lines)
                 if (m := FUNCTION.match(line))]
    fixes = []
    for fi, (start, name) in enumerate(functions):
        end = functions[fi + 1][0] if fi + 1 < len(functions) else len(lines)
        labels = {}
        for line in lines[start:end]:
            if (m := LABEL.fullmatch(line.rstrip("\r\n"))):
                labels[int(m.group(1), 16)] = m.group(1)
        for i in range(start + 1, end):
            m = TRAP.fullmatch(lines[i].rstrip("\r\n"))
            if not m:
                continue
            target = int(m.group("target"), 16)
            if target not in labels:
                continue
            instruction_line = i - 1
            diagnostic = DIAGNOSTIC.fullmatch(lines[instruction_line].rstrip("\r\n"))
            if diagnostic:
                if int(diagnostic.group("target"), 16) != target:
                    continue
                instruction_line -= 1
            if instruction_line <= start:
                continue
            instruction = INSTRUCTION.fullmatch(lines[instruction_line].rstrip("\r\n"))
            if not instruction or int(instruction.group("target"), 16) != target:
                continue
            condition = CONDITIONS[instruction.group("opcode")]
            negate = "!" if condition.startswith("!") else ""
            cr = instruction.group("cr") or "cr0"
            expected = "%sctx.%s.%s" % (negate, cr, condition.lstrip("!"))
            if m.group("condition") != expected:
                continue
            indent = m.group("indent")
            lines[i] = ("%sif (%s) goto loc_%s;  // rexauto: restored local branch%s"
                        % (indent, expected, labels[target], _line_ending(lines[i])))
            if diagnostic:
                lines[i - 1] = ("%s// rexauto: conditional target is a label in this function%s"
                                % (indent, _line_ending(lines[i - 1])))
            fixes.append(Fix(name, int(m.group("source"), 16), target))
    return "".join(lines), fixes


def repair_port(port, check=False):
    generated = Path(port) / "generated"
    if not generated.is_dir():
        raise SystemExit("no generated sources at %s" % generated)
    total = 0
    for module in sorted(generated.iterdir()):
        if not module.is_dir() or module.name.endswith("_scan"):
            continue
        module_fixes = []
        for path in sorted(module.glob("*_recomp.*.cpp")):
            original = path.read_bytes().decode("utf-8")
            repaired, fixes = repair_text(original)
            if fixes:
                if not check:
                    path.write_bytes(repaired.encode("utf-8"))
                module_fixes.extend(fixes)
        if module_fixes:
            print("%s: %d %s local conditional branches" %
                  (module.name, len(module_fixes), "unrepaired" if check else "restored"))
            for fix in module_fixes[:8]:
                print("  %s: 0x%08X -> 0x%08X" %
                      (fix.function, fix.source, fix.target))
        total += len(module_fixes)
    print("local branch repair: %d %s" % (total, "pending" if check else "fixed"))
    return total


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", help="unpacked port-src directory")
    parser.add_argument("--check", action="store_true", help="fail if a repair is still needed")
    args = parser.parse_args()
    count = repair_port(args.port, check=args.check)
    return 1 if args.check and count else 0


if __name__ == "__main__":
    raise SystemExit(main())
