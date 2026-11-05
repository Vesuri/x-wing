"""Conservative DX liveness within one basic block.

Unknown instructions/runtime boundaries read DX. Copied from Secret Weapons of the
Luftwaffe (commit pinned in manifest/references.tsv); X-Wing adds the 186+
three-operand imul, which writes only its destination. All block entries/exits keep
the ordinary register contract. No profile observations participate in proof.
"""
from .decode import Mem, Reg

EXPLICIT_READERS = frozenset({'push', 'xchg', 'add', 'adc', 'sub', 'sbb', 'and',
    'or', 'xor', 'cmp', 'test', 'inc', 'dec', 'neg', 'not', 'rol', 'ror', 'rcl',
    'rcr', 'shl', 'shr', 'sar', 'nop'})


def touches_dx(operand):
    return (isinstance(operand, Reg) and operand.name in ('dx', 'dh', 'dl') or
            isinstance(operand, Mem) and 'dx' in (operand.base, operand.index))


def transfer_dx(i, live, context):
    if context.vram:
        return True
    if i.op == 'cwd':
        return False
    if i.op == 'imul' and len(i.operands) == 3:  # 186+ imul r16,r/m16,imm: no DX:AX
        dest = i.operands[0]
        full = dest.name == 'dx'
        return touches_dx(i.operands[1]) or live and not full
    if i.op in ('mul', 'imul'):
        return any(touches_dx(o) for o in i.operands) or (live if i.width == 8 else False)
    if i.op in ('mov', 'lea', 'pop'):
        dest = i.operands[0]
        read = any(touches_dx(o) for o in i.operands[1:])
        full = isinstance(dest, Reg) and dest.name == 'dx' and i.width == 16
        return read or live and not full
    if i.op in EXPLICIT_READERS:
        return live or any(touches_dx(o) for o in i.operands)
    # In particular, division can trap: its handler observes the input DX.
    return True


def dead_dx(insns, leaders, contexts):
    result, live = [False] * len(insns), True
    for k in reversed(range(len(insns))):
        if k + 1 in leaders:
            live = True
        result[k] = not live
        live = transfer_dx(insns[k], live, contexts[k])
    return result
