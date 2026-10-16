import unittest

from fix_local_branches import repair_text


def source(instruction="bne cr6,0x826d38e8", condition="!ctx.cr6.eq",
           target="826D38E8", label="826D38E8"):
    return ("DEFINE_REX_FUNC(sub_826D3620) {\n"
            "\t// %s\n"
            "\t// ERROR: conditional branch to unknown address 0x%s\n"
            '\tif (%s) REX_FATAL("Unresolved branch from 0x826D3888 to 0x%s");\n'
            "\tctx.r11.s64 = 3;\n"
            "loc_%s:\n"
            "\tctx.r3.u64 = ctx.r11.u64;\n"
            "\treturn;\n"
            "}\n") % (instruction, target, condition, target, label)


class LocalBranchTests(unittest.TestCase):
    def test_restores_conditional_jump_and_preserves_fallthrough(self):
        original = source()
        repaired, fixes = repair_text(original)
        self.assertEqual([(f.source, f.target) for f in fixes], [(0x826D3888, 0x826D38E8)])
        self.assertIn("if (!ctx.cr6.eq) goto loc_826D38E8;", repaired)
        self.assertNotIn("REX_FATAL", repaired)
        self.assertEqual(repaired[repaired.index("\tctx.r11.s64"):],
                         original[original.index("\tctx.r11.s64"):])

    def test_never_jumps_to_label_in_another_function(self):
        original = source(label="826D38E4") + (
            "DEFINE_REX_FUNC(sub_826D3900) {\nloc_826D38E8:\n\treturn;\n}\n")
        self.assertEqual(repair_text(original), (original, []))

    def test_requires_agreement_with_guest_instruction(self):
        for original in (source(instruction="bne cr6,0x826d38e4"),
                         source(condition="ctx.cr6.eq"),
                         source(instruction="bne cr7,0x826d38e8"),
                         source(instruction="bl 0x826d38e8")):
            with self.subTest(original=original):
                self.assertEqual(repair_text(original), (original, []))

    def test_preserves_crlf_and_is_idempotent(self):
        repaired, fixes = repair_text(source().replace("\n", "\r\n"))
        self.assertEqual(len(fixes), 1)
        self.assertNotIn("\n", repaired.replace("\r\n", ""))
        self.assertEqual(repair_text(repaired), (repaired, []))

    def test_handles_implicit_cr0_and_trap_without_diagnostic(self):
        original = source(instruction="beq 0x826d38e8", condition="ctx.cr0.eq")
        original = original.replace(
            "\t// ERROR: conditional branch to unknown address 0x826D38E8\n", "")
        repaired, fixes = repair_text(original)
        self.assertEqual(len(fixes), 1)
        self.assertIn("if (ctx.cr0.eq) goto loc_826D38E8;", repaired)


if __name__ == "__main__":
    unittest.main()
