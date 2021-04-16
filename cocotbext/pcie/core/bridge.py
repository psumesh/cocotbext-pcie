"""

Copyright (c) 2020 Alex Forencich

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.

"""

from .function import Function
from .port import Port, BusPort
from .tlp import Tlp, TlpType
from .utils import byte_mask_update, PcieId


class Bridge(Function):
    """PCIe bridge function, implements bridge config space and TLP routing"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # configuration registers
        # Header type
        self.header_layout = 1
        self.multifunction_device = False
        # Base Address Registers
        self.bar = [0]*2
        self.bar_mask = [0]*2
        # Primary bus number
        self.pri_bus_num = 0
        # Secondary bus number
        self.sec_bus_num = 0
        # Subordinate bus number
        self.sub_bus_num = 0
        # Secondary latency timer
        self.sec_lat_timer = 0
        # IO base and limit registers
        self.io_base = 0x0000
        self.io_limit = 0x0fff
        self.io_addr_capability = 0x1
        # Secondary status
        self.master_data_parity_error = False
        self.signaled_target_abort = False
        self.received_target_abort = False
        self.received_master_abort = False
        self.received_system_error = False
        self.detected_parity_error = False
        # Memory and limit registers
        self.mem_base = 0x00000000
        self.mem_limit = 0x000fffff
        self.prefetchable_mem_base = 0x00000000
        self.prefetchable_mem_limit = 0x000fffff
        # Bridge control
        self.parity_error_response_enable = 0
        self.serr_enable = 0
        self.secondary_bus_reset = 0

        self.class_code = 0x060400
        self.pcie_device_type = 0x6

        self.root = False

        self.upstream_port = Port(self, self.upstream_recv)
        self.upstream_tx_handler = self.upstream_port.send

        self.downstream_port = Port(self, self.downstream_recv)
        self.downstream_tx_handler = self.downstream_port.send

    """
    Bridge (type 1) config space

    31                                                                  0
    +---------------------------------+---------------------------------+
    |            Device ID            |            Vendor ID            |   0   0x00
    +---------------------------------+---------------------------------+
    |             Status              |             Command             |   1   0x04
    +---------------------------------+----------------+----------------+
    |                    Class Code                    |  Revision ID   |   2   0x08
    +----------------+----------------+----------------+----------------+
    |      BIST      |  Header Type   |    Primary     |   Cache Line   |   3   0x0C
    |                |                | Latency Timer  |      Size      |
    +----------------+----------------+----------------+----------------+
    |                      Base Address Register 0                      |   4   0x10
    +-------------------------------------------------------------------+
    |                      Base Address Register 1                      |   5   0x14
    +----------------+----------------+----------------+----------------+
    | Secondary      | Subordinate    | Secondary      | Primary        |   6   0x18
    | Latency Timer  | Bus Number     | Bus Number     | Bus Number     |
    +----------------+----------------+----------------+----------------+
    |        Secondary Status         |    IO Limit    |    IO Base     |   7   0x1C
    +---------------------------------+----------------+----------------+
    |          Memory Limit           |           Memory Base           |   8   0x20
    +---------------------------------+---------------------------------+
    |    Prefetchable Memory Limit    |    Prefetchable Memory Base     |   9   0x24
    +---------------------------------+---------------------------------+
    |                    Prefetchable Base Upper 32                     |  10   0x28
    +-------------------------------------------------------------------+
    |                    Prefetchable Limit Upper 32                    |  11   0x2C
    +---------------------------------+---------------------------------+
    |         IO Lim Upper 16         |        IO Base Lower 16         |  12   0x30
    +---------------------------------+----------------+----------------+
    |                     Reserved                     |    Cap Ptr     |  13   0x34
    +--------------------------------------------------+----------------+
    |                    Expansion ROM Base Address                     |  14   0x38
    +---------------------------------+----------------+----------------+
    |         Bridge Control          |    Int Pin     |    Int Line    |  15   0x3C
    +---------------------------------+----------------+----------------+

    """
    async def read_config_register(self, reg):
        if reg == 4:
            # Base Address Register 0
            return self.bar[0]
        elif reg == 5:
            # Base Address Register 1
            return self.bar[1]
        elif reg == 6:
            # Primary bus number
            val = self.pri_bus_num & 0xff
            # Secondary bus number
            val |= (self.sec_bus_num & 0xff) << 8
            # Subordinate bus number
            val |= (self.sub_bus_num & 0xff) << 16
            # Secondary latency timer
            val |= (self.sec_lat_timer & 0xff) << 24
            return val
        elif reg == 7:
            # IO base
            val = self.io_addr_capability & 0xf
            val |= (self.io_base & 0xf000) >> 8
            # IO limit
            val |= (self.io_addr_capability & 0xf) << 8
            val |= self.io_limit & 0xf000
            # Secondary status
            val |= bool(self.master_data_parity_error) << 24
            val |= bool(self.signaled_target_abort) << 27
            val |= bool(self.received_target_abort) << 28
            val |= bool(self.received_master_abort) << 29
            val |= bool(self.received_system_error) << 30
            val |= bool(self.detected_parity_error) << 31
            return val
        elif reg == 8:
            # Memory base
            val = (self.mem_base & 0xfff00000) >> 16
            # Memory limit
            val |= self.mem_limit & 0xfff00000
            return val
        elif reg == 9:
            # Prefetchable memory base
            val = (self.prefetchable_mem_base & 0xfff00000) >> 16
            # Prefetchable memory limit
            val |= self.prefetchable_mem_limit & 0xfff00000
            return val
        elif reg == 10:
            # Prefetchable memory base (upper)
            return (self.prefetchable_mem_base >> 32) & 0xffffffff
        elif reg == 11:
            # Prefetchable memory limit (upper)
            return (self.prefetchable_mem_limit >> 32) & 0xffffffff
        elif reg == 12:
            # IO base (upper)
            val = (self.io_base & 0xffff0000) >> 16
            # IO limit (upper)
            val |= self.io_limit & 0xffff0000
            return val
        elif reg == 13:
            # Capabilities pointer
            return self.capabilities_ptr
        elif reg == 14:
            # Expansion ROM Base Address
            val = bool(self.expansion_rom_enable)
            val |= self.expansion_rom_addr & 0xfffff800
            return val
        elif reg == 15:
            # Interrupt line
            val = self.interrupt_line & 0xff
            # Interrupt pin
            val |= (self.interrupt_pin & 0xff) << 8
            # Bridge control
            val |= bool(self.parity_error_response_enable) << 16
            val |= bool(self.serr_enable) << 17
            val |= bool(self.secondary_bus_reset) << 22
            return val
        else:
            return await super().read_config_register(reg)

    async def write_config_register(self, reg, data, mask):
        if reg == 4:
            # Base Address Register 0
            self.bar[0] = byte_mask_update(self.bar[0], mask, data, self.bar_mask[0])
        if reg == 5:
            # Base Address Register 1
            self.bar[1] = byte_mask_update(self.bar[1], mask, data, self.bar_mask[1])
        elif reg == 6:
            # Primary bus number
            if mask & 0x1:
                self.pri_bus_num = data & 0xff
            # Secondary bus number
            if mask & 0x2:
                self.sec_bus_num = (data >> 8) & 0xff
            # Subordinate bus number
            if mask & 0x4:
                self.sub_bus_num = (data >> 16) & 0xff
        elif reg == 7:
            # IO base
            if mask & 0x1:
                self.io_base = byte_mask_update(self.io_base, 0x2, data << 8, 0xf000)
            # IO limit
            if mask & 0x2:
                self.io_limit = byte_mask_update(self.io_limit, 0x2, data, 0xf000) | 0xfff
            if mask & 0x8:
                # Secondary status
                if data & 1 << 24:
                    self.master_data_parity_error = False
                if data & 1 << 27:
                    self.signaled_target_abort = False
                if data & 1 << 28:
                    self.received_target_abort = False
                if data & 1 << 29:
                    self.received_master_abort = False
                if data & 1 << 30:
                    self.received_system_error = False
                if data & 1 << 31:
                    self.detected_parity_error = False
        elif reg == 8:
            # Memory base
            self.mem_base = byte_mask_update(self.mem_base, (mask & 0x3) << 2, data << 16, 0xfff00000)
            # Memory limit
            self.mem_limit = byte_mask_update(self.mem_limit, (mask & 0xc), data, 0xfff00000) | 0xfffff
        elif reg == 9:
            # Prefetchable memory base
            self.prefetchable_mem_base = byte_mask_update(self.prefetchable_mem_base,
                (mask & 0x3) << 2, data << 16, 0xfff00000)
            # Prefetchable memory limit
            self.prefetchable_mem_limit = byte_mask_update(self.prefetchable_mem_limit,
                (mask & 0xc), data, 0xfff00000) | 0xfffff
        elif reg == 10:
            # Prefetchable memory base (upper)
            self.prefetchable_mem_base = byte_mask_update(self.prefetchable_mem_base, mask << 4, data << 32)
        elif reg == 11:
            # Prefetchable memory limit (upper)
            self.prefetchable_mem_limit = byte_mask_update(self.prefetchable_mem_limit, mask << 4, data << 32)
        elif reg == 12:
            # IO base (upper)
            self.io_base = byte_mask_update(self.io_base, (mask & 0x3) << 2, data << 16)
            # IO limit (upper)
            self.io_limit = byte_mask_update(self.io_limit, (mask & 0xc), data)
        elif reg == 14:
            # Expansion ROM Base Address
            self.expansion_rom_addr = byte_mask_update(self.expansion_rom_addr,
                mask, data, self.expansion_rom_addr_mask) & 0xfffff800
            if mask & 0x1:
                self.expansion_rom_enable = (data & 1) != 0
        elif reg == 15:
            # Interrupt line
            if mask & 1:
                self.interrupt_line = data & 0xff
            # bridge control
            if mask & 0x4:
                self.parity_error_response_enable = (data & 1 << 16 != 0)
                self.serr_enable = (data & 1 << 17 != 0)
                self.secondary_bus_reset = (data & 1 << 22 != 0)
        else:
            await super().write_config_register(reg, data, mask)

    async def upstream_send(self, tlp):
        assert tlp.check()
        if self.upstream_tx_handler is None:
            raise Exception("Transmit handler not set")
        await self.upstream_tx_handler(tlp)

    async def upstream_recv(self, tlp):
        self.log.debug("Routing downstream TLP: %s", repr(tlp))
        assert tlp.check()
        if tlp.fmt_type == TlpType.CFG_READ_0 or tlp.fmt_type == TlpType.CFG_WRITE_0:
            await self.handle_tlp(tlp)
        elif tlp.fmt_type == TlpType.CFG_READ_1 or tlp.fmt_type == TlpType.CFG_WRITE_1:
            # config type 1
            if self.sec_bus_num <= tlp.dest_id.bus <= self.sub_bus_num:
                if tlp.dest_id.bus == self.sec_bus_num:
                    # targeted to directly connected device; change to type 0
                    if tlp.fmt_type == TlpType.CFG_READ_1:
                        tlp.fmt_type = TlpType.CFG_READ_0
                    elif tlp.fmt_type == TlpType.CFG_WRITE_1:
                        tlp.fmt_type = TlpType.CFG_WRITE_0
                await self.route_downstream_tlp(tlp, False)
            else:
                # error
                pass
        elif (tlp.fmt_type == TlpType.CPL or tlp.fmt_type == TlpType.CPL_DATA or
                tlp.fmt_type == TlpType.CPL_LOCKED or tlp.fmt_type == TlpType.CPL_LOCKED_DATA):
            # Completions
            if not self.root and tlp.requester_id == self.pcie_id:
                # for me
                await self.handle_tlp(tlp)
            elif self.sec_bus_num <= tlp.requester_id.bus <= self.sub_bus_num:
                await self.route_downstream_tlp(tlp, False)
            else:
                # error
                pass
        elif tlp.fmt_type == TlpType.MSG_ID or tlp.fmt_type == TlpType.MSG_DATA_ID:
            # ID routed message
            if not self.root and tlp.dest_id == self.pcie_id:
                # for me
                await self.handle_tlp(tlp)
            elif self.sec_bus_num <= tlp.dest_id.bus <= self.sub_bus_num:
                await self.route_downstream_tlp(tlp, False)
            else:
                # error
                pass
        elif (tlp.fmt_type == TlpType.IO_READ or tlp.fmt_type == TlpType.IO_WRITE):
            # IO read/write
            if self.match_bar(tlp.address, io=True):
                # for me
                await self.handle_tlp(tlp)
            elif self.io_base <= tlp.address <= self.io_limit:
                await self.route_downstream_tlp(tlp, False)
            else:
                # error
                pass
        elif (tlp.fmt_type == TlpType.MEM_READ or tlp.fmt_type == TlpType.MEM_READ_64 or
                tlp.fmt_type == TlpType.MEM_WRITE or tlp.fmt_type == TlpType.MEM_WRITE_64):
            # Memory read/write
            if self.match_bar(tlp.address):
                # for me
                await self.handle_tlp(tlp)
            elif (self.mem_base <= tlp.address <= self.mem_limit
                    or self.prefetchable_mem_base <= tlp.address <= self.prefetchable_mem_limit):
                await self.route_downstream_tlp(tlp, False)
            else:
                # error
                pass
        elif tlp.fmt_type == TlpType.MSG_TO_RC or tlp.fmt_type == TlpType.MSG_DATA_TO_RC:
            # Message to root complex
            # error
            pass
        elif tlp.fmt_type == TlpType.MSG_BCAST or tlp.fmt_type == TlpType.MSG_DATA_BCAST:
            # Message broadcast from root complex
            await self.route_downstream_tlp(tlp, False)
        elif tlp.fmt_type == TlpType.MSG_LOCAL or tlp.fmt_type == TlpType.MSG_DATA_LOCAL:
            # Message local to receiver
            # error
            pass
        elif tlp.fmt_type == TlpType.MSG_GATHER or tlp.fmt_type == TlpType.MSG_DATA_GATHER:
            # Message gather to root complex
            # error
            pass
        else:
            raise Exception("Unknown/invalid packet type")

    async def route_downstream_tlp(self, tlp, from_downstream=False):
        await self.downstream_send(tlp)

    async def downstream_send(self, tlp):
        assert tlp.check()
        if self.downstream_tx_handler is None:
            raise Exception("Transmit handler not set")
        await self.downstream_tx_handler(tlp)

    async def downstream_recv(self, tlp):
        self.log.debug("Routing upstream TLP: %s", repr(tlp))
        assert tlp.check()
        if tlp.fmt_type in [
            TlpType.CFG_READ_0,
            TlpType.CFG_WRITE_0,
            TlpType.CFG_READ_1,
            TlpType.CFG_WRITE_1,
        ]:
            # error
            pass
        elif tlp.fmt_type in [
            TlpType.CPL,
            TlpType.CPL_DATA,
            TlpType.CPL_LOCKED,
            TlpType.CPL_LOCKED_DATA,
        ]:
            # Completions
            if not self.root and tlp.requester_id == self.pcie_id:
                # for me
                await self.handle_tlp(tlp)
            elif self.sec_bus_num <= tlp.requester_id.bus <= self.sub_bus_num:
                if self.root and tlp.requester_id.bus == self.pri_bus_num and tlp.requester_id.device == 0:
                    await self.upstream_send(tlp)
                else:
                    await self.route_downstream_tlp(tlp, True)
            else:
                await self.upstream_send(tlp)
        elif tlp.fmt_type in [TlpType.MSG_ID, TlpType.MSG_DATA_ID]:
            # ID routed messages
            if not self.root and tlp.dest_id == self.pcie_id:
                # for me
                await self.handle_tlp(tlp)
            elif self.sec_bus_num <= tlp.dest_id.bus <= self.sub_bus_num:
                if self.root and tlp.dest_id.bus == self.pri_bus_num and tlp.dest_id.device == 0:
                    await self.upstream_send(tlp)
                else:
                    await self.route_downstream_tlp(tlp, True)
            else:
                await self.upstream_send(tlp)
        elif tlp.fmt_type in [TlpType.IO_READ, TlpType.IO_WRITE]:
            # IO read/write
            if self.match_bar(tlp.address, io=True):
                # for me
                await self.handle_tlp(tlp)
            elif self.io_base <= tlp.address <= self.io_limit:
                await self.route_downstream_tlp(tlp, True)
            else:
                await self.upstream_send(tlp)
        elif tlp.fmt_type in [
            TlpType.MEM_READ,
            TlpType.MEM_READ_64,
            TlpType.MEM_WRITE,
            TlpType.MEM_WRITE_64,
        ]:
            # Memory read/write
            if self.match_bar(tlp.address):
                # for me
                await self.handle_tlp(tlp)
            elif (self.mem_base <= tlp.address <= self.mem_limit
                    or self.prefetchable_mem_base <= tlp.address <= self.prefetchable_mem_limit):
                await self.route_downstream_tlp(tlp, True)
            else:
                await self.upstream_send(tlp)
        elif tlp.fmt_type in [TlpType.MSG_TO_RC, TlpType.MSG_DATA_TO_RC]:
            # Message to root complex
            await self.upstream_send(tlp)
        elif tlp.fmt_type in [TlpType.MSG_BCAST, TlpType.MSG_DATA_BCAST]:
            # Message broadcast from root complex
            # error
            pass
        elif tlp.fmt_type in [TlpType.MSG_LOCAL, TlpType.MSG_DATA_LOCAL]:
            # Message local to receiver
            # error
            pass
        elif tlp.fmt_type in [TlpType.MSG_GATHER, TlpType.MSG_DATA_GATHER]:
            # Message gather to root complex
            raise Exception("TODO")
        else:
            raise Exception("Unknown/invalid packet type")

    async def send(self, tlp):
        # route local transmissions as if they came in via downstream port
        await self.downstream_recv(tlp)


class SwitchUpstreamPort(Bridge):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.pcie_device_type = 0x5

        self.downstream_port = BusPort(self, self.downstream_recv)
        self.downstream_tx_handler = None

        self.vendor_id = 0x1234
        self.device_id = 0x0003

    async def route_downstream_tlp(self, tlp, from_downstream=False):
        assert tlp.check()

        # route downstream packet
        ok = False
        for p in self.downstream_port.other:
            dev = p.parent
            if tlp.fmt_type == TlpType.CFG_READ_0 or tlp.fmt_type == TlpType.CFG_WRITE_0:
                # config type 0
                if tlp.dest_id.device == dev.device_num and tlp.dest_id.function == dev.function_num:
                    await p.ext_recv(Tlp(tlp))
                    return
            elif tlp.fmt_type == TlpType.CFG_READ_1 or tlp.fmt_type == TlpType.CFG_WRITE_1:
                # config type 1
                if isinstance(dev, Bridge) and dev.sec_bus_num <= tlp.dest_id.bus <= dev.sub_bus_num:
                    await p.ext_recv(Tlp(tlp))
                    return
            elif (tlp.fmt_type == TlpType.CPL or tlp.fmt_type == TlpType.CPL_DATA or
                    tlp.fmt_type == TlpType.CPL_LOCKED or tlp.fmt_type == TlpType.CPL_LOCKED_DATA):
                # Completions
                if tlp.requester_id == dev.pcie_id:
                    await p.ext_recv(Tlp(tlp))
                    return
                elif isinstance(dev, Bridge) and dev.sec_bus_num <= tlp.requester_id.bus <= dev.sub_bus_num:
                    await p.ext_recv(Tlp(tlp))
                    return
            elif tlp.fmt_type == TlpType.MSG_ID or tlp.fmt_type == TlpType.MSG_DATA_ID:
                # ID routed message
                if tlp.dest_id == dev.pcie_id:
                    await p.ext_recv(Tlp(tlp))
                    return
                elif isinstance(dev, Bridge) and dev.sec_bus_num <= tlp.requester_id.bus <= dev.sub_bus_num:
                    await p.ext_recv(Tlp(tlp))
                    return
            elif (tlp.fmt_type == TlpType.IO_READ or tlp.fmt_type == TlpType.IO_WRITE):
                # IO read/write
                if dev.match_bar(tlp.address, True):
                    await p.ext_recv(Tlp(tlp))
                    return
                elif isinstance(dev, Bridge) and dev.io_base <= tlp.address <= dev.io_limit:
                    await p.ext_recv(Tlp(tlp))
                    return
            elif (tlp.fmt_type == TlpType.MEM_READ or tlp.fmt_type == TlpType.MEM_READ_64 or
                    tlp.fmt_type == TlpType.MEM_WRITE or tlp.fmt_type == TlpType.MEM_WRITE_64):
                # Memory read/write
                if dev.match_bar(tlp.address):
                    await p.ext_recv(Tlp(tlp))
                    return
                elif isinstance(dev, Bridge) and (dev.mem_base <= tlp.address <= dev.mem_limit or
                        dev.prefetchable_mem_base <= tlp.address <= dev.prefetchable_mem_limit):
                    await p.ext_recv(Tlp(tlp))
                    return
            elif tlp.fmt_type == TlpType.MSG_TO_RC or tlp.fmt_type == TlpType.MSG_DATA_TO_RC:
                # Message to root complex
                # error
                pass
            elif tlp.fmt_type == TlpType.MSG_BCAST or tlp.fmt_type == TlpType.MSG_DATA_BCAST:
                # Message broadcast from root complex
                await p.ext_recv(Tlp(tlp))
                ok = True
            elif tlp.fmt_type == TlpType.MSG_LOCAL or tlp.fmt_type == TlpType.MSG_DATA_LOCAL:
                # Message local to receiver
                # error
                pass
            elif tlp.fmt_type == TlpType.MSG_GATHER or tlp.fmt_type == TlpType.MSG_DATA_GATHER:
                # Message gather to root complex
                # error
                pass
            else:
                raise Exception("Unknown/invalid packet type")

        if not ok:
            self.log.info("Failed to route TLP")
            # Unsupported request
            cpl = Tlp.create_ur_completion_for_tlp(tlp, PcieId(self.bus_num, self.device_num, 0))
            self.log.debug("UR Completion: %s", repr(cpl))
            if from_downstream:
                await self.route_downstream_tlp(cpl, False)
            else:
                await self.upstream_send(cpl)


class SwitchDownstreamPort(Bridge):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.pcie_device_type = 0x6

        self.vendor_id = 0x1234
        self.device_id = 0x0004

    def connect(self, port):
        self.downstream_port.connect(port)


class HostBridge(SwitchUpstreamPort):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.vendor_id = 0x1234
        self.device_id = 0x0001

        self.pri_bus_num = 0
        self.sec_bus_num = 0
        self.sub_bus_num = 255

        self.class_code = 0x060000


class RootPort(SwitchDownstreamPort):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.pcie_device_type = 0x4

        self.vendor_id = 0x1234
        self.device_id = 0x0002

    def connect(self, port):
        self.downstream_port.connect(port)
