# CHIPSEC: Platform Security Assessment Framework
# Copyright (c) 2010-2021, Intel Corporation
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; Version 2.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
#
# Contact information:
# chipsec@intel.com
#


"""
CPU SMM Cache Poisoning / System Management Range Registers check

This module checks to see that SMRRs are enabled and configured.

Reference:
    Researchers demonstrated a way to use CPU cache to effectively change values in SMRAM in
    `Attacking SMM Memory via Intel CPU Cache Poisoning <http://www.invisiblethingslab.com/resources/misc09/smm_cache_fun.pdf>`_
    and `Getting into the SMRAM: SMM Reloaded <http://cansecwest.com/csw09/csw09-duflot.pdf>`_ .
    If ring 0 software can make SMRAM cacheable and then populate cache lines at SMBASE with exploit code,
    then when an SMI is triggered, the CPU could execute the exploit code from cache.
    System Management Mode Range Registers (SMRRs) force non-cachable behavior and block access to SMRAM when the CPU is not in SMM.
    These registers need to be enabled/configured by the BIOS.

Usage:
    ``chipsec_main -m common.smrr [-a modify]``

    - ``-a modify``: Attempt to modify memory at SMRR base

Examples:
    >>> chipsec_main.py -m common.smrr
    >>> chipsec_main.py -m common.smrr -a modify

Registers used:
    - IA32_SMRR_PHYSBASE.PhysBase
    - IA32_SMRR_PHYSBASE.Type
    - IA32_SMRR_PHYSMASK.PhysMask
    - IA32_SMRR_PHYSMASK.Valid

"""

from chipsec.module_common import BaseModule, ModuleResult, MTAG_BIOS, MTAG_SMM, OPT_MODIFY
from chipsec.hal.msr import MemType

TAGS = [MTAG_BIOS, MTAG_SMM]


class smrr(BaseModule):

    def __init__(self):
        BaseModule.__init__(self)
        self.rc_res = ModuleResult(0xdf11080, 'https://chipsec.github.io/modules/chipsec.modules.common.smrr.html')

    def is_supported(self):
        mtrr_exist = self.cs.is_register_defined('MTRRCAP')
        pbase_exist = self.cs.is_register_defined('IA32_SMRR_PHYSBASE')
        pmask_exist = self.cs.is_register_defined('IA32_SMRR_PHYSMASK')
        if mtrr_exist and pbase_exist and pmask_exist:
            return True
        self.logger.log_information('Required registers are not defined for this platform.  Skipping module.')
        self.rc_res.setStatusBit(self.rc_res.status.NOT_APPLICABLE)
        self.res = self.rc_res.getReturnCode(ModuleResult.NOTAPPLICABLE)
        return False

    #
    # Check that SMRR are supported by CPU in IA32_MTRRCAP_MSR[SMRR]
    #
    def check_SMRR(self, do_modify):

        if self.cs.cpu.check_SMRR_supported():
            self.logger.log_good("OK. SMRR range protection is supported")
        else:
            self.logger.log_not_applicable("CPU does not support SMRR range protection of SMRAM")
            self.rc_res.setStatusBit(self.rc_res.status.NOT_APPLICABLE)
            self.res = self.rc_res.getReturnCode(ModuleResult.NOTAPPLICABLE)
        #
        # SMRR are supported
        #
        smrr_ok = True

        #
        # 2. Check SMRR_BASE is programmed correctly (on CPU0)
        #
        self.logger.log('')
        self.logger.log("[*] Checking SMRR range base programming..")
        msr_smrrbase = self.cs.read_register('IA32_SMRR_PHYSBASE')
        self.cs.print_register('IA32_SMRR_PHYSBASE', msr_smrrbase)
        smrrbase = self.cs.get_register_field('IA32_SMRR_PHYSBASE', msr_smrrbase, 'PhysBase', True)
        smrrtype = self.cs.get_register_field('IA32_SMRR_PHYSBASE', msr_smrrbase, 'Type')
        self.logger.log("[*] SMRR range base: 0x{:016X}".format(smrrbase))

        if smrrtype in MemType:
            self.logger.log("[*] SMRR range memory type is {}".format(MemType[smrrtype]))
        else:
            smrr_ok = False
            self.logger.log_bad("SMRR range memory type 0x{:X} is invalid".format(smrrtype))

        if 0 == smrrbase:
            smrr_ok = False
            self.logger.log_bad("SMRR range base is not programmed")

        if smrr_ok:
            self.logger.log_good("OK so far. SMRR range base is programmed")

        #
        # 3. Check SMRR_MASK is programmed and SMRR are enabled (on CPU0)
        #
        self.logger.log('')
        self.logger.log("[*] Checking SMRR range mask programming..")
        msr_smrrmask = self.cs.read_register('IA32_SMRR_PHYSMASK')
        self.cs.print_register('IA32_SMRR_PHYSMASK', msr_smrrmask)
        smrrmask = self.cs.get_register_field('IA32_SMRR_PHYSMASK', msr_smrrmask, 'PhysMask', True)
        smrrvalid = self.cs.get_register_field('IA32_SMRR_PHYSMASK', msr_smrrmask, 'Valid')
        self.logger.log("[*] SMRR range mask: 0x{:016X}".format(smrrmask))

        if not (smrrvalid and (0 != smrrmask)):
            smrr_ok = False
            self.logger.log_bad("SMRR range is not enabled")

        if smrr_ok:
            self.logger.log_good("OK so far. SMRR range is enabled")

        #
        # 4. Verify that SMRR_BASE/MASK MSRs have the same values on all logical CPUs
        #
        self.logger.log('')
        self.logger.log("[*] Verifying that SMRR range base & mask are the same on all logical CPUs..")
        for tid in range(self.cs.msr.get_cpu_thread_count()):
            msr_base = self.cs.read_register('IA32_SMRR_PHYSBASE', tid)
            msr_mask = self.cs.read_register('IA32_SMRR_PHYSMASK', tid)
            self.logger.log("[CPU{:d}] SMRR_PHYSBASE = {:016X}, SMRR_PHYSMASK = {:016X}".format(tid, msr_base, msr_mask))
            if (msr_base != msr_smrrbase) or (msr_mask != msr_smrrmask):
                smrr_ok = False
                self.logger.log_bad("SMRR range base/mask do not match on all logical CPUs")
                break

        if smrr_ok:
            self.logger.log_good("OK so far. SMRR range base/mask match on all logical CPUs")

        #
        # 5. Reading from & writing to SMRR_BASE physical address
        # writes should be dropped, reads should return all F's
        #

        self.logger.log("[*] Trying to read memory at SMRR base 0x{:08X}..".format(smrrbase))

        ok = 0xFFFFFFFF == self.cs.mem.read_physical_mem_dword(smrrbase)
        smrr_ok = smrr_ok and ok
        if ok:
            self.logger.log_passed("SMRR reads are blocked in non-SMM mode")  # return all F's
        else:
            self.logger.log_failed("SMRR reads are not blocked in non-SMM mode")  # all F's are not returned

        if (do_modify):
            self.logger.log("[*] Trying to modify memory at SMRR base 0x{:08X}..".format(smrrbase))
            self.cs.mem.write_physical_mem_dword(smrrbase, 0x90909090)
            ok = 0x90909090 != self.cs.mem.read_physical_mem_dword(smrrbase)
            smrr_ok = smrr_ok and ok
            if ok:
                self.logger.log_good("SMRR writes are blocked in non-SMM mode")
            else:
                self.logger.log_bad("SMRR writes are not blocked in non-SMM mode")

        self.logger.log('')
        if not smrr_ok:
            res = ModuleResult.FAILED
            self.rc_res.setStatusBit(self.rc_res.status.CONFIGURATION)
            self.logger.log_failed("SMRR protection against cache attack is not configured properly")
        else:
            res = ModuleResult.PASSED
            self.logger.log_passed("SMRR protection against cache attack is properly configured")

        return self.rc_res.getReturnCode(res)

    # --------------------------------------------------------------------------
    # run( module_argv )
    # Required function: run here all tests from this module
    # --------------------------------------------------------------------------
    def run(self, module_argv):
        self.logger.start_test("CPU SMM Cache Poisoning / System Management Range Registers")
        do_modify = (len(module_argv) > 0) and (module_argv[0] == OPT_MODIFY)
        self.res = self.check_SMRR(do_modify)
        return self.res
