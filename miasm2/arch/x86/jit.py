import logging

from miasm2.jitter.jitload import Jitter, named_arguments
from miasm2.core.utils import pck16, pck32, pck64, upck16, upck32, upck64
from miasm2.arch.x86.sem import ir_x86_16, ir_x86_32, ir_x86_64
from miasm2.jitter.codegen import CGen
from miasm2.core.locationdb import LocationDB
from miasm2.ir.translators.C import TranslatorC

log = logging.getLogger('jit_x86')
hnd = logging.StreamHandler()
hnd.setFormatter(logging.Formatter("[%(levelname)s]: %(message)s"))
log.addHandler(hnd)
log.setLevel(logging.CRITICAL)


class x86_32_CGen(CGen):
    def __init__(self, ir_arch):
        self.ir_arch = ir_arch
        self.PC = self.ir_arch.arch.regs.RIP
        self.translator = TranslatorC(self.ir_arch.loc_db)
        self.init_arch_C()

    def gen_post_code(self, attrib):
        out = []
        if attrib.log_regs:
            out.append('dump_gpregs_32(jitcpu->cpu);')
        return out

class x86_64_CGen(x86_32_CGen):
    def gen_post_code(self, attrib):
        out = []
        if attrib.log_regs:
            out.append('dump_gpregs_64(jitcpu->cpu);')
        return out

class jitter_x86_16(Jitter):

    C_Gen = x86_32_CGen

    def __init__(self, *args, **kwargs):
        sp = LocationDB()
        Jitter.__init__(self, ir_x86_16(sp), *args, **kwargs)
        self.vm.set_little_endian()
        self.ir_arch.do_stk_segm = False
        self.orig_irbloc_fix_regs_for_mode = self.ir_arch.irbloc_fix_regs_for_mode
        self.ir_arch.irbloc_fix_regs_for_mode = self.ir_archbloc_fix_regs_for_mode

    def ir_archbloc_fix_regs_for_mode(self, irblock, attrib=64):
        return self.orig_irbloc_fix_regs_for_mode(irblock, 64)

    def push_uint16_t(self, value):
        self.cpu.SP -= self.ir_arch.sp.size / 8
        self.vm.set_mem(self.cpu.SP, pck16(value))

    def pop_uint16_t(self):
        value = upck16(self.vm.get_mem(self.cpu.SP, self.ir_arch.sp.size / 8))
        self.cpu.SP += self.ir_arch.sp.size / 8
        return value

    def get_stack_arg(self, index):
        return upck16(self.vm.get_mem(self.cpu.SP + 4 * index, 4))

    def init_run(self, *args, **kwargs):
        Jitter.init_run(self, *args, **kwargs)
        self.cpu.IP = self.pc


class jitter_x86_32(Jitter):

    C_Gen = x86_32_CGen

    def __init__(self, *args, **kwargs):
        sp = LocationDB()
        Jitter.__init__(self, ir_x86_32(sp), *args, **kwargs)
        self.vm.set_little_endian()
        self.ir_arch.do_stk_segm = False

        self.orig_irbloc_fix_regs_for_mode = self.ir_arch.irbloc_fix_regs_for_mode
        self.ir_arch.irbloc_fix_regs_for_mode = self.ir_archbloc_fix_regs_for_mode

    def ir_archbloc_fix_regs_for_mode(self, irblock, attrib=64):
        return self.orig_irbloc_fix_regs_for_mode(irblock, 64)

    def push_uint16_t(self, value):
        self.cpu.ESP -= self.ir_arch.sp.size / 8
        self.vm.set_mem(self.cpu.ESP, pck16(value))

    def pop_uint16_t(self):
        value = upck16(self.vm.get_mem(self.cpu.ESP, self.ir_arch.sp.size / 8))
        self.cpu.ESP += self.ir_arch.sp.size / 8
        return value

    def push_uint32_t(self, value):
        self.cpu.ESP -= self.ir_arch.sp.size / 8
        self.vm.set_mem(self.cpu.ESP, pck32(value))

    def pop_uint32_t(self):
        value = upck32(self.vm.get_mem(self.cpu.ESP, self.ir_arch.sp.size / 8))
        self.cpu.ESP += self.ir_arch.sp.size / 8
        return value

    def get_stack_arg(self, index):
        return upck32(self.vm.get_mem(self.cpu.ESP + 4 * index, 4))

    def init_run(self, *args, **kwargs):
        Jitter.init_run(self, *args, **kwargs)
        self.cpu.EIP = self.pc

    # calling conventions

    # stdcall
    @named_arguments
    def func_args_stdcall(self, n_args):
        ret_ad = self.pop_uint32_t()
        args = [self.pop_uint32_t() for _ in xrange(n_args)]
        return ret_ad, args

    def func_ret_stdcall(self, ret_addr, ret_value1=None, ret_value2=None):
        self.pc = self.cpu.EIP = ret_addr
        if ret_value1 is not None:
            self.cpu.EAX = ret_value1
        if ret_value2 is not None:
            self.cpu.EDX = ret_value2

    def func_prepare_stdcall(self, ret_addr, *args):
        for arg in reversed(args):
            self.push_uint32_t(arg)
        self.push_uint32_t(ret_addr)

    get_arg_n_stdcall = get_stack_arg

    # cdecl
    @named_arguments
    def func_args_cdecl(self, n_args):
        ret_ad = self.pop_uint32_t()
        args = [self.get_stack_arg(i) for i in xrange(n_args)]
        return ret_ad, args

    def func_ret_cdecl(self, ret_addr, ret_value1=None, ret_value2=None):
        self.pc = self.cpu.EIP = ret_addr
        if ret_value1 is not None:
            self.cpu.EAX = ret_value1
        if ret_value2 is not None:
            self.cpu.EDX = ret_value2

    get_arg_n_cdecl = get_stack_arg

    # System V
    func_args_systemv = func_args_cdecl
    func_ret_systemv = func_ret_cdecl
    func_prepare_systemv = func_prepare_stdcall
    get_arg_n_systemv = get_stack_arg


    # fastcall
    @named_arguments
    def func_args_fastcall(self, n_args):
        args_regs = ['ECX', 'EDX']
        ret_ad = self.pop_uint32_t()
        args = []
        for i in xrange(n_args):
            args.append(self.get_arg_n_fastcall(i))
        return ret_ad, args

    def func_prepare_fastcall(self, ret_addr, *args):
        args_regs = ['ECX', 'EDX']
        for i in xrange(min(len(args), len(args_regs))):
            setattr(self.cpu, args_regs[i], args[i])
        remaining_args = args[len(args_regs):]
        for arg in reversed(remaining_args):
            self.push_uint32_t(arg)
        self.push_uint32_t(ret_addr)

    def get_arg_n_fastcall(self, index):
        args_regs = ['ECX', 'EDX']
        if index < len(args_regs):
            return getattr(self.cpu, args_regs[index])
        return self.get_stack_arg(index - len(args_regs))



class jitter_x86_64(Jitter):

    C_Gen = x86_64_CGen
    args_regs_systemv = ['RDI', 'RSI', 'RDX', 'RCX', 'R8', 'R9']
    args_regs_stdcall = ['RCX', 'RDX', 'R8', 'R9']

    def __init__(self, *args, **kwargs):
        sp = LocationDB()
        Jitter.__init__(self, ir_x86_64(sp), *args, **kwargs)
        self.vm.set_little_endian()
        self.ir_arch.do_stk_segm = False

        self.orig_irbloc_fix_regs_for_mode = self.ir_arch.irbloc_fix_regs_for_mode
        self.ir_arch.irbloc_fix_regs_for_mode = self.ir_archbloc_fix_regs_for_mode

    def ir_archbloc_fix_regs_for_mode(self, irblock, attrib=64):
        return self.orig_irbloc_fix_regs_for_mode(irblock, 64)

    def push_uint64_t(self, value):
        self.cpu.RSP -= self.ir_arch.sp.size / 8
        self.vm.set_mem(self.cpu.RSP, pck64(value))

    def pop_uint64_t(self):
        value = upck64(self.vm.get_mem(self.cpu.RSP, self.ir_arch.sp.size / 8))
        self.cpu.RSP += self.ir_arch.sp.size / 8
        return value

    def get_stack_arg(self, index):
        return upck64(self.vm.get_mem(self.cpu.RSP + 8 * index, 8))

    def init_run(self, *args, **kwargs):
        Jitter.init_run(self, *args, **kwargs)
        self.cpu.RIP = self.pc

    # calling conventions

    # stdcall
    @named_arguments
    def func_args_stdcall(self, n_args):
        args_regs = self.args_regs_stdcall
        ret_ad = self.pop_uint64_t()
        args = []
        for i in xrange(min(n_args, 4)):
            args.append(self.cpu.get_gpreg()[args_regs[i]])
        for i in xrange(max(0, n_args - 4)):
            args.append(self.get_stack_arg(i))
        return ret_ad, args

    def func_prepare_stdcall(self, ret_addr, *args):
        args_regs = self.args_regs_stdcall
        for i in xrange(min(len(args), len(args_regs))):
            setattr(self.cpu, args_regs[i], args[i])
        remaining_args = args[len(args_regs):]
        for arg in reversed(remaining_args):
            self.push_uint64_t(arg)
        self.push_uint64_t(ret_addr)

    def func_ret_stdcall(self, ret_addr, ret_value=None):
        self.pc = self.cpu.RIP = ret_addr
        if ret_value is not None:
            self.cpu.RAX = ret_value
        return True

    # cdecl
    func_args_cdecl = func_args_stdcall
    func_ret_cdecl = func_ret_stdcall
    func_prepare_cdecl = func_prepare_stdcall

    # System V

    def get_arg_n_systemv(self, index):
        args_regs = self.args_regs_systemv
        if index < len(args_regs):
            return getattr(self.cpu, args_regs[index])
        return self.get_stack_arg(index - len(args_regs))

    @named_arguments
    def func_args_systemv(self, n_args):
        ret_ad = self.pop_uint64_t()
        args = [self.get_arg_n_systemv(index) for index in xrange(n_args)]
        return ret_ad, args

    func_ret_systemv = func_ret_cdecl

    def func_prepare_systemv(self, ret_addr, *args):
        args_regs = self.args_regs_systemv
        self.push_uint64_t(ret_addr)
        for i in xrange(min(len(args), len(args_regs))):
            setattr(self.cpu, args_regs[i], args[i])
        remaining_args = args[len(args_regs):]
        for arg in reversed(remaining_args):
            self.push_uint64_t(arg)
